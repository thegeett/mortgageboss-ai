# LP-MB-Admin-04 — Staff invites and the accept flow

Admin and roles, ticket 4 of 5. **Status: built, not committed (see Result).** Needs LP-MB-Admin-03. Next: LP-MB-Admin-05.

## What and why

An admin adds a person by entering their email and roles. The person gets an email with a
link, sets their own name and password, and is in. Nobody else ever knows their password, and nobody
has to run a script. Invites expire, can be resent, and can be cancelled.

## The rules

| Rule | What happens |
|---|---|
| **Who** | `users.manage`. Any admin may invite with any roles, ADMIN included. There is no owner role to invite; the owner is set at onboarding. |
| **Token** | 32 random bytes, URL-safe. Only its SHA-256 is stored. Valid 7 days. Single use. |
| **One open invite** | One open invite per email per company. Inviting the same address again resends the existing one, under the same once-a-minute throttle as Resend. |
| **Address already a user here** | Active → 409 "already on your team". Inactive → 409 "reactivate them on the People page". |
| **Address is a user in another company** | Email is the global identity (ADR-042), so this person cannot be added. 409 with a generic "this address can't be invited, contact support". The refusal is written to the audit log. See ADR note. |
| **Resend** | New token, new 7-day expiry, the old link stops working. Not more than once a minute. |
| **Cancel** | `revoked_at` set; the link stops working. |
| **Accept** | Valid token + first name, last name, a password that passes `validate_password_strength`. In one transaction: create the user and their roles, mark the invite accepted, write the audit row. If the address became a user in the meantime, the accept fails with the same generic message as an invalid link. Then the person is signed in (same response and refresh cookie as login). |
| **Invalid link** | Unknown, expired, revoked and already-used all look the same: 404 "this invitation is no longer valid". |
| **No mail transport** | When `settings.mail_transport` is unset (the existing copy-and-send mode), nothing is sent and the create and resend responses carry `accept_url` for the admin to pass on. With a transport, the URL is never returned. |
| **Limits** | At most 50 open invites per company. |

## Scope

- `user_invites` table, `app/services/invites.py`, `app/api/invites.py` (admin) and public routes.
- `app/core/tokens.py`: generate, hash, constant-time compare. Staff invites are its first user; the
  borrower portal's invites are expected to reuse it (that side is not built here).
- The invite email: a system email from `settings.smtp_from_email`, plain text, sent by a Celery task
  through `get_mail_sender()` (the sender is sync and must not run in the request). Subject
  `You've been invited to <company name> on MortgageBoss`. No file address, no thread, no follow-up.
- Invite dialog and a "Pending invitations" list on `/admin/people`; an `(auth)/accept-invite` page.

## Out of scope

- Borrower invites (portal session). Admin-triggered password reset and "forgot password" (they will
  reuse `tokens.py`; separate ticket). Creating an account without an invite (`scripts/add_user` stays).
- Bulk invite, custom message text, invite reminders.

## Open before build

- **SES identity.** `SesMailSender` sends with a configuration set and a verified From. Whether
  `noreply@mortgageboss.ai` is a verified identity in staging has to be checked; if not, it is a small
  INFRA ticket, and until then staging runs in the copy-the-link mode above.
- **Bounces.** A bounced invite should show as "not delivered" on the pending list. First version: not
  handled; the admin resends or copies the link.

## Schema changes

`user_invites`: `id`; `company_id` FK RESTRICT, index; `email` MediumStr, stored lowercase;
`roles` JSON (list of role values); `token_hash` CHAR(64), unique; `expires_at`; `invited_by_user_id`
FK SET NULL; `last_sent_at`; `send_count` int; `accepted_at` null; `accepted_user_id` FK SET NULL null;
`revoked_at` null; `created_at`, `updated_at`.

Partial unique index on `(company_id, email)` where `accepted_at IS NULL AND revoked_at IS NULL`.
Expired invites keep their row; "open" in code also means `expires_at > now()`, and creating an invite
over an expired one reuses the row.

## API

Admin (`users.manage`):
- `POST /invites` `{email, roles}` → 201 (or 200 when it resent an open one).
- `GET /invites` — open and expired, not accepted or revoked.
- `POST /invites/{id}/resend`, `POST /invites/{id}/revoke`.

Public (no auth, no company in the path):
- `POST /invites/lookup` `{token}` → `{company_name, email, roles}` or 404.
- `POST /invites/accept` `{token, first_name, last_name, password}` → `TokenResponse` + refresh cookie.

