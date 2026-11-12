# LP-MB-Admin-04 — Staff invites and the accept flow

Admin and roles, ticket 4 of 5. **Status: planned, not built.** Needs LP-MB-Admin-03. Next: LP-MB-Admin-05.

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
