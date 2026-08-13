"""Shared guards for the account-provisioning scripts.

Used by :mod:`app.scripts.bootstrap_admin` and :mod:`app.scripts.add_user`.
Both run as one-off ECS tasks against a deployed environment, so every guard
here exists to make a mistake fail *before* it touches the database rather than
after.

⚠️ **These scripts take a bcrypt HASH, never a password.** The operator hashes
locally (``scripts/hash-password``) and passes only the hash, because the value
travels through ``aws ecs run-task --overrides``: visible in ``describe-tasks``
for about an hour and recorded in the CloudTrail ``RunTask`` event. A bcrypt
hash at cost 12 with a random salt is not meaningfully sensitive in either
place; a plaintext password would be.

⚠️ **Do not reuse ``settings.is_production`` as a guard here.** It is defined as
``environment == "production"`` and nothing else, so every "not in production"
check in this codebase is OFF in staging — which is precisely the environment
these scripts are for. The environment allowlist below is explicit for that
reason. See ``docs/tickets/C5-bootstrap-admin-result.md``.
"""

from __future__ import annotations

import os

import bcrypt
from email_validator import EmailNotValidError, validate_email

# The two bcrypt variants this application produces or accepts. `$2y$` is
# deliberately absent: it is a PHP-era marker for the same algorithm, and
# accepting it here would mean accepting a hash this codebase never generates.
BCRYPT_PREFIXES = ("$2a$", "$2b$")

# `$2b$` + two-digit cost + `$` + 22 salt chars + 31 digest chars.
BCRYPT_HASH_LENGTH = 60


class ProvisioningError(RuntimeError):
    """A guard refused. The message is safe to print: it never contains a value."""


def require_env(name: str) -> str:
    """Read a required environment variable, or raise.

    No defaults anywhere in these scripts. A default is how a tool meant for one
    deliberate invocation acquires a second, accidental one.
    """
    value = os.environ.get(name, "")
    if not value.strip():
        raise ProvisioningError(f"{name} is required and was not set.")
    return value.strip()


def normalize_email(value: str, *, var_name: str) -> str:
    """Validate an email and return it in the exact form login will look up.

    ⚠️ **The stored value has to match what the login endpoint searches for.**
    ``POST /auth/login`` parses the body through ``LoginRequest.email: EmailStr``,
    so pydantic hands ``authenticate_user`` an address already normalized by
    email-validator — domain lowercased, local part left alone — and the lookup
    is then an exact string match (``User.email == email``).

    Storing whatever the operator typed breaks that agreement: an admin created
    as ``Admin@Example.COM`` is a row that the *same string*, typed at the login
    form, never finds, because the form's copy arrives as ``Admin@example.com``.
    There is no signup route and no password reset, and ``bootstrap_admin``
    refuses to run twice, so that mistake is expensive to undo.

    Normalizing here with the library the API itself uses is what makes the two
    agree by construction. It also rejects a malformed address before the write
    rather than leaving an unusable row behind.
    """
    try:
        return validate_email(value, check_deliverability=False).normalized
    except EmailNotValidError as exc:
        raise ProvisioningError(f"{var_name} is not a valid email address: {exc}") from exc


def validate_bcrypt_hash(value: str, *, var_name: str) -> str:
    """Validate that ``value`` is a well-formed bcrypt hash.

    Checked BEFORE any database write, so a malformed hash cannot leave a
    company row behind with no user attached to it.

    Two checks, because neither alone is sufficient:

    * **Structure** — prefix and total length. ``bcrypt.checkpw`` accepts a
      truncated-but-parseable hash and simply returns ``False``, which would
      create an account that can never be logged into and give no clue why.
    * **The library itself** — ``checkpw`` raises ``ValueError`` on anything it
      cannot parse. Probing with a throwaway password is the only way to ask
      bcrypt "would you accept this?" without a password to verify.

    The value is never included in an error message.
    """
    if not value.startswith(BCRYPT_PREFIXES):
        raise ProvisioningError(
            f"{var_name} is not a bcrypt hash: it must start with "
            f"{' or '.join(BCRYPT_PREFIXES)}. Generate it with scripts/hash-password."
        )
    if len(value) != BCRYPT_HASH_LENGTH:
        raise ProvisioningError(
            f"{var_name} is {len(value)} characters; a bcrypt hash is exactly "
            f"{BCRYPT_HASH_LENGTH}. It was probably truncated in transit — check for "
            f"a shell that split it, or a copy that dropped the tail."
        )
    try:
        bcrypt.checkpw(b"probe-not-a-real-password", value.encode("utf-8"))
    except ValueError as exc:
        raise ProvisioningError(
            f"{var_name} is not a hash bcrypt can parse ({exc}). "
            f"Generate it with scripts/hash-password."
        ) from exc
    return value


def assert_environment_allowed(*, current: str, allowed_raw: str, allowlist_var: str) -> None:
    """Refuse to run outside an explicitly allowed environment.

    ⚠️ Deliberately NOT ``settings.is_production``. That predicate is true only
    for the literal string ``production``, so it would permit these scripts to
    run in development, staging, or any typo'd environment name. This one names
    the environments it permits and refuses everything else, including an
    environment whose name nobody anticipated.
    """
    allowed = {item.strip() for item in allowed_raw.split(",") if item.strip()}
    if not allowed:
        raise ProvisioningError(
            f"{allowlist_var} is empty, so no environment is permitted. "
            f"Set it to a comma-separated list, e.g. 'staging'."
        )
    if current not in allowed:
        raise ProvisioningError(
            f"Refusing to run: ENVIRONMENT is {current!r}, and {allowlist_var} "
            f"permits only {sorted(allowed)}. If this really is intended, set "
            f"{allowlist_var} explicitly for this invocation."
        )