The token travels in request bodies, never in a path or query string, so it does not reach access logs.
The emailed link is `<frontend>/accept-invite#<token>`: the fragment is not sent to the server.
`upload_links` does it differently (the token is a path segment, `/upload/{token}`, on both the page and
the API). That choice is not followed here: an upload link is a write-only drop box, an invite creates an
account with admin rights, and a copied access log should not be able to do that. Note the divergence in
the ticket write-up; converting upload links is not this ticket's job.

## UI

**Mockups:** `docs/design/admin/png/07-invite-dialog.png`, `08-pending-invitations.png`, `09-accept-invite.png`
(both states of the public page).

- People page: "Invite" button → dialog (email, role checkboxes with the same disabled rules as
  LP-MB-Admin-03). Pending list: email, roles, invited by, expires in, Resend, Cancel; "Copy link" only when the
  response carried one.
- `/accept-invite`: shows the company and the email (read-only), asks for name and password, signs in
  and lands on the dashboard. An invalid link shows one message and a link to sign in.

## Tests

- Every rule in the table, allowed and refused.
- The stored value is a hash; the raw token appears in no table, no log line and no audit row.
- Accept is atomic: a failure after the user insert leaves no user and an unaccepted invite.
- A token works once; after resend the old token is a 404.
- An Admin inviting as ADMIN → 201.
- Address in another company → the generic 409, and an audit row; the response body is identical
  whatever the other company is.
- Lookup and accept for expired, revoked, used and garbage tokens return the same body.
- Email task: MailHog receives one message with the right To and the link; with no transport nothing is
  sent and `accept_url` is present.
- Tenant isolation on resend and revoke.
- Frontend: dialog, pending list, accept page happy path and invalid link.

## ADR note (ADR-444)

**Invites are per company; identity stays global.** A person is one user in one company (ADR-042). An
invite to an address that is already a user elsewhere is refused with a generic message. That does tell
an authenticated admin that the address exists somewhere on the platform; the alternative (accepting
the invite and sending nothing) leaves the admin waiting for a person who can never join. The refusal
is audit-logged and open invites are capped. A person who works for two companies cannot be modelled yet; cross-company access is out of scope.

## Result

**SES: is `noreply@mortgageboss.ai` a verified identity in staging? No, as far as the repository
shows.** Answered from the code only, without calling AWS:
- Staging's Terraform (`infra/modules/outbound_mail`, used by `infra/envs/staging/main.tf`) verifies ONE
  domain identity, `mail.staging.mortgageboss.ai` (plus each customer's own domain through
  `set_up_mail_domain`). Nothing verifies `mortgageboss.ai` or the address `noreply@mortgageboss.ai`,
  and SES does not let a verified subdomain cover its parent.
- `SMTP_FROM_EMAIL` is not set anywhere in `infra/`, so staging sends from the default,
  `noreply@mortgageboss.ai`.
- An identity created by hand in the console would not show in the repository; only AWS can rule
  that out.
- **The consequence is not copy-the-link mode.** Staging sets `MAIL_TRANSPORT=ses`
  (`infra/envs/staging/main.tf`), so `get_mail_sender()` is NOT None there: the API returns no
  `accept_url`, and the email task's send will be refused by SES (an unverified From). Until an INFRA
  ticket fixes it, an admin on staging gets neither an email nor a link; the person cannot be invited
  except by `scripts/add_user`. The smallest fix is one line in the staging task's environment,
  `SMTP_FROM_EMAIL = "noreply@mail.${var.domain_name}"`, an address on the already-verified domain;
  the alternative is verifying `mortgageboss.ai`. Not changed here (deploy configuration).

**Built**
- `app/core/tokens.py`: `generate_token`, `hash_token`, `tokens_match`.
- Migration `6316da7fe522` on `c5874fbee899`: `user_invites` as the schema section, with the partial
  unique index on `(company_id, email)` where not accepted and not revoked. Model `UserInvite` with
  `is_open` and `is_expired`. No readonly view; listed as excluded with the reason.
- `app/services/invites.py`: `create_invite`, `resend_invite`, `revoke_invite`, `list_invites` (each
  `ensure(actor, users.manage)`, scoped to `actor.company_id`), and the public `lookup_invite` and
  `accept_invite`. Refusals in `app/core/errors.py` under `UserRuleError`: `AlreadyOnTeam`,
  `DeactivatedOnTeam`, `ForeignEmail` (audited as `invite_refused_foreign_email`, without the other
  company), `TooManyInvites` (50 open), `InviteThrottled` (429, under a minute); no roles is
  `NoRoles` (422). Re-inviting an open address resends it (200); an expired or revoked row is
  reused. Audit actions `invite_sent`, `invite_resent`, `invite_revoked`, `invite_accepted`.
  `accept_invite` locks the row, re-checks it, validates the password, refuses an address that is
  now a user anywhere, and creates the user, roles (granted by the inviter), acceptance and audit row
  inside a SAVEPOINT, so a failure after the user insert leaves nothing.
