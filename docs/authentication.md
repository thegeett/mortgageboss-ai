# Authentication

How mortgageboss-ai authenticates users: how passwords are stored and how
session tokens are issued and verified. This document covers the **cryptographic
foundation** built in **LP-22** (Epic 3) — pure utilities with no endpoints. The
login/refresh endpoints (LP-23), the current-user dependency (LP-24), and
frontend token handling (LP-25) build on what is described here.

Relevant ADRs: **ADR-073** (bcrypt), **ADR-074** (minimal-claim JWT),
**ADR-075** (stateless, no revocation in V1).

## Password hashing

- **Library:** `bcrypt`, used **directly** (not passlib — recent passlib releases
  have a runtime incompatibility with modern bcrypt). See ADR-073.
- **Algorithm:** bcrypt — slow-by-design and **auto-salted**. A fresh per-password
  salt means the same password hashes to a different value every time; both verify.
- **Where:** `app/core/security.py` — `hash_password`, `verify_password`,
  `validate_password_strength`. Pure functions; no DB, no FastAPI.
- **Storage:** the full bcrypt modular-crypt string is stored in
  `User.hashed_password`. Plaintext exists only transiently in memory and is
  **never stored or logged**. Hashes are never logged either.
- **Verification:** `verify_password` uses `bcrypt.checkpw` (constant-time digest
  comparison) and returns `False` — never raises — on a wrong password *or* a
  malformed/non-bcrypt hash, so callers treat every failure uniformly as "does not
  match".
- **72-byte limit:** bcrypt considers only the first 72 bytes of input. Rather than
  let it silently truncate, `validate_password_strength` **rejects** passwords over
  72 UTF-8 bytes (and under 8 characters). The policy is intentionally minimal for
  V1 — length only; no complexity or breach-list rules.

## JSON Web Tokens (JWT)

- **Library:** `PyJWT`. **Algorithm:** `HS256` (HMAC + shared secret), signed with
  `settings.jwt_secret_key`. HS256 suits a single backend service — no public-key
  distribution needed. See ADR-074.
- **Where:** `app/core/jwt.py` — `create_access_token`, `create_refresh_token`,
  `verify_token`, plus the `TokenType` enum and the typed `TokenPayload`. Pure
  functions; no DB, no FastAPI.

### Access vs refresh tokens

| Token | Purpose | Default lifetime (from settings, LP-6) |
| --- | --- | --- |
| **access** | sent on every authenticated request | `jwt_access_token_expire_minutes` (24h) |
| **refresh** | exchanged for a new access token | `jwt_refresh_token_expire_days` (30d) |

Both lifetimes are overridable per call via `expires_delta` (used in tests to mint
an already-expired token). All timestamps are **timezone-aware UTC**; PyJWT does
the `exp` comparison itself on decode.

### Minimal-claims principle

A JWT is **signed, not encrypted** — anyone holding the token can read its payload.
Tokens therefore carry only the **minimal standard claims**:

| Claim | Meaning |
| --- | --- |
| `sub` | the subject — the user's UUID, as a string |
| `type` | `"access"` or `"refresh"` |
| `iat` | issued-at (UTC) |
| `exp` | expiry (UTC) |

The token carries **NO** role, email, company, `is_active`, or any other PII.
Encoding authorization data into a long-lived, readable token would let a *stale*
token assert outdated permissions. Instead the token proves **identity only**, and
authorization (role, active status, company scope) is looked up **live from the
database** on each request (LP-24). This means deactivating a user or changing a
role takes effect on the **next request** — the system always acts on current
truth.

### Verifying a token

`verify_token(token, expected_type)` checks the signature, the expiry, and that the
token's `type` matches `expected_type`, then returns a typed `TokenPayload`
(`subject: UUID`, `token_type: TokenType`). It distinguishes three failure modes
with **distinct exception classes** so LP-24 can map each to the right HTTP
response:

| Exception | Cause | Expected HTTP mapping (LP-24) |
| --- | --- | --- |
| `TokenExpiredError` | well-formed, correctly signed, but past `exp` | `401 Unauthorized` (often with a hint to refresh) |
| `InvalidTokenError` | bad signature, wrong key, malformed, missing claims, or non-UUID subject | `401 Unauthorized` |
| `WrongTokenTypeError` | valid token of the wrong kind (e.g. refresh where access expected) | `401 Unauthorized` |

All three derive from a common `TokenError` base.

## Stateless JWT in V1 (no revocation) — known tradeoff

V1 uses **stateless** JWT with **no server-side revocation/blocklist** (ADR-075).
There is no store consulted on each request to invalidate a token before its `exp`.

- **Implication:** a stolen, unexpired **access** token stays valid until it
  expires.
- **Mitigations now:** a bounded access-token lifetime limits the exposure window.
  Because authorization is looked up live (above), *deactivating* a user already
  blocks new actions immediately — revocation only matters for cutting off an
  already-authenticated session mid-token-life.
- **Deferred to V2:** a revocation/deny-list and refresh-token rotation are a later
  hardening item; a revocation store adds stateful infrastructure not warranted for
  the pilot.

## What's next

- **LP-23** — login & refresh endpoints that call `verify_password`,
  `create_access_token`, and `create_refresh_token`.
- **LP-24** — the current-user dependency: extract the bearer token, `verify_token`
  it as `ACCESS`, map the typed errors to HTTP responses, and look up the live user
  (role, `is_active`, company) from the database.
- **LP-25** — frontend token storage and refresh handling.
