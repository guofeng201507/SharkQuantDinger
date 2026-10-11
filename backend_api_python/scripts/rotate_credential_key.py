#!/usr/bin/env python3
"""Rotate CREDENTIAL_ENCRYPTION_KEY: re-encrypt stored credential and MFA blobs.

Replacing CREDENTIAL_ENCRYPTION_KEY strands every row encrypted with the
previous key, because decryption only tries the current key and the legacy
SECRET_KEY. This script re-encrypts those rows to the new key so the old key
can be retired.

Procedure (writers stopped):
  1. Generate the new key and stop every service running the backend image.
  2. Dry run:   python scripts/rotate_credential_key.py \
                    --new-key-file /root/rotate/new.key --old-key-file /root/rotate/old.key
  3. Apply:     ... --apply
  4. Put the new key into .env (CREDENTIAL_ENCRYPTION_KEY=...), start the services.

Environment alternative:
  CREDENTIAL_ENCRYPTION_KEY=<new> OLD_CREDENTIAL_ENCRYPTION_KEY=<old> \
      python scripts/rotate_credential_key.py --apply

Old-key candidates are tried in order: --old-key-file, OLD_CREDENTIAL_ENCRYPTION_KEY,
SECRET_KEY, then the values found in /app/.env when that file is present (covers
legacy ciphertexts without exporting secrets). Exits non-zero when any non-empty
row cannot be decrypted with the new key after the rotation pass.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from typing import Any, Dict, Iterable, List, Optional, Tuple

from app.utils.credential_crypto import decrypt_with_key, encrypt_with_key
from app.utils.db import get_db_connection

# (table, primary key column, ciphertext column)
TARGETS: Tuple[Tuple[str, str, str], ...] = (
    ("qd_exchange_credentials", "id", "encrypted_config"),
    ("qd_user_mfa", "user_id", "secret_encrypted"),
)

MAX_PASSES = 3

# Inside the container the deployment .env is bind-mounted here; reading it
# covers the legacy SECRET_KEY fallback without exporting secrets on the
# command line. Overridable so tests and bare-metal runs can point elsewhere.
DEFAULT_ENV_FILE = "/app/.env"


def _fingerprint(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()[:12]


def _read_key_file(path: str) -> str:
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read().strip()


def _read_dotenv_keys(path: str) -> List[Tuple[str, str]]:
    """Return (label, value) pairs for the credential/SECRET keys in a dotenv file."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except OSError:
        return []
    found: List[Tuple[str, str]] = []
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        if name not in ("CREDENTIAL_ENCRYPTION_KEY", "SECRET_KEY"):
            continue
        value = value.strip().strip('"').strip("'")
        if value:
            found.append((f"{path} {name}", value))
    return found


def _resolve_keys(args: argparse.Namespace) -> Tuple[str, List[Tuple[str, str]]]:
    new_key = ""
    if args.new_key_file:
        new_key = _read_key_file(args.new_key_file)
    else:
        new_key = (os.getenv("CREDENTIAL_ENCRYPTION_KEY") or "").strip()
    if not new_key:
        raise SystemExit(
            "New key missing: pass --new-key-file or set CREDENTIAL_ENCRYPTION_KEY."
        )

    old_keys: List[Tuple[str, str]] = []
    if args.old_key_file:
        value = _read_key_file(args.old_key_file)
        if value:
            old_keys.append(("--old-key-file", value))
    for label in ("OLD_CREDENTIAL_ENCRYPTION_KEY", "SECRET_KEY"):
        value = (os.getenv(label) or "").strip()
        if value:
            old_keys.append((label, value))
    old_keys.extend(_read_dotenv_keys(DEFAULT_ENV_FILE))

    deduped: List[Tuple[str, str]] = []
    seen = {new_key}
    for label, value in old_keys:
        if value not in seen:
            seen.add(value)
            deduped.append((label, value))
    return new_key, deduped


def classify(
    stored: Any, new_key: str, old_keys: Iterable[Tuple[str, str]]
) -> Tuple[str, Optional[str], Optional[str]]:
    """Classify one stored blob.

    Returns (status, new_ciphertext, old_key_label) with status one of
    "empty", "already", "rotate", "failed".
    """
    text = stored.decode("utf-8") if isinstance(stored, (bytes, bytearray)) else str(stored or "")
    if not text.strip():
        return "empty", None, None
    try:
        decrypt_with_key(new_key, text)
        return "already", None, None
    except ValueError:
        pass
    for label, key in old_keys:
        try:
            plaintext = decrypt_with_key(key, text)
        except ValueError:
            continue
        return "rotate", encrypt_with_key(new_key, plaintext), label
    return "failed", None, None