- `app/tasks/invites.py`: `send_invite_email(invite_id, token)`, plain text from
  `smtp_from_name <smtp_from_email>`, the subject and body as specified. It sends only if the token
  is still the invite's current one (a resend or cancel since queueing skips it). Logs carry the
  invite id only. Registered in `celery_app._TASK_MODULES`.
- `app/api/invites.py`: the admin router (`users.manage`) and a public router (`/invites/lookup`,
  `/invites/accept`) with no auth; `accept` signs in through a new `auth.issue_session`, which login
  now uses too. Any failing link is one 404 sentence.
- Frontend: `lib/types/invites.ts`, `lib/api/invites.ts`; People page tabs with counts, an Invite
  person button, `components/admin/invite-dialog.tsx` (mockup 07, no owner note),
  `invitations-panel.tsx` (mockup 08: link state, Resend, Cancel, the copy-link card),
  `app/(auth)/accept-invite/page.tsx` (mockup 09, both states).
- Tests: backend 26 API tests and 8 task tests (every rule allowed and refused; the stored value is a
  hash and the raw token is in no table, audit row or captured log line; atomic accept; single use;
  old token dead after resend; foreign-email bodies byte-identical across two companies and the
  refusal committed; one body for expired, revoked, used and garbage tokens; throttle on resend and
  re-POST; the cap; reuse of expired and revoked rows; tenant isolation; 403 for PROCESSOR and LO; the
  task with a fake sender, with none, with a stale token, with a refused send), plus a migration test
  on `migrated_db`. Frontend: dialog (defaults, payload, inline 409, no owner), panel (link states,
  Resend, Cancel, the 429), copy-link card (only with `accept_url`), accept page (fragment read, body,
  fragment cleared, happy path, 422 rule, invalid link three ways).
- Mutations, each caught: the throttle, the cap, the open check on accept, the SAVEPOINT, the
  "became a user" check, the commit of the foreign-email audit row (missed at first: the shared test
  session kept a flushed row; the test now asserts the commit), the task's current-token check,
  `accept_url` only without a transport; on the frontend the fragment read, the fragment clear, the
  copy card's condition and the dialog's inline error.
- Backend: 10061 passed; ruff, mypy strict clean. Frontend: 2605 passed (216 files); tsc and biome
  clean.

**Assumptions and deviations**
- The link's origin is `settings.upload_link_base_url` (already the frontend origin, set in staging),
  through `usable_link_origin()`; no `frontend_url` setting was added.
- The service returns the raw token and the API enqueues the email after its commit, rather than the
  service enqueueing: a worker that ran before the commit would not find the invite.
- The raw token is a Celery task argument, so it sits in the Redis broker until the worker takes it.
- The foreign-email refusal commits its audit row before answering 409; without that the request's
  rollback would drop it.
- No rate limit on the public routes: the upload-link public routes have none to follow.
- The accept page clears the fragment from the address bar once read (`history.replaceState`).
- The password hint is static ("At least 8 characters.", the server's minimum); the server's own
  sentence replaces it on a 422.

**Deferred**
- The staging From address (above): an INFRA ticket.
- Bounce handling ("not delivered" on the pending list), password reset, borrower invites, bulk
  invite, custom message, reminders, rate limiting the public routes.

**Review fixes (after `e2beeadc`)**
5. The invite address is stored the way login looks it up (domain lowercased, local part as typed,
   as `scripts/add_user` stores it), and duplicates are found ignoring case. Before, `Alice.Smith@`
   became `alice.smith@` and the person could not sign in typing their own address. The original
   test asserted the lowercased form, i.e. it pinned the defect; it now asserts the login form.
2. Re-inviting an address with an open invite updates its roles (and audits the change) instead of
   silently keeping the old ones.
3. The link is built before the commit, so a misconfigured origin saves nothing; a queue that
   refuses the email after the commit is a 503 "saved but not sent, use Resend".
4. The email task logs a misconfigured origin as a failed send instead of crashing.
7. Resending an expired invitation counts toward the 50-open cap.
8. Accepting records `last_login_at`: it signs the person in.
9. The accept page shows "no longer valid" only for the server's 404; a network error or 5xx shows
   "We couldn't check your invitation" with Try again, keeping the token in memory.
10. The copy-link card is keyed by its link, so a new link starts at "Copy link", never "Copied";
    tested on the People page, where the bug was.
1, 6. The two races (two admins inviting the same new address at once; two companies' invitations
   for one address accepted at once) are caught in their SAVEPOINTs: the first answers 429 "Try again
   in a minute", the second the usual dead-link 404. Staged in tests by making the lookup miss.
Each fix's mutation is caught.
