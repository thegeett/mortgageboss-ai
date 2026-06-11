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

## Endpoints & token transport (LP-23)

The auth endpoints live under `/api/v1/auth` (`app/api/auth.py`, mounted in
`app/main.py`). They are thin orchestration over the utilities above; the substance
is the **hybrid token transport**. Relevant ADRs: **ADR-076** (hybrid transport),
**ADR-077** (anti-enumeration), **ADR-078** (rotation-lite), **ADR-079** (no signup
/ no rate limiting in V1).

### Hybrid transport, end to end

| Token | Where it travels | Why |
| --- | --- | --- |
| **access** | JSON response **body** → client holds it in memory, sends `Authorization: Bearer` | short-lived; never persisted to disk, so it dies with the tab |
| **refresh** | **httpOnly cookie** (`Set-Cookie`), never in any body | long-lived and powerful; httpOnly keeps it unreadable by JavaScript |

The access token goes in the body because the SPA needs to read and attach it. The
refresh token goes in an httpOnly cookie because it is the more powerful, long-lived
credential — keeping it out of JS storage means an XSS bug cannot exfiltrate it.

### The refresh cookie flags (and what each defends)

The cookie is `refresh_token` (constant `REFRESH_TOKEN_COOKIE`), set with:

| Flag | Value | Defends against |
| --- | --- | --- |
| `httponly` | always `True` | **XSS** — JavaScript (`document.cookie`) cannot read it |
| `secure` | `settings.is_production` | **interception** — sent only over HTTPS in prod; `False` in local dev so it works over plain-HTTP `localhost` |
| `samesite` | `"lax"` | **CSRF** — the browser won't attach it to cross-site POSTs |
| `path` | `/api/v1/auth/refresh` (`REFRESH_COOKIE_PATH`) | **scope** — the browser sends it only on refresh requests, not on every API call |
| `max-age` | `jwt_refresh_token_expire_days` (in seconds) | aligns cookie lifetime with the token's expiry |

`secure` is **environment-conditional** on purpose: hardcoding `True` would break
local dev over HTTP (the browser drops the cookie); hardcoding `False` would be
insecure in production. Logout clears the cookie with the **same path and flags** —
otherwise the browser treats it as a different cookie and the original survives.

### Dev cross-origin note

In dev the frontend (`localhost:3000`) and backend (`localhost:8000`) are different
origins. CORS is configured with `allow_credentials=True` (LP-6), and the frontend
must send requests with credentials enabled. The combination that works over local
HTTP is **`secure=False` + `samesite="lax"` + credentialed requests**; if the refresh
cookie fails to appear in dev, this trio is the first thing to check.

### Endpoint contracts

| Endpoint | Input | Success | Failure |
| --- | --- | --- | --- |
| `POST /auth/login` | `LoginRequest` (email, password) | `200` + `TokenResponse` (access token + `UserPublic`); sets refresh cookie | `401` generic for unknown email *or* wrong password (identical); `403` if the account is inactive |
| `POST /auth/refresh` | refresh **cookie** (no body) | `200` + `TokenResponse`; sets a **rotated** refresh cookie | `401` if the cookie is missing, expired, invalid, the wrong type, or the user is gone/inactive |
| `POST /auth/logout` | — | `204`; clears the refresh cookie | — |

The LP-22 token errors all map to `401` on refresh: `TokenExpiredError`,
`InvalidTokenError`, and `WrongTokenTypeError` (e.g. an access token presented to the
refresh endpoint). The body of a login/refresh response **never** contains the
refresh token or `hashed_password`; the access token still carries only
`sub`/`type`/`exp`/`iat` (verified by test).

### Anti-enumeration

`authenticate_user` raises the **same** `AuthenticationError` with the **same**
message for an unknown email and for a wrong password, so a client can never tell
whether an email is registered (ADR-077). To avoid a *timing* signal too, the
unknown-email path still runs one bcrypt comparison against a throwaway hash, so it
isn't measurably faster than the wrong-password path. (An inactive account raises a
distinct `InactiveUserError` → `403`; this is not an enumeration leak because the
caller has already proven they know the password.)

### Rotation-lite

