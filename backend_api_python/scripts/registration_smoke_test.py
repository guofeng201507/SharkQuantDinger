#!/usr/bin/env python3
"""
Registration smoke test: send-code -> register -> login.

It validates the self-service registration chain end to end without requiring a
working SMTP server: the backend persists the verification code in
``qd_verification_codes`` *before* attempting to send the email, so the code can
be read straight from the database even when SMTP is not configured.

Intended to run inside the backend container, which already has psycopg2, the
Flask app on 127.0.0.1:5000 and DATABASE_URL pointing at Postgres:

    docker exec quantdinger-backend python scripts/registration_smoke_test.py

Host usage works too when a reachable DB URL and API URL are supplied:

    python scripts/registration_smoke_test.py \
        --base-url http://127.0.0.1:5001 \
        --db-url postgresql://quantdinger:quantdinger123@127.0.0.1:5432/quantdinger_e2e

Exit code is 0 on PASS, 1 on FAIL, so the script can gate CI.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

try:
    import psycopg2
except ImportError:  # pragma: no cover - guidance for host runs
    psycopg2 = None


def _http(method: str, url: str, body: dict | None = None, token: str | None = None,
          timeout: int = 20) -> tuple[int, dict]:
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


def _fetch_code(db_url: str, email: str, code_type: str, timeout: float) -> str | None:
    """Poll qd_verification_codes for the newest unused code for this email/type."""
    deadline = time.time() + timeout
    conn = psycopg2.connect(db_url)
    try:
        conn.autocommit = True
        while time.time() < deadline:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT code FROM qd_verification_codes
                    WHERE email = %s AND type = %s AND used_at IS NULL
                    ORDER BY id DESC LIMIT 1
                    """,
                    (email, code_type),
                )
                row = cur.fetchone()
                if row:
                    return row[0]
            time.sleep(1)
    finally:
        conn.close()
    return None


def _purge_codes(db_url: str, email: str) -> None:
    conn = psycopg2.connect(db_url)
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("DELETE FROM qd_verification_codes WHERE email = %s", (email,))
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Registration smoke test (send-code -> register -> login)")
    parser.add_argument("--base-url", default="http://127.0.0.1:5000", help="Backend API base (default: in-container Flask)")
    parser.add_argument("--db-url", default=os.getenv("DATABASE_URL", ""), help="Postgres DSN (default: $DATABASE_URL)")
    parser.add_argument("--email", default=f"qd_smoke_{int(time.time())}@example.com", help="Test email")
    parser.add_argument("--username", default=f"qdsmoke{int(time.time())}", help="Test username")
    parser.add_argument("--password", default="QdSmoke!2026", help="Test password")
    parser.add_argument("--admin-user", default=os.getenv("ADMIN_USER", ""), help="Admin username for cleanup")
    parser.add_argument("--admin-password", default=os.getenv("ADMIN_PASSWORD", ""), help="Admin password for cleanup")
    parser.add_argument("--keep", action="store_true", help="Keep the created user (skip admin cleanup)")
    parser.add_argument("--code-timeout", type=float, default=20.0, help="Seconds to wait for the code to appear")
    args = parser.parse_args()

    if psycopg2 is None:
        print("FAIL: psycopg2 is required. Run inside the backend container or install psycopg2-binary.")
        return 1
    if not args.db_url:
        print("FAIL: no --db-url and DATABASE_URL is unset.")
        return 1

    base = args.base_url.rstrip("/")
    checks: list[tuple[str, bool, str]] = []

    def record(name: str, ok: bool, detail: str = "") -> bool:
        checks.append((name, ok, detail))
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" - {detail}" if detail else ""))
        return ok

    # 1. Preflight: registration must be enabled.
    status, cfg = _http("GET", f"{base}/api/auth/security-config")
    enabled = bool(cfg.get("data", {}).get("registration_enabled"))
    if not record("security-config reachable & registration enabled", status == 200 and enabled, f"http={status} enabled={enabled}"):
        return _summary(checks)

    # 2. Request a verification code. The code is persisted even if email send fails.
    status, body = _http("POST", f"{base}/api/auth/send-code", {"email": args.email, "type": "register"})
    sent = body.get("code") == 1
    record("send-code accepted", status in (200, 500), f"http={status} msg={body.get('msg')}")
    if status == 429:
        print("FAIL: rate limited while requesting the code.")
        return _summary(checks)
    if not sent:
        print(f"[WARN] email send did not report success ({body.get('msg')}); reading code from DB anyway.")

    # 3. Read the code from the database.
    code = _fetch_code(args.db_url, args.email, "register", args.code_timeout)
    if not record("verification code persisted in DB", bool(code), f"code={'***' if code else 'missing'}"):
        return _summary(checks)

    # 4. Register.
    status, body = _http("POST", f"{base}/api/auth/register", {
        "email": args.email, "code": code, "username": args.username, "password": args.password,
    })
    token = (body.get("data") or {}).get("token")
    user_id = ((body.get("data") or {}).get("userinfo") or {}).get("id")
    if not record("register succeeds", status == 200 and body.get("code") == 1 and bool(token), f"http={status} msg={body.get('msg')}"):
        _cleanup(args, user_id)
        return _summary(checks)

    # 5. Login with the new credentials.
    status, body = _http("POST", f"{base}/api/auth/login", {"username": args.username, "password": args.password})
    login_token = (body.get("data") or {}).get("token")
    if not record("login succeeds", status == 200 and body.get("code") == 1 and bool(login_token), f"http={status} msg={body.get('msg')}"):
        _cleanup(args, user_id)
        return _summary(checks)

    # 6. The token resolves to the freshly created account.
    status, body = _http("GET", f"{base}/api/users/profile", token=login_token)
    profile = body.get("data") or {}
    record("profile matches new user", status == 200 and profile.get("username") == args.username,
           f"username={profile.get('username')} credits={profile.get('credits')}")

    _cleanup(args, user_id)
    return _summary(checks)


def _cleanup(args, user_id) -> None:
    """Remove the test user (via admin API) and the leftover verification codes."""
    if not args.keep and args.admin_user and args.admin_password and user_id:
        status, body = _http("POST", f"{args.base_url.rstrip('/')}/api/auth/login",
                             {"username": args.admin_user, "password": args.admin_password})
        admin_token = (body.get("data") or {}).get("token")
        if admin_token:
            st, _ = _http("DELETE", f"{args.base_url.rstrip('/')}/api/users/delete?id={user_id}", token=admin_token)
            print(f"[INFO] cleanup delete user id={user_id} -> http={st}")
        else:
            print("[WARN] admin login failed; test user left in place.")
    elif not args.keep:
        print("[WARN] no admin credentials provided; test user left in place (use --keep to silence).")
    try:
        _purge_codes(args.db_url, args.email)
    except Exception as exc:  # pragma: no cover
        print(f"[WARN] code purge failed: {exc}")


def _summary(checks: list[tuple[str, bool, str]]) -> int:
    failed = [c for c in checks if not c[1]]
    print("\n==== summary ====")
    print(f"checks: {len(checks)}  passed: {len(checks) - len(failed)}  failed: {len(failed)}")
    if failed:
        for name, _, detail in failed:
            print(f"  FAILED: {name} {detail}")
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
