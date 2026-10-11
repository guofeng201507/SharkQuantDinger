"""Unit tests for scripts/rotate_credential_key.py — no live database required."""

from __future__ import annotations

import argparse

import pytest

from app.utils.credential_crypto import decrypt_with_key, encrypt_with_key
from scripts import rotate_credential_key as rotate
from scripts.rotate_credential_key import _read_dotenv_keys, _resolve_keys, classify, run

NEW_KEY = "new-key-0123456789abcdef0123456789abcdef"
OLD_KEY = "old-key-fedcba9876543210fedcba9876543210"
LEGACY_KEY = "legacy-secret-0011223344556677889900"


class _FakeCursor:
    def __init__(self, conn):
        self._conn = conn
        self._rows = []

    def execute(self, query, params=None):
        statement = " ".join(query.split())
        if statement.upper().startswith("SELECT"):
            table = statement.split("FROM", 1)[1].strip().split()[0]
            if table not in self._conn.tables:
                raise RuntimeError(f'relation "{table}" does not exist')
            self._rows = [
                {"row_id": row_id, "value": value}
                for row_id, value in self._conn.tables[table].items()
            ]
        elif statement.upper().startswith("UPDATE"):
            _, table, _, column = statement.split()[:4]
            new_value, row_id = params
            self._conn.tables[table][row_id] = new_value

    def fetchall(self):
        return self._rows

    def close(self):
        pass


class _FakeConn:
    def __init__(self, tables=None):
        self.tables = tables if tables is not None else {}
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return _FakeCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def test_classify_states():
    old_keys = [("OLD_CREDENTIAL_ENCRYPTION_KEY", OLD_KEY)]

    status, new_value, label = classify("", NEW_KEY, old_keys)
    assert status == "empty" and new_value is None

    status, _, _ = classify(encrypt_with_key(NEW_KEY, "{}"), NEW_KEY, old_keys)
    assert status == "already"

    status, new_value, label = classify(encrypt_with_key(OLD_KEY, '{"a":1}'), NEW_KEY, old_keys)
    assert status == "rotate" and label == "OLD_CREDENTIAL_ENCRYPTION_KEY"
    assert decrypt_with_key(NEW_KEY, new_value) == '{"a":1}'

    status, _, _ = classify(encrypt_with_key("some-other-key", "{}"), NEW_KEY, old_keys)
    assert status == "failed"


def test_classify_legacy_fallback_label():
    status, new_value, label = classify(
        encrypt_with_key(LEGACY_KEY, "{}"), NEW_KEY, [("SECRET_KEY", LEGACY_KEY)]
    )
    assert status == "rotate" and label == "SECRET_KEY"
    assert decrypt_with_key(NEW_KEY, new_value) == "{}"


def test_run_reencrypts_all_rows_and_verifies():
    old_blob = encrypt_with_key(OLD_KEY, '{"secret":"v"}')
    new_blob = encrypt_with_key(NEW_KEY, "{}")
    conn = _FakeConn(
        {
            "qd_exchange_credentials": {1: old_blob, 2: new_blob},
            "qd_user_mfa": {7: encrypt_with_key(LEGACY_KEY, "MFA")},
        }
    )
    report = run(
        conn,
        NEW_KEY,
        [("OLD_CREDENTIAL_ENCRYPTION_KEY", OLD_KEY), ("SECRET_KEY", LEGACY_KEY)],
        apply=True,
    )

    assert report["failures"] == []
    assert "rows=2 rotated=1 already=1" in "; ".join(report["qd_exchange_credentials"])
    assert "rows=1 rotated=1 already=0" in "; ".join(report["qd_user_mfa"])
    assert decrypt_with_key(NEW_KEY, conn.tables["qd_exchange_credentials"][1]) == '{"secret":"v"}'
    assert decrypt_with_key(NEW_KEY, conn.tables["qd_user_mfa"][7]) == "MFA"
    with pytest.raises(ValueError):
        decrypt_with_key(OLD_KEY, conn.tables["qd_exchange_credentials"][1])


def test_run_dry_run_writes_nothing():
    conn = _FakeConn(
        {"qd_exchange_credentials": {1: encrypt_with_key(OLD_KEY, "{}")}, "qd_user_mfa": {}}
    )
    before = dict(conn.tables["qd_exchange_credentials"])
    report = run(
        conn, NEW_KEY, [("OLD_CREDENTIAL_ENCRYPTION_KEY", OLD_KEY)], apply=False
    )

    assert conn.tables["qd_exchange_credentials"] == before
    assert conn.commits == 0
    assert "rotated=1" in "; ".join(report["qd_exchange_credentials"])


def test_run_reports_undecryptable_rows():
    conn = _FakeConn(
        {
            "qd_exchange_credentials": {1: encrypt_with_key("unknown-key", "{}")},
            "qd_user_mfa": {},
        }
    )
    report = run(conn, NEW_KEY, [("OLD_CREDENTIAL_ENCRYPTION_KEY", OLD_KEY)], apply=True)

    assert len(report["failures"]) == 1
    assert "qd_exchange_credentials.id=1" in report["failures"][0]


def test_run_skips_missing_tables():
    conn = _FakeConn({"qd_exchange_credentials": {}})
    report = run(conn, NEW_KEY, [], apply=True)

    assert "skipped" in report["qd_user_mfa"][0]
    assert report["failures"] == []


def test_resolve_keys_dedupes_new_key_and_reads_files(tmp_path, monkeypatch):
    monkeypatch.delenv("OLD_CREDENTIAL_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", NEW_KEY)
    monkeypatch.setattr(rotate, "DEFAULT_ENV_FILE", str(tmp_path / "absent.env"))
    old_file = tmp_path / "old.key"
    old_file.write_text(OLD_KEY + "\n", encoding="utf-8")

    new_key, old_keys = _resolve_keys(
        argparse.Namespace(new_key_file=None, old_key_file=str(old_file))
    )

    assert new_key == NEW_KEY
    assert old_keys == [("--old-key-file", OLD_KEY)]

    # Same value as the new key must not be tried as an old key.
    monkeypatch.setenv("OLD_CREDENTIAL_ENCRYPTION_KEY", NEW_KEY)
    _, old_keys = _resolve_keys(
        argparse.Namespace(new_key_file=None, old_key_file=str(old_file))
    )
    assert ("OLD_CREDENTIAL_ENCRYPTION_KEY", NEW_KEY) not in old_keys


def test_resolve_keys_reads_deployment_env_file(tmp_path, monkeypatch):
    monkeypatch.delenv("OLD_CREDENTIAL_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", NEW_KEY)
    env_file = tmp_path / "deploy.env"
    env_file.write_text(
        f"SECRET_KEY='{LEGACY_KEY}'\nCREDENTIAL_ENCRYPTION_KEY={OLD_KEY}\nUNRELATED=1\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(rotate, "DEFAULT_ENV_FILE", str(env_file))

    _, old_keys = _resolve_keys(argparse.Namespace(new_key_file=None, old_key_file=None))

    assert sorted(old_keys) == sorted(
        [
            (f"{env_file} SECRET_KEY", LEGACY_KEY),
            (f"{env_file} CREDENTIAL_ENCRYPTION_KEY", OLD_KEY),
        ]
    )


def test_read_dotenv_keys_ignores_missing_and_malformed(tmp_path):
    assert _read_dotenv_keys(str(tmp_path / "absent.env")) == []

    env_file = tmp_path / "broken.env"
    env_file.write_text("# comment\nnot a key value\nSECRET_KEY=\n", encoding="utf-8")
    assert _read_dotenv_keys(str(env_file)) == []
