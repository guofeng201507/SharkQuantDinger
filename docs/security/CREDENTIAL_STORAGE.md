# Broker credential storage and security

How trading credentials saved through the UI (Alpaca / IBKR panels, **Settings → Broker Credentials**) are stored, what the API exposes, and what an operator must protect.

## What is stored, and where

One row per credential in `qd_exchange_credentials`, scoped to its owner:

| column | contents |
|---|---|
| `user_id` | owner; every read is scoped to the caller's own id |
| `exchange_id` | `alpaca`, `binance`, `ibkr`, … |
| `name` / `api_key_hint` | display label and a masked hint (`PK…abcd (paper)`) |
| `encrypted_config` | **Fernet ciphertext** of the full config JSON |

The ciphertext decrypts to:

```json
{ "exchange_id": "alpaca", "api_key": "PK…", "secret_key": "…", "paper": true,
  "market_category": "USStock", "market_type": "spot" }
```

Key and secret exist **only inside that encrypted blob** — the database never holds plaintext, and the hint column is masked by construction.

## Encryption

- **Fernet** (AES-128-CBC + HMAC-SHA256, authenticated) — `app/utils/credential_crypto.py`.
- Key material: `base64url(sha256(CREDENTIAL_ENCRYPTION_KEY))`. Decryption also tries the legacy `SECRET_KEY` derivation so ciphertexts written by older releases remain readable; new writes always use `CREDENTIAL_ENCRYPTION_KEY`.
- `CREDENTIAL_ENCRYPTION_KEY` lives in the deployment `.env` (root file, mounted into the containers). It must stay `chmod 600`.

## What the API exposes

- `GET /api/../credentials` returns the **hint only** — `encrypted_config` is dropped before the response is built.
- The Alpaca/IBKR status endpoints return host, mode, account id and booleans — never key material.
- Provider credentials are redacted from logs (see the redaction pass in `app/utils/redaction.py`).

## Boundaries

- Only **official exchange hosts over HTTPS** are accepted; a user-supplied `baseUrl` is rejected (`ALPACA_BASE_URL_OVERRIDE_NOT_ALLOWED`).
- Every load is scoped by `user_id`; the generic credential vault UI is gated by the `credentials` permission (admin), the broker panels by login.
- Agent Tokens can never reach credentials (`C` scope is admin-only and self-service tokens cannot request it).

## Operator runbook

1. **Back up `.env`** (password manager or offline vault). `CREDENTIAL_ENCRYPTION_KEY` is the master key: if it is lost with the server, stored credentials are **unrecoverable** — that property is the point of the encryption.
2. Keep every `.env.bak*` at `0600` as well: backups may contain the legacy `SECRET_KEY`, which can decrypt old ciphertexts.
3. Database dumps contain ciphertext only; they still deserve normal backup protection but do not leak key material by themselves.
4. Rotation: **replacing `CREDENTIAL_ENCRYPTION_KEY` alone strands every row encrypted with the previous key** — decryption only tries the current key and the legacy `SECRET_KEY`. Run the rotation script below *before* swapping the key in `.env`; it re-encrypts all rows so the old key can be retired.
5. Venue-side hygiene: grant trading keys the minimum permissions, disable withdrawals, prefer a dedicated subaccount, and revoke keys that are no longer used.

## Rotating the key

`scripts/rotate_credential_key.py` re-encrypts every stored blob — broker
credentials (`qd_exchange_credentials.encrypted_config`) and TOTP secrets
(`qd_user_mfa.secret_encrypted`) — from the old key to the new one. Plan a short
maintenance window:

1. Generate the new key and store it with `0600`, e.g. `/root/rotate-keys/new.key`:

   ```bash
   python3 -c "import secrets; print(secrets.token_hex(32))"
   ```

2. Stop every service that runs the backend image (backend and all workers) so no
   process keeps writing under the old key.
3. From the repo root on the server, dry-run first, then apply:

   ```bash
   docker compose run --rm --no-deps \
     -v /root/rotate-keys:/rotate-keys:ro \
     backend python scripts/rotate_credential_key.py \
       --new-key-file /rotate-keys/new.key --old-key-file /rotate-keys/old.key

   docker compose run --rm --no-deps \
     -v /root/rotate-keys:/rotate-keys:ro \
     backend python scripts/rotate_credential_key.py \
       --new-key-file /rotate-keys/new.key --old-key-file /rotate-keys/old.key --apply
   ```

   The script also treats the mounted `/app/.env` values
   (`CREDENTIAL_ENCRYPTION_KEY`, `SECRET_KEY`) as old-key candidates, so legacy
   ciphertexts are covered without exporting secrets to the shell. A non-zero
   exit means some row could not be decrypted — do **not** swap the key until it
   passes clean.
4. Put the new key into the deployment `.env` (`CREDENTIAL_ENCRYPTION_KEY=...`),
   keep the file `chmod 600`, and start the services again.
5. Verify one credential round-trip in the UI (Settings → Broker Credentials),
   then delete the key files and retire the old key from your backups.

## FAQ: why is the Alpaca base URL shown without `/v2`?

Alpaca's REST documentation lists endpoints such as `https://paper-api.alpaca.markets/v2/account`, but the `alpaca-py` SDK takes a **host-level** base URL and appends the API version itself:

```python
# alpaca-py RESTClient
url = base_url + "/" + version + path   # version defaults to "v2"
```

So `https://paper-api.alpaca.markets` + `/v2/account` becomes exactly the documented URL. Passing `.../v2` to the SDK would produce `/v2/v2/account`; `normalize_base_url()` strips a user-entered trailing `/v2` for that reason, and custom hosts are rejected outright.

If a connect attempt fails, the UI now shows the reason Alpaca returned (authentication failed, key-prefix/account-mode mismatch, revoked key, …) rather than the bare HTTP status — see `ADMIN_AND_SETTINGS_TROUBLESHOOTING`.
