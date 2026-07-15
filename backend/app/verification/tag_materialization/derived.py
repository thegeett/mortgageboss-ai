"""The generic DERIVED producer (LP-326) — compute a tag deterministically from other facts.

A ``derived`` tag's ``production_data`` is a RECIPE KEY resolved against the recipe registry (one
entry per recipe, reusable across families — never per-family branching). A recipe reads the snapshot
and returns ``(value, reasoning)`` for its subject; the producer wraps it in a ``derived`` tag citing
its subject. A recipe that cannot compute returns ``("unknown", reason)`` — honest, never fabricated.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from decimal import Decimal, InvalidOperation

from pydantic import JsonValue

from app.ai.extraction.parsing import coerce_date
from app.verification.snapshot.model import Snapshot
from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage
from app.verification.tag_materialization.declarations import TagDeclaration
from app.verification.tag_materialization.subjects import LOAN_SUBJECT

# A recipe: snapshot -> (value, reasoning). Deterministic; "unknown" when it cannot compute.
Recipe = Callable[[Snapshot], tuple[JsonValue, str]]

_UNKNOWN = "unknown"


def _income_numbers(snapshot: Snapshot, tag_id: str) -> tuple[Decimal, bool, bool]:
    """Sum a per-document numeric income tag across every non-loan subject → (total, any_present,
    any_unknown). A tag valued ``"unknown"`` or unparseable marks ``any_unknown`` (absent≠unknown — an
    incomplete sum must abstain, never silently understate). Used by the loan-level income recipes."""
    total = Decimal(0)
    any_present = any_unknown = False
    if snapshot.tags.absent:
        return total, any_present, any_unknown
    for subject_id, tags in snapshot.tags.by_subject.items():
        if subject_id == LOAN_SUBJECT:
            continue
        tag = tags.get(tag_id)
        if tag is None:
            continue
        if str(tag.value) == _UNKNOWN:
            any_unknown = True
            continue
        try:
            total += Decimal(str(tag.value))
            any_present = True
        except (InvalidOperation, ValueError):
            any_unknown = True
    return total, any_present, any_unknown


def _income_dates(snapshot: Snapshot, tag_id: str) -> list[date]:
    """Every parseable date value of a per-document income date tag (e.g. income.pay_date)."""
    out: list[date] = []
    if snapshot.tags.absent:
        return out
    for subject_id, tags in snapshot.tags.by_subject.items():
        if subject_id == LOAN_SUBJECT:
            continue
        tag = tags.get(tag_id)
        if tag is None or str(tag.value) == _UNKNOWN:
            continue
        parsed = coerce_date(str(tag.value))
        if parsed is not None:
            out.append(parsed)
    return out


def _income_documented_shortfall(snapshot: Snapshot) -> tuple[JsonValue, str]:
    """income.documented_income_shortfall_pct — (stated - documented) / stated, loan-level aggregate.

    SIGNED (a SHORTFALL), NOT abs: documented ABOVE stated (a raise) is a NEGATIVE shortfall and must
    NOT fire (LP-323-IN-A domain edge). Abstains when stated is absent/zero or documented is
    incomplete (any unknown) — never a fabricated ratio."""
    stated, s_present, _ = _income_numbers(snapshot, "income.stated_monthly")
    documented, d_present, d_unknown = _income_numbers(snapshot, "income.documented_monthly")
    if not s_present or stated == 0:
        return _UNKNOWN, "stated monthly income is absent or zero — cannot compute a shortfall"
    if not d_present or d_unknown:
        return (
            _UNKNOWN,
            "documented monthly income is absent or incomplete — cannot compute a shortfall",
        )
    shortfall = (stated - documented) / stated
    return (
        str(shortfall),
        f"documented monthly income {documented} vs stated {stated} → shortfall {shortfall:.4f} "
        "(negative = documented exceeds stated, e.g. a raise — not a shortfall)",
    )


def _income_ytd_annualized_shortfall(snapshot: Snapshot) -> tuple[JsonValue, str]:
    """income.ytd_annualized_shortfall_pct — (documented - ytd_monthly) / documented, loan-level.

    ytd_monthly = total YTD gross / elapsed months (the most-recent pay date's month number). Fires
    when the paystub YTD does NOT support the documented monthly (a positive shortfall). Abstains when
    YTD, a pay date, or documented income is missing."""
    ytd, ytd_present, ytd_unknown = _income_numbers(snapshot, "income.ytd_gross")
    documented, d_present, _ = _income_numbers(snapshot, "income.documented_monthly")
    pay_dates = _income_dates(snapshot, "income.pay_date")
    if not ytd_present or ytd_unknown:
        return _UNKNOWN, "year-to-date gross is absent or incomplete — cannot annualize"
    if not pay_dates:
        return _UNKNOWN, "no pay date — cannot determine the elapsed period for the YTD figure"
    if not d_present or documented == 0:
        return _UNKNOWN, "documented monthly income is absent or zero — cannot compare"
    elapsed_months = max(d.month for d in pay_dates)  # month number of the most recent pay date
    ytd_monthly = ytd / Decimal(elapsed_months)
    shortfall = (documented - ytd_monthly) / documented
    return (
        str(shortfall),
        f"YTD gross {ytd} over {elapsed_months} month(s) = {ytd_monthly:.2f}/mo vs documented "
        f"{documented}/mo → shortfall {shortfall:.4f}",
    )


def _income_max_employment_gap(snapshot: Snapshot) -> tuple[JsonValue, str]:
    """income.max_employment_gap_days — the largest gap (days) between consecutive employment records.

    Sorts the (end → next start) intervals across all employment records. Abstains when fewer than two
    records with the needed dates exist (a single job cannot have a gap)."""
    starts = sorted(_income_dates(snapshot, "income.employment_start"))
    ends = sorted(_income_dates(snapshot, "income.employment_end"))
    if len(starts) < 2 or not ends:
        return _UNKNOWN, "fewer than two dated employment records — no gap to measure"
    # The largest gap between a prior job's end and the next job's start.
    gaps = [(start - end).days for end in ends for start in starts if start > end]
    if not gaps:
        return _UNKNOWN, "no employment record starts after a prior one ends — cannot measure a gap"
    max_gap = max(gaps)
    return str(max_gap), f"largest gap between consecutive employment records is {max_gap} day(s)"


def _income_days_since_recent_pay(snapshot: Snapshot) -> tuple[JsonValue, str]:
    """income.days_since_most_recent_pay — days from the most recent pay date to the snapshot date.

    Recency is measured against ``snapshot.created_at`` (the run date — the file's 'as of'). Abstains
    when no pay date is present."""
    pay_dates = _income_dates(snapshot, "income.pay_date")
    if not pay_dates:
        return _UNKNOWN, "no pay date on any document — cannot measure recency"
    most_recent = max(pay_dates)
    age = (snapshot.created_at.date() - most_recent).days
    return str(
        age
    ), f"most recent pay date {most_recent.isoformat()} is {age} day(s) before the file date"


# The 1003 fields a complete application must carry (a STARTER set — the authoritative required set
# incl. Declarations + co-borrower is a Priya/guideline value, LP-323-ID-A §5). Keys are MISMO fact
# keys; a blank/absent one counts as missing.
_APP_REQUIRED_FIELDS = (
    "borrower.1.name",
    "borrower.1.ssn",
    "loan.amount",
    "property.address",
)


def _app_required_fields_present(snapshot: Snapshot) -> tuple[JsonValue, str]:
    """id.app_required_fields_present — 'complete' iff every required 1003 field is present."""
    if snapshot.mismo.absent:
        return "unknown", "the 1003 (MISMO) facts are absent — cannot check completeness"
    facts = snapshot.mismo.facts
    missing = [
        key
        for key in _APP_REQUIRED_FIELDS
        if (field := facts.get(key)) is None or not field.is_present
    ]
    if not missing:
        return "complete", "all required 1003 fields are present"
    return "incomplete + list", f"missing required 1003 field(s): {', '.join(missing)}"


_RECIPES: dict[str, Recipe] = {
    "app_required_fields_present": _app_required_fields_present,
    # LP-323-IN-B — the income family's loan-level arithmetic (per-borrower granularity is deferred:
    # the derived producer is loan-only, so these aggregate the file like the DTI calc does — see the
    # LP-323-IN-B doc). Registry entries only; produce_derived_tags is untouched (the wave criterion).
    "income_documented_shortfall": _income_documented_shortfall,
    "income_ytd_annualized_shortfall": _income_ytd_annualized_shortfall,
    "income_max_employment_gap": _income_max_employment_gap,
    "income_days_since_recent_pay": _income_days_since_recent_pay,
}

KNOWN_RECIPES = frozenset(_RECIPES)


def produce_derived_tags(decl: TagDeclaration, snapshot: Snapshot) -> dict[str, dict[str, Tag]]:
    """Produce a derived tag for its subject (``loan`` today), keyed ``{subject_id: {tag_id: Tag}}``."""
    recipe = _RECIPES.get(decl.data)
    if recipe is None:
        raise KeyError(f"unknown derived recipe {decl.data!r} (known: {sorted(_RECIPES)})")
    # Recipes are snapshot -> ONE value, so they attach to the single loan subject; a non-loan subject
    # would be misrouted here (validate_declarations rejects it at load, but never route silently).
    if decl.subject != LOAN_SUBJECT:
        raise KeyError(
            f"derived tag {decl.tag_id!r}: subject {decl.subject!r} is unsupported — "
            f"derived recipes are loan-level (snapshot -> one value) today"
        )
    value, reasoning = recipe(snapshot)
    subject_id = LOAN_SUBJECT
    tag = Tag(
        value=value,
        confidence=None,
        reasoning=reasoning,
        source_facts=(subject_id,),
        produced_by=TagProducedBy.DERIVED,
        tag_role=TagRole.STRUCTURAL_FACT,
        stage=TagStage.A,
    )
    return {subject_id: {decl.tag_id: tag}}


__all__ = ["KNOWN_RECIPES", "Recipe", "produce_derived_tags"]
