#!/usr/bin/env python3
"""Publish a markdown document (default: the user guide) into the docs table.

The in-app user guide reads `/api/docs/<slug>` and falls back to the copy bundled
with the frontend build, so this script is how the DB edition is created or
refreshed — no frontend rebuild needed.

    python scripts/import_user_guide.py \
        --base-url https://shark.aiorz.cc \
        --admin-user "$ADMIN_USER" --admin-password "$ADMIN_PASSWORD" \
        --file ../frontend/USER_GUIDE.md --slug user-guide --locale zh-CN

Exit code 0 on success.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path


def _http(method: str, url: str, body: dict | None = None, token: str | None = None,
          timeout: int = 60) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode() or "{}"
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"raw": raw}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True, help="e.g. https://shark.aiorz.cc")
    ap.add_argument("--admin-user", required=True)
    ap.add_argument("--admin-password", required=True)
    ap.add_argument("--file", required=True, help="markdown file to publish")
    ap.add_argument("--slug", default="user-guide")
    ap.add_argument("--locale", default="zh-CN")
    ap.add_argument("--title", default="")
    args = ap.parse_args()

    path = Path(args.file)
    if not path.is_file():
        print(f"FAIL: {path} not found")
        return 1
    content = path.read_text(encoding="utf-8")
    print(f"source: {path} ({len(content)} chars, {len(content.encode('utf-8'))} bytes)")

    base = args.base_url.rstrip("/")
    status, body = _http("POST", f"{base}/api/auth/login",
                         {"username": args.admin_user, "password": args.admin_password})
    token = (body.get("data") or {}).get("token")
    if not token:
        print(f"FAIL: admin login http={status} msg={body.get('msg')}")
        return 1
    print("admin login ok")

    status, body = _http("PUT", f"{base}/api/docs/{args.slug}",
                         {"content_md": content, "locale": args.locale, "title": args.title},
                         token)
    if status != 200 or body.get("code") != 1:
        print(f"FAIL: save http={status} msg={body.get('msg')}")
        return 1
    print(f"saved: {json.dumps(body.get('data'), ensure_ascii=False)}")

    status, body = _http("GET", f"{base}/api/docs/{args.slug}", token=token)
    doc = body.get("data") or {}
    ok = status == 200 and len(doc.get("content_md") or "") == len(content)
    print(f"verified: http={status} locale={doc.get('locale')} chars={len(doc.get('content_md') or '')}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
