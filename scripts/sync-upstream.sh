#!/bin/bash
# Sync new commits from the upstream QuantDinger repository into this fork.
#
# This fork is the production/product line, so the sync is one-way: we pull
# upstream's features and fixes in, and never push our changes back. Because
# the fork diverges heavily (branding, i18n, local docs), a merge can conflict;
# this script always lets you see the damage before committing to it.
#
# Usage:
#   ./scripts/sync-upstream.sh              # preview only: nothing is modified
#   ./scripts/sync-upstream.sh --apply      # merge for real, tag a rollback point
#   ./scripts/sync-upstream.sh --apply --test   # ... and run the test suites
#
# It never pushes and never deploys. Pushing to origin/main is what the ECS
# production host pulls (git pull --ff-only), so that stays a deliberate manual
# step after you have reviewed and tested the merge.
#
# Env overrides:
#   SYNC_BRANCH      branch to sync into        (default: main)
#   SYNC_UPSTREAM    upstream remote name       (default: upstream)
#   BACKEND_TEST_IMAGE  backend image for tests (default: quantdinger-backend:local)

set -euo pipefail

BRANCH="${SYNC_BRANCH:-main}"
UPSTREAM="${SYNC_UPSTREAM:-upstream}"
BACKEND_IMAGE="${BACKEND_TEST_IMAGE:-quantdinger-backend:local}"

APPLY=0
RUN_TESTS=0
for arg in "$@"; do
  case "$arg" in
    --apply) APPLY=1 ;;
    --test) RUN_TESTS=1 ;;
    -h|--help) sed -n '2,25p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown argument: $arg (try --help)" >&2; exit 2 ;;
  esac
done

cd "$(git rev-parse --show-toplevel)"

if ! git remote get-url "$UPSTREAM" >/dev/null 2>&1; then
  echo "Remote '$UPSTREAM' is not configured. Add it with:" >&2
  echo "  git remote add $UPSTREAM https://github.com/OpenByteInc/QuantDinger.git" >&2
  exit 2
fi

current="$(git rev-parse --abbrev-ref HEAD)"
if [ "$current" != "$BRANCH" ]; then
  echo "Refusing to run: on branch '$current', expected '$BRANCH' (set SYNC_BRANCH to override)." >&2
  exit 2
fi

# A tracked change would be entangled with the merge and hard to untangle.
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  echo "Refusing to run: working tree has uncommitted tracked changes. Commit or stash first." >&2
  exit 2
fi

echo "==> Fetching $UPSTREAM"
git fetch "$UPSTREAM" --prune

ahead="$(git rev-list --count "$UPSTREAM/main..$BRANCH")"
behind="$(git rev-list --count "$BRANCH..$UPSTREAM/main")"
echo "fork vs $UPSTREAM/main: ahead $ahead, behind $behind"

if [ "$behind" -eq 0 ]; then
  echo "Already up to date with $UPSTREAM/main; nothing to sync."
  exit 0
fi

echo
echo "==> Upstream commits not in $BRANCH ($behind):"
git --no-pager log --oneline --no-merges "$BRANCH..$UPSTREAM/main"
merges="$(git rev-list --count --merges "$BRANCH..$UPSTREAM/main")"
[ "$merges" -gt 0 ] && echo "  (+ $merges merge commits)"
echo
echo "==> Files upstream touches:"
git --no-pager diff --stat "$BRANCH"..."$UPSTREAM/main" | tail -n 1

if [ "$APPLY" -eq 0 ]; then
  echo
  echo "==> Trial merge (detecting conflicts; nothing will be committed)"
  git merge --no-commit --no-ff "$UPSTREAM/main" >/dev/null 2>&1 || true
  conflicts="$(git diff --name-only --diff-filter=U)"
  # Only a stop with MERGE_HEAD is a real merge state worth aborting.
  if git rev-parse -q --verify MERGE_HEAD >/dev/null 2>&1; then
    if [ -n "$conflicts" ]; then
      echo "CONFLICTS in $(echo "$conflicts" | wc -l | tr -d ' ') file(s):"
      echo "$conflicts" | sed 's/^/  /'
      echo
      echo "This merge needs manual resolution. Preferred path for a conflicted sync:"
      echo "  git checkout -b sync/upstream-\$(date +%Y%m%d)   # do it on a throwaway branch"
      echo "  git merge $UPSTREAM/main                           # resolve, then test"
      echo "  # or cherry-pick just the features you want instead of merging everything"
    else
      echo "Clean merge (no conflicts). Apply it with: ./scripts/sync-upstream.sh --apply"
    fi
    git merge --abort
  else
    echo "Merge produced no changes (unexpected); inspect manually."
    git merge --abort 2>/dev/null || true
  fi
  echo
  echo "Preview only: $BRANCH is unchanged."
  exit 0
fi

tag="pre-sync-$(date +%Y%m%d-%H%M)"
echo
echo "==> Checkpoint tag $tag at current $BRANCH (local rollback point)"
git tag "$tag"

echo "==> Merging $UPSTREAM/main into $BRANCH"
if git merge --no-ff -m "chore(sync): merge $UPSTREAM/main into $BRANCH" "$UPSTREAM/main"; then
  echo "Merge committed."
else
  echo
  echo "Merge stopped with conflicts. Resolve them, then 'git commit' to finish." >&2
  echo "Conflict files:" >&2
  git diff --name-only --diff-filter=U | sed 's/^/  /' >&2
  echo "Abandon the attempt with: git merge --abort (then delete tag $tag)" >&2
  exit 1
fi

if [ "$RUN_TESTS" -eq 1 ]; then
  echo
  echo "==> MCP package tests"
  if python3 -c "import mcp" >/dev/null 2>&1; then
    PYTHONPATH=mcp_server/src python3 -m pytest mcp_server/tests -q
  else
    echo "Skipped: 'mcp' is not importable by python3. Use the pinned venv, e.g.:"
    echo "  python3 -m venv /tmp/mcp-venv && /tmp/mcp-venv/bin/pip install 'mcp==1.28.1'"
    echo "  PYTHONPATH=mcp_server/src /tmp/mcp-venv/bin/python -m pytest mcp_server/tests -q"
  fi

  echo
  echo "==> Backend agent/contract tests (via $BACKEND_IMAGE)"
  if docker image inspect "$BACKEND_IMAGE" >/dev/null 2>&1; then
    docker run --rm --entrypoint sh \
      -v "$PWD":/repo -w /repo/backend_api_python \
      -e PYTHONPATH=/repo/backend_api_python \
      "$BACKEND_IMAGE" \
      -c "pip install -q --disable-pip-version-check pytest >/dev/null 2>&1; python -m pytest tests/test_ai_agent_contract_alignment.py tests/test_agent_strategy_sources.py tests/test_agent_current_contract.py -q"
  else
    echo "Skipped: image '$BACKEND_IMAGE' not found. Build it (docker compose build backend) or set BACKEND_TEST_IMAGE."
  fi
fi

echo
echo "Done. Next steps (manual, deliberate):"
echo "  git push origin $BRANCH      # ECS pulls this with 'git pull --ff-only'"
echo "  Rollback if production breaks: git reset --hard $tag && git push --force-with-lease origin $BRANCH"