Every successful refresh issues a **new** refresh token (a sliding window), so an
active session's refresh credential keeps moving. V1 does **not** implement
server-side reuse-detection (which would need a store of issued/used tokens) —
consistent with the stateless posture (ADR-078). A stolen, unexpired refresh token is
usable until it expires; the mitigations are `httpOnly` (it's hard to steal in the
first place) and the bounded lifetime.

## V1 gaps (known, documented)

- **No login rate limiting** — brute-force protection is deferred to Phase 7
  hardening; bcrypt's slowness is a partial mitigation, not a substitute (ADR-079).
- **No public registration** — users are admin/seed-provisioned; there is no signup
  endpoint (ADR-079).
- **CSRF posture is SameSite only** — no separate CSRF token in V1; `SameSite=Lax`
  plus the scoped cookie path is the V1 defense.
- **Stateless** — no server-side revocation of access *or* refresh tokens (ADR-075,
  ADR-078); deactivating a user blocks new actions immediately because authorization
  is looked up live.

## Route protection (LP-24)

Protected routes are guarded by **per-route FastAPI dependencies**, not global
middleware (`app/api/dependencies.py`). A route opts into protection by *declaring*
the dependency; public routes (login, refresh, logout, health) simply don't. This
is cleaner than global middleware that has to maintain a list of public-route
exemptions, and it makes each route's protection explicit and greppable. Relevant
ADRs: **ADR-080** (dependencies not middleware), **ADR-081** (live-lookup cutoff),
**ADR-082** (tenant context), **ADR-083** (`require_role`, 403 vs 401).

### `get_current_user` flow

1. Extract the `Authorization: Bearer <token>` credential (`HTTPBearer(auto_error=False)`).
2. `verify_token(token, ACCESS)` — checks signature, expiry, and that it's an
   *access* token (a refresh token here is the wrong type).
3. Look the user up in the database by the token's `sub` (**live lookup**).
4. Confirm the user exists and `is_active` is true.
5. Return the live `User`.

Steps 3–4 are the security core: **role, `company_id`, and `is_active` always come
from the current DB record, never from the token** (the token carries only `sub`).
Any failure — missing/malformed header, expired/invalid/wrong-type token, or a
gone/inactive user — returns a uniform `401` with a `WWW-Authenticate: Bearer`
challenge. `CurrentUser = Annotated[User, Depends(get_current_user)]` is the alias
routes use; `get_current_user_optional` is the non-raising variant for routes that
vary by auth state.

### Deactivation cutoff (the V1 revocation substitute)

Because the user is re-read on every request, setting `is_active=False` (or deleting
the user, or changing their role) takes effect on their **very next request**, even
with a still-valid token. This is how V1 cuts off access without a stateless-JWT
revocation store (ADR-075/ADR-078) — verified by a test that flips `is_active=False`
on a user holding a valid token and asserts the next call gets `401`.

### `require_role` — 401 vs 403

`require_role(*roles)` is a dependency factory that depends on `get_current_user`
(so authentication always precedes authorization) and then checks the live user's
role:

- **401 Unauthorized** — not authenticated (no/invalid token). Authorization is
  never even reached.
- **403 Forbidden** — authenticated, but the role isn't permitted.

V1 has only `PROCESSOR` and `ADMIN`; role checks are coarse (role-level, no
per-resource ACLs).

### Tenant context — activating Epic 2 multi-tenancy

The request's tenant scope is **`current_user.company_id`**, exposed as
`get_current_company_id` / `CurrentCompanyId`. Every business endpoint (Epic 4+)
scopes its queries to it via `scope_to_company(stmt, Model, current_user.company_id)`
(`app/models/helpers.py`). Because that `company_id` comes from the validated token
plus the live user record, a caller **cannot forge another company's scope** — which
is exactly what makes the Epic 2 multi-tenancy enforceable at runtime. A query that
forgets to scope is a tenant leak; the helper gives the rule one greppable name.

### `GET /auth/me`

`GET /api/v1/auth/me` is the first protected endpoint and the end-to-end proof of the
chain: it depends on `CurrentUser` and returns `UserPublic` (never `hashed_password`).

## What's next

- **LP-25** — frontend token storage (access in memory), an axios Bearer interceptor,
  silent refresh against the cookie endpoint, and the auth store.
