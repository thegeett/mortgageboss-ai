# Onboarding & Tenancy Model

How companies and users come to exist in mortgageboss-ai, how tenant isolation
works, and the **staged plan** for building the full onboarding flow. Most of the
flow described here is **future** — this document is the durable record of the
design so it isn't lost while we ship the minimal slice (a dev seed script, LP-26).

Related: **ADR-088** (invite-only tenancy), **ADR-089** (minimal seed / staged
onboarding), **ADR-090** (invitation & reset are capability tokens), and ADR-036
(capability-vs-identifier), ADR-042 (globally-unique email), the LP-24 tenant
context, and `docs/authentication.md`.

## Current status vs future (read this first)

| Capability | Status | Where / when |
| --- | --- | --- |
| Company exists as the tenant (`company_id` scoping) | ✅ Built | Epic 2 models; `scope_to_company` |
| Tenant isolation enforced from the authenticated user's `company_id` | ✅ Built | LP-24 (`get_current_user`, `CurrentCompanyId`) |
| Login / refresh / logout, role-based access (PROCESSOR/ADMIN) | ✅ Built | LP-23, LP-24, LP-25 |
| **Minimal dev accounts** (1 company + admin + processor) | ✅ Built | **LP-26** — `app/scripts/seed_dev.py` |
| Admin user-management (add/remove processors): API + UI | ⏳ Deferred | After Epic 4 |
| Invitation email + "set your own password" link | ⏳ Deferred | After Phase 4 (needs email + capability tokens) |
| Password reset (same machinery) | ⏳ Deferred | After Phase 4 |
| Company onboarding tooling (platform-level) | ⏳ Deferred | Phase 7 |
| Subdomain routing / wildcard DNS / TLS | ⏳ Deferred | Phase 7 |
| Public self-service signup | ❌ Not planned (V1) | — (invite/seed only) |
| Comprehensive seed (many companies, lenders, sample files) | ⏳ Deferred | LP-48 |

**Today:** accounts are created by the seed script (and, later, by admins). Isolation
already works via `company_id` from the token. Everything else above is planned, not
built.

## Actors

- **Platform (mortgageboss-ai)** — onboards **companies** (tenants). Creating a company
  is a platform/superadmin function. In V1 this is the seed script; later, platform
  tooling (Phase 7).
- **Company ADMIN** — manages their company's **processors** (provisions/deactivates
  them) and lender configuration. Belongs to exactly one company.
- **PROCESSOR** — does the loan-processing work (files, documents, verification,
  conditions). Belongs to exactly one company.

## Tenancy model

- Each **Company** is a tenant. The `Company.slug` (globally unique, e.g. `"demo"`) is
  a stable, human-readable identifier — and the **future** subdomain label.
- Every **User** belongs to exactly one company (`User.company_id`). Email is **globally
  unique** (ADR-042), so it identifies the user across the whole system and determines
  their company at login.
- **Isolation is enforced from the authenticated user's `company_id`** (LP-24): the
  access token carries only the user's identity (`sub`); `get_current_user` loads the
  live user, and business endpoints scope every query with
  `scope_to_company(stmt, Model, current_user.company_id)`. The scoping company is
  therefore **non-forgeable** — it comes from the validated token + live record, never
  from client input or a hostname.
- **Subdomains are NOT the security mechanism.** A future `abc.mortgageboss-ai.com` is
  branding/UX (and a login hint), but isolation does not depend on it — it depends on
  `company_id`. This means we get correct multi-tenancy today, before any DNS work.

## Intended onboarding flow (future)

1. **Platform onboards a company** — creates the `Company`, assigns a `slug` (the future
   subdomain `slug.mortgageboss-ai.com`), and creates the first **ADMIN** user for it.
2. **Admin signs in** and adds processors by basic info (first/last name, email) — no
   password is set by the admin.
3. **The new processor receives an invitation email** containing a single-use,
   expiring **capability-token** link.
4. **The processor clicks the link and sets their OWN password** (first login); the
   account is then active. The admin never knows the processor's password.
5. **Thereafter** the admin signs in with the ADMIN role; processors sign in with the
   PROCESSOR role. Role-based access (LP-24 `require_role`) gates admin-only actions.

**Tenant assignment is always controlled:** an invited user inherits the **inviting
admin's** company; a processor can never choose or change their tenant. Company creation
stays a platform function. There is **no public self-registration**.

## Subdomain model (deferred to Phase 7)

- `Company.slug` is the future subdomain identifier; subdomain **routing**, wildcard
  **DNS**, and **TLS** are Phase 7.
- In the interim there are no subdomains: the app is served from a single origin and
  isolation works entirely via `company_id` from the token.
- When subdomains arrive they add branding and a login-hint (which company you're signing
  into); they remain orthogonal to the security boundary.

## Invitation & password-reset = capability tokens (deferred)

The future "set your own password" invitation link and the password-reset link are both
**capability-token** flows (ADR-036):

- The link carries a **cryptographically random, single-use, expiring** token (generated
  with Python's `secrets`, never sequential or derived) — possession of the link *is* the
  authorization to set a password / activate the account.
- Both flows **share one mechanism** (a capability-token store + email delivery), the same
  way the loan-file `inbox_token` is a capability.
- Both are **deferred** until **email sending exists (Phase 4)** and the capability-token
  infrastructure is built. Until then, the seed script sets passwords directly.

## What is built now (LP-26)

A minimal, idempotent seed script — `backend/app/scripts/seed_dev.py` — that creates:

- one **Company** (`Demo Mortgage Processing`, slug `demo`),
- one **ADMIN** (`admin@demo.com`), and
- one **PROCESSOR** (`processor@demo.com`),

with **real bcrypt-hashed** passwords (dev defaults, overridable via env), so the accounts
work through the normal login flow. No email, no tokens, no subdomain. See
`docs/development-workflow.md` for how to run it.

## Staged build plan

| Stage | What | Depends on |
| --- | --- | --- |
| **Now (LP-26)** | Minimal dev seed (company + admin + processor, set passwords) | — |
| **After Epic 4** | Admin user-management: add/remove processors — endpoints (`require_role(ADMIN)`, scoped to the admin's company so tenant assignment stays controlled) + minimal admin UI | Epic 4 patterns |
| **After Phase 4** | Invitation-email + set-password capability-token flow (and password reset, same machinery) | Email sending (Phase 4) + capability-token infra |
| **Phase 7** | Subdomain routing / wildcard DNS / TLS; platform-level company onboarding tooling | Infra/ops |

## Security rationale

- **No public self-registration.** Self-signup means uncontrolled tenant assignment — a
  user could land in (or guess their way into) the wrong company, which is an isolation
  breach. For an internal tool handling **GLBA-covered PII**, onboarding must be
  controlled.
- **Invited users inherit the inviting admin's company** — controlled tenant assignment;
  the user never picks their tenant.
- **Company creation is a platform/superadmin function** (a script in V1) — tenants are
  not created by end users.
- **Isolation does not wait on subdomains** — it is already enforced via `company_id`
  from the token (LP-24), so the security property holds today and subdomains remain a
  pure UX/branding layer.

## References

- `backend/app/scripts/seed_dev.py` — the minimal dev seed (LP-26).
- `docs/development-workflow.md` — how to run the seed.
- `docs/authentication.md` — login/refresh, route protection, tenant context.
- `decisions.md` — ADR-088/089/090 (this ticket); ADR-036 (capability tokens), ADR-042
  (globally-unique email), ADR-082 (tenant context derives from the user).
- `docs/phases/phase-1.md` — phase/ticket plan; LP-48 (comprehensive seed).
