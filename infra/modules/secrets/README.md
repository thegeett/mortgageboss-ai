# `modules/secrets`

A customer-managed KMS key (rotation enabled, aliased) and the Secrets Manager
**containers** for the application's credentials. It never creates a value.

## Why the values are not in Terraform

A value written by Terraform is:

- stored in plaintext in the state file,
- rendered in the plan diff every operator reads,
- and replaceable — a provider upgrade or a resource replacement rewrites it.

For `JWT_SECRET_KEY` that would be careless. For `ENCRYPTION_KEY` it is
catastrophic, for the reason below.

## ⚠️ `ENCRYPTION_KEY` — rotating it destroys data permanently

This is the most dangerous value in the entire stack. It has **two** consumers in
the application:

1. **Fernet encryption at rest** of `borrowers.ssn`
   (`backend/app/core/encryption.py:58` → `backend/app/models/borrower.py:88`).
   A **single** key — not a `MultiFernet` rotation chain. There is **no
   re-encryption path anywhere in the repository.**
2. **A derived HMAC key for PII match-hashing**
   (`encryption.py:47` → `backend/app/verification/snapshot/pii.py:134`), which
   produces the `match_hash` values persisted inside `snapshot_records.snapshot_json`
   and materialised as the `id.ssn_hash` fact tag that rule **ID-2** consumes.

**Rotating or regenerating this key makes every stored borrower SSN permanently
undecryptable.** Not "users must log in again" — unrecoverable, unless the old key
still exists somewhere. `decrypt_value` raises `ValueError` and there is no
migration to run.

Rotation also invalidates every existing `match_hash`. That half is less severe
than it looks — each verification run rebuilds the snapshot from source data and
recomputes all hashes under the current key, so live rule evaluation still works —
but historical `snapshot_records` rows keep hashes that no longer correspond to
anything. The `v1:` version prefix (`pii.py:62`) encodes the *construction*, not
the *key*, so a key change is invisible to it.

### How this module protects it

**By not creating it at all.** There is no `random_password` resource, so there is
nothing Terraform can replace. The key is generated once, out of band, and put
into the container by hand:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

This is stronger than `lifecycle { prevent_destroy = true }` on a `random_password`,
which still leaves a resource that a provider upgrade or a state manipulation can
force to replace. The safest resource is the one that does not exist.

**Consequence to accept:** this environment is designed to be destroyed and
rebuilt, and that workflow is safe **only because RDS is destroyed alongside the
secret** — no surviving database means no data to lose. The two must **never** be
destroyed independently. Destroying the secret while the database survives is the
unrecoverable case.

**Ordering note.** Ticket B2 makes the key rotatable (`MultiFernet` plus a
re-encryption path). Until B2 lands, an accidental regeneration is unrecoverable.
After B2 it is recoverable *provided the old key still exists*. B2 lowers the
severity; it does not remove the need for the protection above.

## `recovery_window_days`

`0` for a throwaway environment. A non-zero window leaves a deleted secret in
pending-deletion state **with its name reserved**, so `destroy` followed by
`apply` fails on a name conflict — which is exactly the workflow this environment
is built around.

**Staging and production must use `30`.** The variable has no default, so the
choice is explicit in every `terraform.tfvars`.

## `redis-url`

Created only when `create_redis_url_secret = true`, which must track whether the
cache uses an AUTH token. With a token the URL carries a credential and is a
secret; with transit encryption alone it is topology and belongs in `environment[]`
as CONFIG. `envs/*/main.tf` drives both this module and the data module from one
variable so the two cannot disagree.

## Populating the containers

See `infra/README.md` for the exact `aws secretsmanager put-secret-value`
commands. Nothing in this directory should ever be edited to hold a value.