def _select_rows(conn: Any, table: str, pk: str, col: str) -> List[Tuple[Any, Any]]:
    cur = conn.cursor()
    try:
        cur.execute(f"SELECT {pk} AS row_id, {col} AS value FROM {table}")
        rows = cur.fetchall()
    finally:
        cur.close()
    out: List[Tuple[Any, Any]] = []
    for row in rows:
        if isinstance(row, dict):
            out.append((row.get("row_id"), row.get("value")))
        else:
            out.append((row[0], row[1]))
    return out


def run(
    conn: Any,
    new_key: str,
    old_keys: List[Tuple[str, str]],
    *,
    apply: bool,
    targets: Tuple[Tuple[str, str, str], ...] = TARGETS,
) -> Dict[str, List[str]]:
    """Re-encrypt every blob readable with an old key. Returns per-table reports."""
    report: Dict[str, List[str]] = {}
    failures: List[str] = []

    for table, pk, col in targets:
        try:
            rows = _select_rows(conn, table, pk, col)
        except Exception as exc:  # missing table on older databases is not fatal
            try:
                conn.rollback()
            except Exception:
                pass
            report[table] = [f"skipped (cannot read: {exc})"]
            print(f"[{table}] skipped: cannot read rows ({exc})")
            continue

        rotated_ids: set = set()
        used_labels: Dict[str, int] = {}
        for _ in range(MAX_PASSES):
            changed = 0
            for row_id, stored in rows:
                status, new_cipher, label = classify(stored, new_key, old_keys)
                if status != "rotate":
                    continue
                if row_id not in rotated_ids:
                    used_labels[label or "?"] = used_labels.get(label or "?", 0) + 1
                    rotated_ids.add(row_id)
                changed += 1
                if not apply:
                    continue
                cur = conn.cursor()
                try:
                    cur.execute(
                        f"UPDATE {table} SET {col} = %s WHERE {pk} = %s",
                        (new_cipher, row_id),
                    )
                    conn.commit()
                finally:
                    cur.close()
                for idx, (rid, _) in enumerate(rows):
                    if rid == row_id:
                        rows[idx] = (rid, new_cipher)
                        break
            # A concurrent writer holding the old key can add rows between
            # passes; extra passes converge instead of failing the run.
            if not apply or changed == 0:
                break

        empty = already = failed = 0
        for row_id, stored in rows:
            if row_id in rotated_ids:
                continue
            status, _, _ = classify(stored, new_key, old_keys)
            if status == "empty":
                empty += 1
            elif status == "already":
                already += 1
            else:
                failed += 1
                failures.append(f"{table}.{pk}={row_id}: not decryptable with the new key")
        summary = [
            f"rows={len(rows)} rotated={len(rotated_ids)} already={already} "
            f"empty={empty} failed={failed}"
        ]
        for label, count in sorted(used_labels.items()):
            summary.append(f"re-encrypted with old key from {label}: {count}")
        report[table] = summary
        print(f"[{table}] " + "; ".join(summary))

    if not apply:
        print("DRY RUN - no rows were modified (pass --apply to write)")
    if failures:
        print("FAILURES:")
        for line in failures:
            print(f"  - {line}")
    report["failures"] = failures
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write the re-encrypted rows (default is a dry run)",
    )
    parser.add_argument(
        "--new-key-file",
        help="file containing the new key (default: env CREDENTIAL_ENCRYPTION_KEY)",
    )
    parser.add_argument(
        "--old-key-file",
        help="file containing the previous key (fallbacks: OLD_CREDENTIAL_ENCRYPTION_KEY, SECRET_KEY)",
    )
    args = parser.parse_args()

    new_key, old_keys = _resolve_keys(args)
    print(f"new key fingerprint: {_fingerprint(new_key)}")
    if not old_keys:
        print(
            "no old keys supplied (--old-key-file / OLD_CREDENTIAL_ENCRYPTION_KEY / SECRET_KEY); "
            "rows under the previous key will be reported as failures"
        )
    for label, value in old_keys:
        print(f"old key candidate: {label} fingerprint {_fingerprint(value)}")

    with get_db_connection() as conn:
        report = run(conn, new_key, old_keys, apply=args.apply)
    return 1 if report["failures"] else 0


if __name__ == "__main__":
    sys.exit(main())
