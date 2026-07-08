"""Shared account grouping for statement-based evaluators (LP-125R FIX 9).

Continuity (AS-8) and large-deposit sourcing (AS-1) both need to answer "which account is this
statement / deposit in?" — WITHIN one account only, never across accounts. That identity logic + the
PII-free ordinal labelling used to live privately in ``bank_statement_continuity`` and was re-imported /
re-implemented by ``large_deposit``. Promoted here (mirroring how ``normalize_text`` was promoted to
``canonicalize``) so there is ONE grouping implementation and ONE label scheme — "account N" refers to
the same account across every rule's outcome.

ADR-150: the grouping token is an opaque hash — no raw masked account number / holder name flows into a
(loggable) outcome; the outcome uses the ordinal labels only.

KNOWN OPEN ITEM (round-6 review, not this ticket's scope): ``account_type`` is folded into the primary
``bank + masked#`` key, so a single account whose ``account_type`` is inconsistently extracted (populated
on one statement, blank on another) can split. Left as-is here to preserve AS-8 behaviour + tests; the
promotion at least means the fix, when made, lands in ONE place.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable

from app.verification.fact_namespace.canonicalize import normalize_text
from app.verification.fact_namespace.snapshot import BankStatementFacts


def _token_from(
    *, bank: str | None, account_type: str | None, masked: str | None, holder: str | None
) -> str | None:
    """The shared account-identity token from raw account fields (used by both a statement and a
    non-statement document that carries account fields, e.g. a VOD / donor statement).

    Account IDENTITY (a complete key is not a rigid key):
    * ``bank + masked#`` is a sufficient identity when both are present. ``account_type`` is a best-effort
      AI field (often blank) — a FALLBACK DISAMBIGUATOR folded in so two statements sharing bank+masked#
      with DIFFERENT populated types split, but a BLANK type never blocks grouping.
    * When the masked number is absent, fall back to ``bank + account_type + holder``.
    * Missing the bank (or, in the fallback, the holder) → ``None`` (ungroupable).
    """
    bank_n = normalize_text(bank)
    account_type_n = normalize_text(account_type)  # may be "" — a fallback disambiguator only
    masked_n = normalize_text(masked)
    holder_n = normalize_text(holder)
    if bank_n and masked_n:
        components = ("m", bank_n, masked_n, account_type_n)
    elif bank_n and account_type_n and holder_n:
        components = ("h", bank_n, account_type_n, holder_n)
    else:
        return None
    digest = hashlib.sha256("|".join(components).encode("utf-8")).hexdigest()[:12]
    return f"acct:{digest}"


def account_grouping_token(statement: BankStatementFacts) -> str | None:
    """An OPAQUE, PII-free token that UNIQUELY identifies a statement's account, or ``None`` if it can't
    be disambiguated (→ the caller routes it to couldn't-check, never a blind chain across accounts)."""
    return _token_from(
        bank=statement.bank_name,
        account_type=statement.account_type,
        masked=statement.account_number_masked,
        holder=statement.account_holder_name,
    )


def account_token_from_fields(fields: dict[str, str]) -> str | None:
    """The account token for a NON-statement document that carries account fields (LP-125R FIX 5) — e.g.
    a verification-of-deposit / donor bank statement whose ``fields`` name the account it sources. Same
    identity rule as :func:`account_grouping_token`, so a sourcing doc can be matched to the SPECIFIC
    account it explains. ``None`` when the doc carries no usable account identity (unattributable)."""
    return _token_from(
        bank=fields.get("bank_name"),
        account_type=fields.get("account_type"),
        masked=fields.get("account_number_masked"),
        holder=fields.get("account_holder_name"),
    )


def label_accounts(statements: Iterable[BankStatementFacts]) -> dict[str, str]:
    """A stable, PII-free ``token → "account N"`` label map for the given statements (ADR-150).

    Ordinals are assigned by sorted token, so the SAME account gets the SAME label across every rule's
    outcome (AS-8 continuity + AS-1 sourcing) for one file/run. Ungroupable statements (token ``None``)
    contribute no label.
    """
    tokens = sorted({t for s in statements if (t := account_grouping_token(s)) is not None})
    return {token: f"account {i + 1}" for i, token in enumerate(tokens)}
