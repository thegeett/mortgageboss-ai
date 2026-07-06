"""Normalized-substance finding identity + dedup (LP-93).

Findings are emitted from more than one generator (the deterministic ``xsrc.*`` rules, the AI
cross-source layer, the single-source engine) into LP-75's one shared model. LP-81 made the
emission stable — a re-run supersedes the file's OPEN findings and re-emits, preserving the
RESOLVED ones — and the deterministic rules render a TEMPLATED message identical every run.

The gap this closes: the same discrepancy worded two ways produced **two** findings. The live
case: the employer-name-consistency rule (``xsrc.income.employer_name_consistency``) fired once
per documented-employer string, and two documents carried the SAME employer differing only in
case + dash ("Thermofisher Life Science – PPD Development LP." vs "THERMOFISHER LIFE SCIENCE —
PPD DEVELOPMENT LP."). The rule's own key (``_norm``) folds case + whitespace but NOT the
en-dash/em-dash, so the two were treated as distinct → two Open findings for one employer.

This module gives every finding a **normalized-substance identity** — the canonical type/rule
plus the subject value(s), case-folded and punctuation-canonicalized (dashes → ``-``, curly
quotes → straight, whitespace collapsed). Emission dedups on it: the same normalized identity is
emitted once (the first kept, with its wording), and a fresh finding whose identity matches an
existing (e.g. RESOLVED, preserved) one is skipped — so a re-detected resolved finding keeps its
resolution rather than spawning an Open duplicate.

**Deterministic textual only** — NO fuzzy/semantic matching. Same normalized string → same
finding; anything needing similarity ("Thermofisher" vs "Thermo Fisher Scientific") stays
separate. Conservative by design: under-collapse a genuine edge case rather than wrongly merge
two different findings.
"""
# This module deliberately contains ambiguous-unicode literals (the dash/quote variants it
# canonicalizes), so ruff's confusable-character lints are noise here.
# ruff: noqa: RUF001, RUF002, RUF003

from __future__ import annotations

import re
import unicodedata
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.finding import Finding

# Punctuation that varies without changing meaning → a single canonical form.
_DASHES = "‐‑‒–—―−"  # hyphen variants, en/em dash, bar, minus
_SINGLE_QUOTES = "‘’‚‛′"  # curly/’ variants + prime
_DOUBLE_QUOTES = "“”„‟″"  # curly/” variants + double prime
_TRANSLATION = {
    **{ord(c): "-" for c in _DASHES},
    **{ord(c): "'" for c in _SINGLE_QUOTES},
    **{ord(c): '"' for c in _DOUBLE_QUOTES},
}

# The identity of a finding: (normalized type/rule, normalized subject).
FindingIdentity = tuple[str, str]


def normalize_text(value: str) -> str:
    """Case-fold + punctuation-canonicalize + whitespace-collapse a string (deterministic).

    Unicode-normalizes (NFKC), maps dash/quote variants to a canonical form, case-folds, and
    collapses whitespace. Textual only — no fuzzy/semantic matching.
    """
    text = unicodedata.normalize("NFKC", value)
    text = text.translate(_TRANSLATION)
    text = text.casefold()
    return re.sub(r"\s+", " ", text).strip()


def _subject_repr(finding: Finding) -> str:
    """The finding's subject — WHICH thing it concerns (before normalization).

    Prefers the deterministic rules' ``subject_key`` (e.g. ``employer_name:<x>``,
    ``undisclosed:<holder>``); falls back to the AI layer's substance values
    (``stated_value`` / ``document_value``) when there is no subject_key.
    """
    details = finding.details or {}
    subject_key = details.get("subject_key")
    if subject_key:
        return str(subject_key)
    parts = [details.get("stated_value"), details.get("document_value")]
    return " | ".join(str(p) for p in parts if p)


def finding_identity(finding: Finding) -> FindingIdentity:
    """The normalized-substance identity: (canonical type/rule, normalized subject).

    Two findings with the same identity are the SAME discrepancy (worded differently). The type
    component uses the canonical ``details.type`` when present (so the deterministic + AI views of
    one discrepancy share an identity), else the ``rule_id``. The subject disambiguates distinct
    subjects under one type (e.g. two different employers), so it never over-collapses.
    """
    details = finding.details or {}
    type_key = str(details.get("type") or finding.rule_id)
    return (normalize_text(type_key), normalize_text(_subject_repr(finding)))


async def existing_identities(db: AsyncSession, loan_file_id: UUID) -> set[FindingIdentity]:
    """The normalized identities of the file's live (non-deleted) findings — the dedup seed.

    Includes RESOLVED findings preserved across a re-run, so a re-detected resolved finding is
    skipped (its resolution is kept) rather than re-emitted as an Open duplicate. Tenant scoping
    is via the caller's already-resolved ``loan_file_id``.
    """
    rows = (
        (
            await db.execute(
                select(Finding).where(
                    Finding.loan_file_id == loan_file_id,
                    Finding.deleted_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    return {finding_identity(f) for f in rows}
