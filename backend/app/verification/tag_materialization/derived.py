"""The generic DERIVED producer (LP-326) — compute a tag deterministically from other facts.

A ``derived`` tag's ``production_data`` is a RECIPE KEY resolved against the recipe registry (one
entry per recipe, reusable across families — never per-family branching). A recipe reads the snapshot
and returns ``(value, reasoning)`` for its subject; the producer wraps it in a ``derived`` tag citing
its subject. A recipe that cannot compute returns ``("unknown", reason)`` — honest, never fabricated.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from itertools import pairwise
from typing import NamedTuple

from pydantic import JsonValue

from app.ai.extraction.parsing import coerce_date
from app.verification.ltv import LtvInputs, LtvPurpose, compute_ltv, value_basis
from app.verification.reserves import required_reserve_months
from app.verification.snapshot.fields import Field
from app.verification.snapshot.model import DocumentEntry, Snapshot
from app.verification.snapshot.pii import PiiField
from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage
from app.verification.snapshot.traversal import all_list_rows, all_transactions
from app.verification.tag_materialization.declarations import TagDeclaration
from app.verification.tag_materialization.subjects import (
    LOAN_SUBJECT,
    BorrowerSubject,
    subject_type,
)

# A recipe: (snapshot, subject_id, subject_raw) -> (value, reasoning). Deterministic; "unknown" when it
# cannot compute. LP-332 added the subject arguments so a recipe can be PER-SUBJECT (a borrower recipe
# reads THIS borrower's facts). A loan-level recipe (subject_id == "loan") ignores both — its logic is
# unchanged (the regression canary, _app_required_fields_present).
# A recipe returns ``(value, reasoning)``; a ``None`` value DECLINES the subject (LP-447 — the producer
# materialises no tag), for a recipe scoped narrower than its subject type (e.g. one document_type).
Recipe = Callable[[Snapshot, str, object], tuple[JsonValue | None, str]]

_UNKNOWN = "unknown"
# The classifier's UNCLASSIFIED sentinel — a SLUG, not None. classification.py sets it both when the model
# is unsure and when the call never completed, so any "is this document type X?" read must treat it as
# undetermined rather than as a confident "not X" (mirrors _UNKNOWN_DOC_TYPE in subjects/enumerators).
_UNKNOWN_DOC_TYPE = "unknown"


def _income_numbers(snapshot: Snapshot, tag_id: str) -> tuple[Decimal, bool, bool]:
    """Sum a numeric income tag across every non-loan subject → (total, any_present, any_unknown). A
    tag valued ``"unknown"`` or unparseable marks ``any_unknown`` (absent≠unknown — an incomplete sum
    must abstain, never silently understate). Used by the loan-level income recipes.

    CONTRACT (LP-323-IN-B): the sum assumes ONE income figure PER SUBJECT — a household total is the
    sum over borrowers, not over paystubs. Materialization MUST therefore key these income tags per
    BORROWER (one figure each), NOT per paystub: keying a monthly figure under each of a borrower's N
    paystubs would sum to Nx the income here (this recipe cannot dedup — a tag carries no borrower id)."""
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


def _borrower_stated_monthly(snapshot: Snapshot, index: int) -> tuple[Decimal, bool, bool]:
    """Sum a borrower's MISMO stated income items (borrower.{index}.income.{m}.monthly_amount) →
    (total, any_present, any_unknown). A present-but-unparseable amount marks any_unknown so the caller
    ABSTAINS rather than silently understating stated (an understated stated masks a real shortfall — the
    same absent≠unknown discipline the documented side already follows). Enumerates ALL income keys for
    the borrower rather than assuming contiguous indices — a gap must not silently truncate the sum."""
    total = Decimal(0)
    any_present = any_unknown = False
    if snapshot.mismo.absent:
        return total, any_present, any_unknown
    prefix = f"borrower.{index}.income."
    for name, field in snapshot.mismo.facts.items():
        if not (name.startswith(prefix) and name.endswith(".monthly_amount")):
            continue
        # A monthly income amount is a plain Field (never PII); guard the type so mypy is satisfied and
        # a stray PiiField never contributes a display value.
        if not isinstance(field, Field) or not field.is_present:
            continue
        try:
            total += Decimal(str(field.value))
            any_present = True
        except (InvalidOperation, ValueError):
            any_unknown = (
                True  # a present-but-unparseable amount → incomplete sum → abstain, not drop
            )
    return total, any_present, any_unknown


def _borrower_attributed_documents(snapshot: Snapshot, borrower_id: str) -> list[DocumentEntry]:
    """The documents belongs_to-ATTRIBUTED to this borrower (LP-202/385) — the shared per-borrower-over-
    documents primitive. Attribution is the EVIDENCE-based upload link, NEVER a guess: an unattributed
    document (no ``belongs_to``) is not this borrower's and is excluded, so a borrower's context is
    honestly incomplete rather than padded by a mis-attributed document (LP-332/336). Reused by the
    income AND the ID-expiration per-borrower recipes — one attribution mechanism, not two."""
    if snapshot.documents.absent:
        return []
    return [
        entry
        for entry in snapshot.documents.entries
        if entry.belongs_to is not None
        and any(str(ref.borrower_id) == borrower_id for ref in entry.belongs_to)
    ]


def _borrower_documented_monthly(
    snapshot: Snapshot, borrower_id: str
) -> tuple[Decimal, bool, bool]:
    """The borrower's documented monthly income from its OWN documents (belongs_to) → (value,
    any_present, any_unknown). Only this borrower's documents — one borrower's income never leaks."""
    if snapshot.tags.absent or snapshot.documents.absent:
        return Decimal(0), False, False
    return _distinct_documented_monthly(
        snapshot, _borrower_attributed_documents(snapshot, borrower_id)
    )


def _distinct_documented_monthly(
    snapshot: Snapshot, entries: Sequence[DocumentEntry]
) -> tuple[Decimal, bool, bool]:
    """The DISTINCT documented monthly income across ``entries`` → (value, any_present, any_unknown).

    income.documented_monthly is a PER-PAYSTUB figure (materialized per document), so the standard two
    recent paystubs from ONE job carry the SAME monthly amount — SUMMING them would double-count and turn
    a real shortfall into an apparent raise (the exact PIN #1 false-green, re-created within a borrower).
    We therefore take the DISTINCT documented figure: exactly one distinct value → that is the documented
    monthly; MORE than one (variable pay, or a genuine multi-job borrower whose sources need per-employer
    aggregation) → any_unknown → the caller ABSTAINS (couldnt_check), never a summed over-count. Summing
    a true multi-job borrower's sources is a domain follow-on (needs per-employer grouping); until then
    the honest answer is to abstain, never to mask.

    Takes the document SET rather than a borrower id (LP-511) so the per-borrower and loan-level callers
    share one implementation — the de-duplication rule is the same either way, only the scope differs."""
    values: set[Decimal] = set()
    any_present = any_unknown = False
    if snapshot.tags.absent or snapshot.documents.absent:
        return Decimal(0), any_present, any_unknown
    for entry in entries:
        tag = snapshot.tags.by_subject.get(entry.content_id, {}).get("income.documented_monthly")
        if tag is None:
            continue
        if str(tag.value) == _UNKNOWN:
            any_unknown = True
            continue
        try:
            values.add(Decimal(str(tag.value)))
            any_present = True
        except (InvalidOperation, ValueError):
            any_unknown = True
    if len(values) > 1:
        any_unknown = True  # conflicting documented figures → ambiguous aggregation → abstain
    value = next(iter(values)) if len(values) == 1 else Decimal(0)
    return value, any_present, any_unknown


def _income_documented_shortfall(
    snapshot: Snapshot, subject_id: str, subject_raw: object
) -> tuple[JsonValue, str]:
    """income.documented_income_shortfall_pct — PER BORROWER (LP-332, fixes PIN #1).

    (stated - documented) / stated for THIS borrower: stated = the borrower's MISMO stated income;
    documented = the borrower's OWN documents' documented monthly income (belongs_to) — the DISTINCT
    per-paystub figure, NOT a sum across paystubs (summing would double-count one job's income; see
    _borrower_documented_monthly). SIGNED (a raise is negative → never fires — the LP-323-IN-A edge).
    Abstains PER BORROWER when its stated is absent/zero/incomplete or its documented is absent/
    incomplete/conflicting — one borrower's gap never fails another (per-subject fail-closed), and a
    borrower A whose income is inflated is no longer MASKED by a borrower B (the loan-level aggregate
    false-green — PIN #1)."""
    if not isinstance(subject_raw, BorrowerSubject):
        return _UNKNOWN, "the income shortfall is a per-borrower recipe (needs a borrower subject)"
    stated, s_present, s_unknown = _borrower_stated_monthly(snapshot, subject_raw.index)
    documented, d_present, d_unknown = _borrower_documented_monthly(snapshot, subject_id)
    if not s_present or s_unknown or stated == 0:
        return (
            _UNKNOWN,
            # LP-611 — "this borrower", not the subject id. These reasonings are engineer-facing
            # provenance AND the text a couldnt_check finding shows, so IN-1 shipped "borrower
            # 7558383f-dfbb-47c3-8b3f-aa1ca5494987: documented monthly income is absent" to a
            # processor. The finding already carries the subject, which resolves to the borrower's
            # NAME, so the id was redundant as well as leaked. 28 sites, all in this file.
            "this borrower: stated monthly income is absent, zero, or incomplete",
        )
    if not d_present or d_unknown:
        return (
            _UNKNOWN,
            "this borrower: documented monthly income is absent, incomplete, or has "
            "conflicting figures across documents",
        )
    shortfall = (stated - documented) / stated
    return (
        str(shortfall),
        f"this borrower: documented {documented} vs stated {stated} → shortfall "
        f"{shortfall:.4f} (negative = a raise, not a shortfall)",
    )


#: Average days per calendar month (365.25 / 12) — the divisor turning a day-of-year into an
#: elapsed-month FRACTION, so a pay date of 4 April is 3.09 months elapsed rather than 4.
_DAYS_PER_MONTH = Decimal("30.4375")

#: Below this many elapsed months a YTD figure is not a usable annualization base: dividing a small
#: YTD by a fraction of a month multiplies noise (one early-January stub would "annualize" to a
#: wildly overstated or understated monthly). Abstain instead — never a fabricated shortfall.
_MIN_ELAPSED_MONTHS = Decimal("1")


def _borrower_latest_ytd(
    snapshot: Snapshot, borrower_id: str
) -> tuple[Decimal, date | None, bool, bool]:
    """The borrower's MOST RECENT year-to-date gross, from its OWN documents (belongs_to)."""
    if snapshot.tags.absent or snapshot.documents.absent:
        return Decimal(0), None, False, False
    return _latest_ytd(snapshot, _borrower_attributed_documents(snapshot, borrower_id))


def _latest_ytd(
    snapshot: Snapshot, entries: Sequence[DocumentEntry]
) -> tuple[Decimal, date | None, bool, bool]:
    """The MOST RECENT year-to-date gross across ``entries`` → (ytd, its pay date, any_present,
    any_unknown).

    ⚠️ THE LATEST, NEVER THE SUM. Year-to-date is CUMULATIVE: an April stub's YTD already contains
    March's. Summing two stubs double-counts every month they share — on LF-WCHG the two stubs read
    36,376.62 and 42,404.64 and the recipe used 78,781.26, which is exactly their sum and roughly
    twice the true figure.

    Paired PER DOCUMENT, so the YTD taken is the one belonging to the latest pay date rather than the
    largest number found anywhere. Two documents sharing the latest pay date but disagreeing on YTD
    are ambiguous → any_unknown → the caller abstains.

    Takes the document SET rather than a borrower id (LP-511), so the per-borrower and loan-level
    callers share one implementation.
    """
    latest: tuple[date, Decimal] | None = None
    any_present = any_unknown = False
    if snapshot.tags.absent or snapshot.documents.absent:
        return Decimal(0), None, any_present, any_unknown

    for entry in entries:
        tags = snapshot.tags.by_subject.get(entry.content_id, {})
        ytd_tag, date_tag = tags.get("income.ytd_gross"), tags.get("income.pay_date")
        if ytd_tag is None:
            continue
        if str(ytd_tag.value) == _UNKNOWN:
            any_unknown = True
            continue
        # A YTD with no pay date cannot be placed in time, so it can neither be chosen as the latest
        # nor ruled out as later than the one chosen.
        if date_tag is None or str(date_tag.value) == _UNKNOWN:
            any_unknown = True
            continue
        pay_date = coerce_date(str(date_tag.value))
        if pay_date is None:
            any_unknown = True
            continue
        try:
            value = Decimal(str(ytd_tag.value))
        except (InvalidOperation, ValueError):
            any_unknown = True
            continue
        any_present = True
        if latest is None or pay_date > latest[0]:
            latest = (pay_date, value)
        elif pay_date == latest[0] and value != latest[1]:
            any_unknown = True  # two stubs, same pay date, different YTD → cannot choose

    if latest is None:
        return Decimal(0), None, any_present, any_unknown
    return latest[1], latest[0], any_present, any_unknown


def _income_ytd_annualized_shortfall(
    snapshot: Snapshot, _subject_id: str, _subject_raw: object
) -> tuple[JsonValue, str]:
    """income.ytd_annualized_shortfall_pct — (documented - ytd_monthly) / documented, PER BORROWER.

    LP-509-A3 — THREE STACKED ARITHMETIC DEFECTS, all of which had to go together: fixing any one or
    two of them left the rule firing on LF-WCHG, a file with no income shortfall at all.

      1. YTD was SUMMED across pay stubs (`_income_numbers`). YTD is cumulative, so that
         double-counts. Now the LATEST stub's figure (see :func:`_borrower_latest_ytd`).
      2. `documented_monthly` was SUMMED across documents, and it is materialized PER DOCUMENT — so
         a borrower with four documents read as four times their income (52,615.42 against someone
         earning about 13,150/mo). Now the DISTINCT figure, abstaining when documents disagree
         (:func:`_borrower_documented_monthly`) — the same fix LP-332 applied to IN-1's sibling
         recipe, which this one never received.
      3. `elapsed_months` was `max(pay_dates).month`, so a pay date of 4 April counted as four whole
         months when about 3.1 had passed. Now a real elapsed fraction from the day of year.

    ⚠️ LOAN-SCOPED, not per-borrower — LP-511 reverted that half of A3. Moving it to per_borrower made
    the rule produce NOTHING on the first real file: the per_borrower enumerator resolves borrowers via
    documents' `belongs_to`, and on that file the attribution yields no borrower subjects at all (LP-513,
    which affects IN-1, IN-12..IN-16, ID-5, CR-4 and CR-10 the same way). Per-borrower remains the right
    end state — a loan aggregate can mask one borrower's shortfall behind another's surplus — but a rule
    that silently evaluates nothing is worse than one that aggregates. The three arithmetic fixes above
    are independent of the scope and stand either way.
    """
    entries: Sequence[DocumentEntry] = (
        () if snapshot.documents.absent else tuple(snapshot.documents.entries)
    )
    documented, d_present, d_unknown = _distinct_documented_monthly(snapshot, entries)
    ytd, pay_date, y_present, y_unknown = _latest_ytd(snapshot, entries)

    if not y_present or y_unknown or pay_date is None:
        return _UNKNOWN, (
            "year-to-date gross is absent, incomplete, or cannot be placed against a pay date — "
            "cannot annualize"
        )
    if not d_present or d_unknown or documented == 0:
        return _UNKNOWN, (
            "documented monthly income is absent, zero, incomplete, or has conflicting figures "
            "across documents — cannot compare"
        )

    # The elapsed portion of the year up to the pay date, as a FRACTION of a month. `timetuple().
    # tm_yday` is the day of year (4 April = 94), so this is 3.09 months rather than April's "4".
    elapsed_months = Decimal(pay_date.timetuple().tm_yday) / _DAYS_PER_MONTH
    if elapsed_months < _MIN_ELAPSED_MONTHS:
        return _UNKNOWN, (
            f"the latest pay date ({pay_date.isoformat()}) is only "
            f"{elapsed_months:.2f} month(s) into the year — too short a period to annualize a "
            "year-to-date figure from"
        )

    ytd_monthly = ytd / elapsed_months
    shortfall = (documented - ytd_monthly) / documented
    return (
        str(shortfall),
        f"year-to-date gross {ytd} through {pay_date.isoformat()} "
        f"({elapsed_months:.2f} months elapsed) = {ytd_monthly:.2f}/mo vs documented "
        f"{documented}/mo → shortfall {shortfall:.1%} (negative = ahead of pace, not a shortfall)",
    )


def _income_borrower_indices(snapshot: Snapshot) -> list[int]:
    """The borrower indices that have a MISMO income section (borrower.<n>.income.*). Enumerated from the
    facts, never assumed contiguous — a gap must not silently truncate the loan-level sum."""
    if snapshot.mismo.absent:
        return []
    idx: set[int] = set()
    for name in snapshot.mismo.facts:
        parts = name.split(".")
        if (
            len(parts) >= 3
            and parts[0] == "borrower"
            and parts[2] == "income"
            and parts[1].isdigit()
        ):
            idx.add(int(parts[1]))
    return sorted(idx)


def _qualifying_income_monthly(
    snapshot: Snapshot, _subject_id: str, _subject_raw: object
) -> tuple[JsonValue, str]:
    """dti.qualifying_income_monthly — the loan's total monthly qualifying income = the sum of the
    borrowers' MISMO STATED income lines (``borrower.<n>.income.<m>.monthly_amount``), the SAME income the
    DTI qualifies on (its income lines are ``source='stated'``). A per-subject rule reads THIS via a
    ``loan_tag`` operand (LP-366-A) instead of the DTI calc — a deposit-size question needs income, NOT
    the housing expenses the DTI also weighs (taxes/insurance/MI/HOA), so it must never inherit the DTI's
    insurance gate.

    Reads STATED 1003 income (``source='parsed'``), NOT the AI ``income.qualifying_monthly`` tag — which
    need not materialize (it degraded on the real run) and whose "continuity/averaging" convention is
    underspecified (LP-343 F2). Reading the stated total keeps F2 OFF this path. ABSTAINS to ``unknown``
    (NEVER 0) when no income is stated or a line is unparseable — fail-closed, so a rule reading it
    couldnt_checks on a missing income rather than sizing a threshold from 0.

    ⚠️ The vocabulary (``fact_tags.csv``, xlsx-generated) still describes this as "sum of
    income.qualifying_monthly" — STALE: it reads STATED income. STATED >= QUALIFYING (qualifying haircuts
    declining/variable pay), so a threshold sized on this is LOOSER than 50%-of-qualifying; the AS-1 wiring
    (LP-366-B) must account for it, and the xlsx description needs reconciling."""
    if snapshot.mismo.absent:
        return _UNKNOWN, "no stated financials (MISMO absent) — cannot establish qualifying income"
    total = Decimal(0)
    any_present = any_unknown = False
    for index in _income_borrower_indices(snapshot):
        subtotal, present, unknown = _borrower_stated_monthly(snapshot, index)
        total += subtotal
        any_present = any_present or present
        any_unknown = any_unknown or unknown
    if not any_present or any_unknown:
        return (
            _UNKNOWN,
            "no stated monthly income (or an unparseable income line) — cannot establish qualifying income",
        )
    return (
        str(total),
        f"total stated qualifying income {total}/mo (sum of the borrowers' MISMO stated income lines)",
    )


def _income_max_employment_gap(
    snapshot: Snapshot, _subject_id: str, _subject_raw: object
) -> tuple[JsonValue, str]:
    """income.max_employment_gap_days — the largest gap (days) between consecutive employment records,
    computed PER BORROWER and NEVER across borrowers.

    Employment continuity is a per-borrower concept: one borrower's job-end must not pair with ANOTHER
    borrower's job-start — that manufactures a gap neither borrower has (a false FIRE) or masks a real
    one (a false SATISFY). So records are GROUPED by their document's belongs_to attribution (documents
    with no belongs_to share one group), each group's consecutive (end → next start) gaps are measured,
    and the loan-level tag is the LARGEST gap across the groups. Abstains when no group has two dated
    records (a single job cannot have a gap)."""
    if snapshot.tags.absent or snapshot.documents.absent:
        return _UNKNOWN, "fewer than two dated employment records — no gap to measure"
    # (starts, ends) keyed by the document's borrower attribution — records only pair WITHIN a group,
    # so a gap is never spanned across two different borrowers' timelines.
    groups: dict[object, tuple[list[date], list[date]]] = {}
    for entry in snapshot.documents.entries:
        tags = snapshot.tags.by_subject.get(entry.content_id)
        if not tags:
            continue
        key = (
            frozenset(str(ref.borrower_id) for ref in entry.belongs_to)
            if entry.belongs_to
            else None
        )
        starts, ends = groups.setdefault(key, ([], []))
        for tag_id, bucket in (
            ("income.employment_start", starts),
            ("income.employment_end", ends),
        ):
            tag = tags.get(tag_id)
            if tag is None or str(tag.value) == _UNKNOWN:
                continue
            parsed = coerce_date(str(tag.value))
            if parsed is not None:
                bucket.append(parsed)
    # Each end pairs with the NEXT start in its OWN group (the earliest start after it), NOT every later
    # start — else the max would span intervening jobs (end of job A → start of job C) and overstate a
    # gap that job B actually fills. The largest of those consecutive per-borrower gaps is the answer.
    gaps: list[int] = []
    for starts, ends in groups.values():
        for end in ends:
            later_starts = [s for s in starts if s > end]
            if later_starts:
                gaps.append((min(later_starts) - end).days)
    if not gaps:
        return _UNKNOWN, "fewer than two dated employment records — no gap to measure"
    max_gap = max(gaps)
    return (
        str(max_gap),
        f"largest gap between consecutive employment records (per borrower) is {max_gap} day(s)",
    )


def _income_days_since_recent_pay(
    snapshot: Snapshot, _subject_id: str, _subject_raw: object
) -> tuple[JsonValue, str]:
    """income.days_since_most_recent_pay — days from the most recent pay date to the snapshot date.

    Recency is measured against ``snapshot.created_at`` (the run date — the file's 'as of'). Abstains
    when no pay date is present."""
    pay_dates = _income_dates(snapshot, "income.pay_date")
    if not pay_dates:
        return _UNKNOWN, "no pay date on any document — cannot measure recency"
    most_recent = max(pay_dates)
    age = (snapshot.created_at.date() - most_recent).days
    if age < 0:
        # A pay date AFTER the file date is a data error, not "ultra-fresh". Emitting the negative age
        # would let a staleness rule read it as recent — abstain (couldnt_check) so it is surfaced.
        return (
            _UNKNOWN,
            f"the most recent pay date {most_recent.isoformat()} is AFTER the file date — a "
            "future-dated paystub cannot measure recency",
        )
    return str(
        age
    ), f"most recent pay date {most_recent.isoformat()} is {age} day(s) before the file date"


# The 1003 fields a complete application must carry (a STARTER set — the authoritative required set
# incl. Declarations + co-borrower is a Priya/guideline value, LP-323-ID-A §5). Keys are MISMO fact
# keys; a blank/absent one counts as missing.
#
# LP-509-A2: `borrower.1.name` and `property.address` were required here and are emitted BY NOTHING —
# mismo_section.py emits `first_name`/`middle_name`/`last_name` and `address_line`/`address_line_2`.
# Two of the four keys could never resolve, so ID-6 fired "the application is incomplete" on EVERY loan
# file in the system, naming two fields that were in fact present under their real names. The starter
# set stays a STARTER set: city/state/postal_code are emitted and are deliberately NOT required here,
# because widening what counts as a complete 1003 is the Priya/guideline decision this comment defers,
# not a side effect of repairing the key names. Guarded by the fact-key registry test (LP-509-E1).
_APP_REQUIRED_FIELDS = (
    "borrower.1.first_name",
    "borrower.1.last_name",
    "borrower.1.ssn",
    "loan.amount",
    "property.address_line",
)


def _app_required_fields_present(
    snapshot: Snapshot, _subject_id: str, _subject_raw: object
) -> tuple[JsonValue, str]:
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


# --------------------------------------------------------------------------- #
# LP-323-AS-B — the assets family's loan-level arithmetic. Loan-level recipes that, where a check is
# per-ACCOUNT, GROUP internally via resolve_accounts (LP-336) and fire-if-ANY (never masking a single
# account — PIN #1's cousin avoided). Registry entries only; produce_derived_tags is untouched.
# --------------------------------------------------------------------------- #
# Fannie Mae Selling Guide B3-4.1-01, Minimum Reserve Requirements — page dated 08/07/2024, TIER P,
# fetched 2026-08-13 (LP-497). Pinned to AS-4.yaml's reference_values by test.
#
#   one-unit principal residence ......... none ("There is no minimum reserve requirement")
#   second home .......................... 2 months
#   2-4 unit principal residence ......... 6 months
#   investment property .................. 6 months
#
# THE UNIT COUNT IS LOAD-BEARING, AND ITS ABSENCE ABSTAINS. This replaces an occupancy-ONLY map that
# carried a recorded defect (LP-323-AS-B): it returned 0 for every principal residence, so a 2-4 unit
# primary — which requires 6 months — read as requiring nothing and AS-4 reported `satisfied` on a real
# reserve shortfall. A primary residence whose unit count is unknown is therefore the one cell that
# cannot be defaulted: the answer is either 0 or 6 and nothing in between, so guessing 0 re-creates
# exactly the false-green this replaces. It abstains instead.
#
# The prior deferral said `property.financed_unit_count`'s semantics were "ambiguous for this axis".
# LP-496a measured it: it reaches the snapshot on 10/19 loan files and is the SUBJECT property's
# financed unit count, which is the axis B3-4.1-01 keys on. That is the fact this now reads.
# LP-498 review — THE MATRIX MOVED TO `app/verification/reserves.py` AND IS NO LONGER DUPLICATED. It
# was encoded here only, while the reserves CALCULATOR used an unsourced starter of 2 months, so the
# worksheet and AS-4 could report different requirements for the same file. Both now read the function
# below. The cells, the abstains and their reasons are unchanged — this recipe is a thin adapter that
# maps `None` to the tag's `"unknown"`.


def _mismo_str(snapshot: Snapshot, key: str) -> str | None:
    if snapshot.mismo.absent:
        return None
    field = snapshot.mismo.facts.get(key)
    if not isinstance(field, Field) or not field.is_present:
        return None
    return str(field.value).strip() or None


# LP-371 — MISMO's occupancy value space → occupancy.stated's declared enum (primary | second |
# investment). MISMO uses the long forms (property.occupancy = "primary_residence"); the tag's
# allowed_values are the shorthand. A value NOT in this map ABSTAINS (never a guessed occupancy).
_OCCUPANCY_ENUM = {
    "primary_residence": "primary",
    "second_home": "second",
    "investment": "investment",
}


def _occupancy_stated(
    snapshot: Snapshot, _subject_id: str, _subject_raw: object
) -> tuple[JsonValue, str]:
    """occupancy.stated — the borrower's stated occupancy, MAPPED from the MISMO ``property.occupancy``
    value to the tag's enum (primary | second | investment). A derived mapping, NOT a raw parsed
    passthrough, because MISMO's value ("primary_residence") is not the tag's shorthand enum ("primary")
    — a parsed tag is never re-typed, so it would emit an out-of-enum value (LP-371 D1). ABSTAINS to
    ``unknown`` when occupancy is absent or is a MISMO value not in the map — never a guessed occupancy."""
    occupancy = _mismo_str(snapshot, "property.occupancy")
    if occupancy is None:
        return _UNKNOWN, "property.occupancy is absent — no stated occupancy to report"
    mapped = _OCCUPANCY_ENUM.get(occupancy.casefold())
    if mapped is None:
        return (
            _UNKNOWN,
            f"MISMO occupancy {occupancy!r} is not a mapped value (primary/second/investment)",
        )
    return mapped, f"stated occupancy {mapped} (MISMO property.occupancy={occupancy!r})"


def _housing_insurance_monthly(
    snapshot: Snapshot, _subject_id: str, _subject_raw: object
) -> tuple[JsonValue, str]:
    """housing.insurance_monthly — the loan's monthly homeowners (hazard) insurance = the extracted
    ``annual_premium`` on the file's homeowners-insurance binder ÷ 12 (LP-374). A DERIVED loan recipe: the
    tag's vocabulary subject is ``loan`` and its consumers (DT-1/DT-5/IH-1) read it there. It reads the
    binder DOCUMENT's extracted ``annual_premium`` field from the snapshot — the SAME field the DTI
    calculator reads directly from the extraction (``services/dti.py`` ``_extracted_monthly``). This recipe
    does NOT feed the DTI (which reads the extraction itself); it closes the vocabulary orphan and serves
    the tag's own consumers.

    AGREES-OR-ABSTAINS (never LOOSER than the DTI): the DTI takes the SINGLE NEWEST current binder
    (``_current_extracted_data`` orders by ``created_at`` desc, limit 1). The snapshot exposes no
    ``created_at`` on a document entry, so we cannot pick "the newest" here — instead we ABSTAIN on ANY
    multi-binder ambiguity, which is stricter-than-or-equal-to the DTI in every case (so the tag can agree
    with the DTI's insurance line but never emit a premium the DTI's newest-binder rule would treat as
    unknown). FAIL-CLOSED (``absent ≠ 0`` — the tag's vocabulary note): a 0 premium makes the DTI
    confidently too-low, the exact false-green the DTI's gate exists to prevent. ABSTAINS to ``unknown``
    WITH A REASON when: no homeowners-insurance binder is in the file; the (only) binder states no or a
    non-positive annual premium; multiple binders state CONFLICTING premiums; or multiple binders are
    present and at least one states no premium — cannot tell which is current (the LP-332/LP-336
    fail-closed-on-ambiguity discipline). Reads ONLY ``homeowners_insurance`` (hazard) — NOT
    ``flood_insurance_policy`` or MI, which the classifier types separately and which carry their own DTI
    lines / calculators (LP-374 D3)."""
    if snapshot.documents.absent:
        return _UNKNOWN, "no documents in the file — no homeowners insurance binder to read"
    premiums: set[Decimal] = set()
    binder_count = 0
    unparseable = missing_premium = False
    for entry in snapshot.documents.entries:
        if entry.document_type != "homeowners_insurance":
            continue
        binder_count += 1
        field = entry.fields.get("annual_premium")
        if not isinstance(field, Field) or not field.is_present:
            missing_premium = True
            continue
        try:
            premiums.add(Decimal(str(field.value)))
        except (InvalidOperation, ValueError):
            unparseable = True
    if binder_count == 0:
        return _UNKNOWN, "no homeowners insurance binder in the file — insurance is unknown, not 0"
    if unparseable:
        return _UNKNOWN, "a homeowners insurance binder states an unparseable annual premium"
    if len(premiums) > 1:
        return (
            _UNKNOWN,
            f"{len(premiums)} homeowners insurance binders state conflicting annual premiums "
            f"({', '.join(str(p) for p in sorted(premiums))}) — cannot tell which is current",
        )
    if not premiums:
        return _UNKNOWN, "a homeowners insurance binder is present but states no annual premium"
    # Exactly one distinct premium, but a SECOND binder stated none → the DTI would use its newest binder
    # (which may be the premium-less one) → abstain rather than risk emitting a premium the DTI ignores.
    if missing_premium:
        return (
            _UNKNOWN,
            f"{binder_count} homeowners insurance binders are present but at least one states no annual "
            "premium — cannot tell which is current",
        )
    annual = next(iter(premiums))
    if annual <= 0:
        return (
            _UNKNOWN,
            f"the homeowners insurance binder states a non-positive annual premium ({annual})",
        )
    monthly = annual / Decimal(12)
    return str(monthly), f"monthly homeowners insurance {monthly} (annual premium {annual} ÷ 12)"


# --------------------------------------------------------------------------- #
# LP-597 — the other-financed-properties reserve overlay (B3-4.1-01)
# --------------------------------------------------------------------------- #
#
# Fannie requires reserves BEYOND the occupancy/unit matrix when the borrower owns other financed
# properties: 2% of the aggregate UPB at 1-4 financed properties, 4% at 5-6, 6% at 7-10 (DU only).
# `_reserves_required_months` has always said in its own docstring that it does not model this,
# because the count and the aggregate UPB did not reach the snapshot. LP-596 put the 1003's
# real-estate-owned schedule there, so they do now.
_OTHER_FINANCED_TIERS: tuple[tuple[int, int, Decimal], ...] = (
    (1, 4, Decimal("0.02")),
    (5, 6, Decimal("0.04")),
    (7, 10, Decimal("0.06")),
)

#: Dispositions that keep a property (and therefore its lien) on the borrower's books after closing.
#: `Sell` / `PendingSale` are EXCLUDED by the guide itself — "the aggregate UPB calculation does not
#: include ... properties that are sold or pending sale".
_RETAINED_DISPOSITION = "retain"


def _owned_property_rows(snapshot: Snapshot) -> list[dict[str, str]]:
    """The REO schedule, regrouped out of the snapshot's flat ``owned_property.<n>.<field>`` keys."""
    if snapshot.mismo.absent:
        return []
    rows: dict[str, dict[str, str]] = {}
    for key in snapshot.mismo.facts:
        if not key.startswith("owned_property."):
            continue
        _, index, field = key.split(".", 2)
        value = _mismo_str(snapshot, key)
        if value is not None:
            rows.setdefault(index, {})[field] = value
    return [rows[k] for k in sorted(rows)]


def _schedule_marks_a_subject(snapshot: Snapshot) -> bool:
    """Does this export USE ``OwnedPropertySubjectIndicator`` at all? (LP-600)

    THE MISSING PREMISE IN LP-596/597. Both recorded that only a ``true`` identifies the subject,
    because the first export seen wrote ``false`` on every block — and then both consumers treated
    "not true" as "another property", which is the same mistake wearing different clothes. On an
    export that never sets the flag, the subject property's OWN row becomes an other-financed property
    and its own lien "contradicts" its own payoff marking.

    And the deeper reason it must: ``OwnedPropertyDispositionStatusType`` describes the PROPERTY, not
    the lien. A borrower refinancing their home RETAINS it — of course they do — while the lien is
    retired at closing. So "marked paid off" + "property Retain" is the ordinary refinance, not a
    contradiction, unless the row is positively known to be a DIFFERENT property.

    So the indicator is only trustworthy on a schedule that uses it. Where nothing is marked, the
    schedule cannot distinguish the subject and the honest answer is to abstain, not to guess.
    """
    return any(
        row.get("is_subject", "").strip().lower() == "true"
        for row in _owned_property_rows(snapshot)
    )


def _other_financed(snapshot: Snapshot) -> list[dict[str, str]]:
    """Owned properties that carry a lien the borrower KEEPS after this loan closes.

    Excluded, each for a reason the guide gives: a block marked as the subject (only a true counts —
    see LP-596 on why the false is worthless), and anything being sold or pending sale.

    ⚠️ A ROW WITH NO STATED LIEN BALANCE IS KEPT. It used to be filtered out here alongside a
    free-and-clear property, which had two consequences: the aggregate's "a retained financed property
    states no lien balance" abstention became DEAD CODE (nothing without a balance ever reached it),
    and three retained financed properties whose export omits ``OwnedPropertyLienUPBAmount`` produced
    ``has_other_financed_properties = "no"`` — AS-4 passing while asserting "the application lists no
    other retained financed property", a positive claim about data it never saw.

    A zero balance IS still excluded: a free-and-clear property is owned, not financed. Absent and
    zero are different answers and this is the §8 line — the aggregate abstains on the first and
    counts the second as nothing.
    """
    out = []
    for row in _owned_property_rows(snapshot):
        if row.get("is_subject", "").strip().lower() == "true":
            continue
        if row.get("disposition_status", "").strip().lower() != _RETAINED_DISPOSITION:
            continue
        if _to_decimal_or_none(row.get("lien_upb")) == Decimal(0):
            continue
        out.append(row)
    return out


def _to_decimal_or_none(value: str | None) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(value)
    except (ArithmeticError, ValueError):
        return None


def _reserves_has_other_financed_properties(
    snapshot: Snapshot, _subject_id: str, _subject_raw: object
) -> tuple[JsonValue, str]:
    """reserves.has_other_financed_properties — does the B3-4.1-01 overlay apply at all?

    A GUARD, and deliberately a weak one. An absent REO schedule yields "no", NOT "unknown": most
    exports carry the section, a purchase with no real estate owned legitimately states none, and
    abstaining on absence would turn AS-4 into a couldnt_check on essentially every file without one.
    The tag is NOT gated for the same reason — it can only ever ADD a review, never remove one, so a
    wrong "no" leaves AS-4 exactly where it already was rather than making it worse.
    """
    rows = _other_financed(snapshot)
    if rows and not _schedule_marks_a_subject(snapshot):
        # The schedule lists retained financed property but never says which one this loan is
        # against, so "besides the subject" cannot be established — and on a refinance the subject's
        # own row looks exactly like these. §8: unknown, never a guessed "yes" or a confident "no".
        return (
            _UNKNOWN,
            "the owned-property schedule does not identify which property this loan is against, so "
            "whether any of them is besides the subject cannot be determined",
        )
    if not rows:
        return "no", "the application lists no retained financed property besides the subject"
    return (
        "yes",
        f"the application lists {len(rows)} retained financed "
        f"{'property' if len(rows) == 1 else 'properties'} besides the subject",
    )


def _reserves_other_financed_count(
    snapshot: Snapshot, _subject_id: str, _subject_raw: object
) -> tuple[JsonValue, str]:
    """reserves.other_financed_count — financed properties for the TIER lookup, subject included.

    B2-2-03 counts the subject property among the borrower's financed properties, and the tier
    boundaries in B3-4.1-01 ("one to four", "five to six") are read against that count — so the +1 is
    the guide's arithmetic, not a padding. What the count selects is only the PERCENTAGE; the balance
    it is applied to is a different set, which is why `aggregate_upb` is computed separately.
    """
    count = len(_other_financed(snapshot)) + 1
    return str(count), f"{count - 1} other retained financed properties, plus the subject"


def _reserves_other_financed_aggregate_upb(
    snapshot: Snapshot, _subject_id: str, _subject_raw: object
) -> tuple[JsonValue, str]:
    """reserves.other_financed_aggregate_upb — the balance the percentage is applied to.

    NARROWER THAN THE COUNT, and the difference is the guide's: "the aggregate UPB calculation does
    not include the mortgages and HELOCs that are on the subject property, the borrower's principal
    residence, properties that are sold or pending sale, and accounts that will be paid by closing."
    So the borrower's own home is counted for the tier and excluded from the balance.
    """
    total = Decimal(0)
    excluded = 0
    for row in _other_financed(snapshot):
        if row.get("current_usage_type", "").strip().lower() == "primaryresidence":
            excluded += 1
            continue
        upb = _to_decimal_or_none(row.get("lien_upb"))
        if upb is None:
            return _UNKNOWN, "a retained financed property states no lien balance"
        total += upb
    note = f", excluding {excluded} principal residence" if excluded else ""
    return str(total), f"the aggregate lien balance on retained financed properties{note}"


def _reserves_other_financed_required_amount(
    snapshot: Snapshot, _subject_id: str, _subject_raw: object
) -> tuple[JsonValue, str]:
    """reserves.other_financed_required_amount — the additional reserves B3-4.1-01 requires, in dollars.

    DOLLARS, NOT MONTHS, on purpose. AS-4 compares months of PITIA, and converting this would need the
    housing payment as a divisor — which is gated on exactly the files where taxes and insurance have
    not arrived. Reporting the dollar figure keeps the number available to a processor on a file whose
    ratio cannot yet be computed, which is when they most need it.
    """
    count = len(_other_financed(snapshot)) + 1
    aggregate = _reserves_other_financed_aggregate_upb(snapshot, _subject_id, _subject_raw)[0]
    if aggregate == _UNKNOWN:
        return _UNKNOWN, "the aggregate lien balance could not be totalled"
    rate = next((r for lo, hi, r in _OTHER_FINANCED_TIERS if lo <= count <= hi), None)
    if rate is None:
        # Above ten financed properties the loan is not deliverable at all (B2-2-03), so there is no
        # percentage to apply — a separate eligibility question, not a reserves figure to guess at.
        return _UNKNOWN, f"{count} financed properties is outside the 1-10 tiers B3-4.1-01 covers"
    amount = (Decimal(str(aggregate)) * rate).quantize(Decimal("0.01"))
    return str(amount), f"{rate * 100:.0f}% of {aggregate} at {count} financed properties"


def _reserves_required_months(
    snapshot: Snapshot, _subject_id: str, _subject_raw: object
) -> tuple[JsonValue, str]:
    """reserves.required_months — the reserve requirement in months of PITIA (AS-4's threshold).

    Selected from occupancy AND unit count per B3-4.1-01. An occupancy outside the encoded cells, an
    absent occupancy, and a principal residence whose unit count is unknown all ABSTAIN — a guessed
    requirement is a silent, permanent error, and for the primary-residence cell the guess is between
    0 and 6 months, which is the difference between clearing a file and catching it.

    WHAT THIS DOES NOT MODEL, stated because `satisfied` means less than it appears to: B3-4.1-01 also
    requires reserves of 2% / 4% / 6% of the aggregate UPB when the borrower owns 1-4 / 5-6 / 7-10
    financed properties, and 6 months for a cash-out refinance with DTI over 45%. Neither the financed-
    property count nor the aggregate UPB reaches the snapshot (`property.is_retained_reo` and
    `property.retained_pitia` are vocabulary orphans with no recipe), so neither overlay is evaluated.
    Both can only RAISE the requirement, so this figure is a FLOOR: AS-4's `satisfied` means "meets the
    occupancy/unit requirement", never "meets every reserve requirement". AS-4's spec and its finding
    text say so in words.

    LP-498 review — the matrix itself now lives in `app/verification/reserves.py` so the reserves
    CALCULATOR reads the same cells. This function is the snapshot adapter: read the two MISMO facts,
    call the shared selector, map an abstain to the tag's `"unknown"`.
    """
    months, reason = required_reserve_months(
        _mismo_str(snapshot, "property.occupancy"),
        _mismo_str(snapshot, "property.financed_unit_count"),
    )
    return (_UNKNOWN if months is None else str(months)), reason


# LP-519 — the deposit categories Fannie B3-4.2-02 treats as readily identifiable, mirroring AS-12's
# `exempt_when`. They are excluded from the repeat scan for the arithmetic reason LP-518 recorded: a
# borrower paid the same salary twice a month IS a repeated same-amount deposit, so counting payroll
# would fire this on essentially every W-2 file and say nothing.
#
# `transfer_own` is exempt for the same reason, and it is Stage A's OWN label for "a transfer between
# the borrower's own accounts". A standing savings-to-checking transfer of one round figure is the most
# common benign repeated credit there is — the bar's `fp_fn` text names it as a false positive this rule
# must avoid. AS-12 can leave it unexempted because a model still judges each deposit; this rule asserts
# the pattern deterministically, so it cannot.
_REPEAT_SCAN_EXEMPT = frozenset({"payroll", "interest", "transfer_own"})

#: Two deposits of one amount belong to the same SPLIT only if they land within this many days of each
#: other. A split is CLUSTERED — a sum broken up to stay under a floor arrives over days — while
#: recurring income of a fixed amount (rent, child support, a non-payroll second job) arrives about a
#: month apart. Without a window, six monthly $1,800 credits sum to $10,800 and clear a 50% floor on any
#: income under $21.6k/mo, which accuses a documented income stream of being borrowed funds. 14 days
#: leaves room for a split spread over a week or two while keeping a monthly cadence out; a fortnightly
#: one is caught, which is the accepted cost of not doing per-counterparty grouping (txn.counterparty is
#: produced by nothing today).
_SPLIT_WINDOW_DAYS = 14


def _stmt_repeated_money_in_max_total(
    snapshot: Snapshot, _subject_id: str, _subject_raw: object
) -> tuple[JsonValue, str]:
    """stmt.repeated_money_in_max_total — the largest TOTAL among money-in deposits that share one exact
    amount AND cluster within :data:`_SPLIT_WINDOW_DAYS` (AS-13). Groups of one never count.

    WHY THIS SHAPE. A deposit split to stay under a materiality floor shows up as the same amount, more
    than once, over a short span — which needs no floor and no counterparty. The obvious alternative
    ("sum what AS-12's floor scoped out") is NOT buildable: a recipe receives only the snapshot,
    materialises before any rule runs, and has no access to a spec's reference_values, so it cannot know
    what floor AS-12 applied. Recomputing the floor here would put a threshold in Python and leave two
    copies to drift.

    THREE THINGS KEEP "SAME AMOUNT" FROM MEANING "ARRANGED". Amount equality alone is a weak signal, and
    every one of these is a way it is wrong — all three are answerable from facts already on the subject:

    * the CATEGORY, via :data:`_REPEAT_SCAN_EXEMPT` — a payroll, interest or own-account transfer repeats
      by its nature;
    * the CADENCE, via :data:`_SPLIT_WINDOW_DAYS` — recurring income repeats monthly, a split repeats
      over days;
    * the DOCUMENT, via the (amount, date, description) key below — two uploads of one statement are two
      documents with two content_ids, so without deduplication a single $9,000 deposit present in both
      copies becomes a 2-member group totalling $18,000. AS-1 and AS-12 are immune to that (they would
      emit the same per-deposit finding twice); this rule would turn duplication into a NEW claim about a
      pattern. Deduplication can in principle merge two genuinely distinct deposits that agree on all
      three, which under-reports — the right direction for a fraud-adjacent claim, and the direction the
      bar's `fp_fn` text already chooses.

    ABSTENTION follows :func:`_stmt_nsf_count` — a wrong 0 here reads as "we looked and there is no
    pattern" — except that an unreadable deposit is weighed rather than fatal:

    * tags absent, or ``txn.is_money_in`` on NO subject -> unknown (detection never ran != none found);
    * a transaction whose AMOUNT or DATE is unreadable -> unknown. Both are parsed rather than perceived,
      so this is rare, and without either one the deposit cannot be placed in or out of a cluster.
    * a transaction whose DIRECTION or CATEGORY is undetermined -> unknown ONLY IF its amount could
      change the answer, i.e. it matches an in-scope amount or another undetermined one. An unreadable
      deposit whose amount appears nowhere else cannot form or extend a repeat, so its category is
      irrelevant and abstaining on it would be theatre. Stage A is told to return ``unknown`` liberally
      and a real file carries dozens of transactions, so the unbounded form made the tag less likely to
      be concrete the larger the file got — useless on exactly the files this rule is for.

    A concrete ``0`` means only what it says: every deposit that could matter was readable, and no
    non-exempt amount repeats inside the window.
    """
    if snapshot.tags.absent:
        return _UNKNOWN, "no tags materialized — cannot look for repeated deposits"

    # The scan iterates the TAGS, exactly as its neighbours do, so its coverage does not become
    # conditional on the documents section being readable. Descriptions come from the raw records, which
    # no tag carries: transaction subjects are keyed by content_id, so one index gives them by subject.
    # A subject with no matching record (a tags-only snapshot) keeps its description empty and
    # deduplicates on amount and date alone.
    descriptions = {
        record.content_id: str(record.description.value or "")
        for record in all_transactions(snapshot)
    }
    by_amount: dict[Decimal, list[date]] = {}
    in_scope_keys: set[tuple[Decimal, date, str]] = set()
    undetermined_keys: set[tuple[Decimal, date, str]] = set()
    any_seen = False

    for subject_id, tags in snapshot.tags.by_subject.items():
        direction = tags.get("txn.is_money_in")
        if direction is None:
            continue  # not a transaction subject
        any_seen = True

        # `_decimal_or_none` / `_date_or_none` are the module's Tag→value helpers (defined below):
        # absent, "unknown" and unparseable all collapse to None.
        amount = _decimal_or_none(tags.get("txn.amount"))
        day = _date_or_none(tags.get("txn.date"))
        if amount is None or day is None:
            return (
                _UNKNOWN,
                "a transaction's amount or date is missing or unreadable — a deposit with neither an "
                "amount nor a date cannot be placed in or out of a cluster, so no repeat total can be "
                "asserted",
            )

        # One deposit, identified by its own content rather than by which upload it arrived in.
        key = (amount, day, descriptions.get(subject_id, ""))

        category = tags.get("txn.apparent_category")
        if str(direction.value) == _UNKNOWN or category is None or str(category.value) == _UNKNOWN:
            undetermined_keys.add(key)
            continue
        if str(direction.value) != "in" or str(category.value) in _REPEAT_SCAN_EXEMPT:
            continue
        if key in in_scope_keys:
            continue  # the same deposit, seen again in a duplicate or overlapping statement
        in_scope_keys.add(key)
        by_amount.setdefault(amount, []).append(day)

    if not any_seen:
        return (
            _UNKNOWN,
            "no txn.is_money_in tag on any transaction — deposit detection has not run, so the absence "
            "of a repeated amount cannot be asserted",
        )

    # BOUNDED abstention: only an undetermined deposit whose amount could join or create a group can
    # change the answer. One that matches nothing is irrelevant however it would have been categorized.
    undetermined_amounts = [amount for amount, _day, _desc in undetermined_keys]
    for amount in undetermined_amounts:
        if amount in by_amount or undetermined_amounts.count(amount) > 1:
            return (
                _UNKNOWN,
                f"a transaction of {amount} has an undetermined direction or category and that amount "
                "appears on another deposit — it could form or extend a repeat, so the total cannot be "
                "asserted",
            )

    best: tuple[Decimal, int] | None = None  # (amount, deposits in its largest cluster)
    for amount, days in by_amount.items():
        clustered = _largest_split_cluster(days)
        if clustered < 2:
            continue  # one deposit, or repeats too far apart to be a split
        if best is None or amount * clustered > best[0] * best[1]:
            best = (amount, clustered)

    if best is None:
        return (
            "0",
            f"no non-exempt money-in amount repeats within {_SPLIT_WINDOW_DAYS} days across the file's "
            "statements",
        )
    amount, clustered = best
    return (
        str(amount * clustered),
        f"{clustered} money-in deposits of {amount} each within {_SPLIT_WINDOW_DAYS} days across the "
        "file's statements",
    )


def _largest_split_cluster(days: list[date]) -> int:
    """The most deposits of ONE amount that chain together in within-window steps.

    Sorted ascending, each member has to fall within :data:`_SPLIT_WINDOW_DAYS` of the previous one. A
    sum split over three days gives 3; twelve monthly credits of one rent figure give 1, because no step
    is inside the window — so they never reach the two-member minimum a repeat requires. A chain rather
    than a fixed span so a split that dribbles out over three weeks still reads as one cluster.
    """
    best = run = 1
    for earlier, later in pairwise(sorted(days)):
        run = run + 1 if (later - earlier).days <= _SPLIT_WINDOW_DAYS else 1
        best = max(best, run)
    return best


def _stmt_nsf_count(
    snapshot: Snapshot, _subject_id: str, _subject_raw: object
) -> tuple[JsonValue, str]:
    """stmt.nsf_count — the count of NSF / overdraft transactions across the file (AS-7). Reads the
    per-transaction ``txn.is_nsf_or_overdraft`` tag. ABSTAINS when that tag is present on NO transaction —
    a concrete 0 there would mean "detection ran and found none", but it actually means the detection tag
    was never materialized (absent≠no); returning 0 would false-green AS-7 (every file reads NSF-clean).
    ABSTAINS too when ANY transaction's NSF status is "unknown" (an unreadable/garbled description): the
    count would then be a LOWER BOUND, and reporting it as exact could undercount — false-greening AS-7 the
    same way a fabricated 0 would (the perceiver emits "unknown" only for a genuinely illegible line)."""
    if snapshot.tags.absent:
        return _UNKNOWN, "no tags materialized — cannot count NSF/overdraft items"
    count = 0
    any_seen = False
    for tags in snapshot.tags.by_subject.values():
        tag = tags.get("txn.is_nsf_or_overdraft")
        if tag is None:
            continue
        any_seen = True
        if str(tag.value) == _UNKNOWN:
            return (
                _UNKNOWN,
                "a transaction's NSF/overdraft status is unreadable (unknown) — the count could be an "
                "undercount, so it cannot be asserted (never false-green a possibly-missed NSF)",
            )
        if str(tag.value) == "yes":
            count += 1
    if not any_seen:
        return (
            _UNKNOWN,
            "no txn.is_nsf_or_overdraft tag on any transaction — NSF/overdraft detection has not run "
            "(absent≠no) — cannot assert a clean count",
        )
    return str(count), f"{count} NSF/overdraft transaction(s) across the file's statements"


def _stmt_min_account_months(
    snapshot: Snapshot, _subject_id: str, _subject_raw: object
) -> tuple[JsonValue, str]:
    """stmt.min_account_months — the FEWEST distinct statement months any ONE account has (AS-10 recency).
    Groups statements per account via resolve_accounts (LP-336) and takes the MIN across accounts, so a
    single short account is never MASKED by a well-documented one (fire-if-any). Abstains when no
    resolvable account or no period dates. Deterministic (parsed period fields + the parsed identity)."""
    # LAZY IMPORT — load-bearing, do NOT hoist to module top. rule_engine imports (transitively) reorder
    # module initialization in a way that breaks the snapshot-persistence import order under a full-suite
    # run (a PII-at-rest guard misfires); keeping this function-local avoids the back-edge. Verified: a
    # top-level import turns test_e2e's persist step red.
    from app.verification.rule_engine.enumerators import resolve_accounts

    resolved, _unresolvable = resolve_accounts(snapshot)
    if not resolved:
        return (
            _UNKNOWN,
            "no resolvable account (no bank statement, or an unidentifiable one) — cannot check recency",
        )
    by_subject = {} if snapshot.tags.absent else snapshot.tags.by_subject
    per_account: list[int] = []
    for content_ids in resolved.values():
        months = set()
        for cid in content_ids:
            tag = by_subject.get(cid, {}).get("stmt.period_end")
            parsed = (
                coerce_date(str(tag.value))
                if tag is not None and str(tag.value) != _UNKNOWN
                else None
            )
            if parsed is not None:
                months.add((parsed.year, parsed.month))
        # An account with statements but ZERO parseable period dates is UNCOUNTABLE — counting it as 0
        # months would report a false recency violation (extraction failure ≠ a genuinely short account),
        # and the true MIN is unknowable (this account could be the shortest). ABSTAIN (couldnt_check) —
        # fail-closed: never a fabricated 0, never a silent drop that could mask this account's shortness.
        if not months:
            return (
                _UNKNOWN,
                "an account's statement period dates could not be parsed — cannot count its months "
                "without reporting a false 0",
            )
        per_account.append(len(months))
    fewest = min(per_account)
    return str(fewest), f"the account with the fewest statements has {fewest} distinct month(s)"


def _cash_to_close_shortfall(
    snapshot: Snapshot, _subject_id: str, _subject_raw: object
) -> tuple[JsonValue, str]:
    """calc.cash_to_close — the cash-to-close SHORTFALL (need minus available). BUCKET C: there is NO
    cash-to-close calculator (§3B), and ``closing_costs`` is not a fact today (no Loan-Estimate
    extraction), so this recipe cannot compute the need and ABSTAINS — AS-3 couldnt_checks until the
    closing-costs input exists (reported in the LP-323-AS-B doc, not invented)."""
    return (
        _UNKNOWN,
        "cash-to-close needs the closing-costs figure, which is not extracted today (no Loan-Estimate / "
        "Closing-Disclosure extraction) — cannot compute the requirement (upstream gap, LP-323-AS-B)",
    )


# LP-389-A — the government photo-ID document types whose expiration ID-5 checks. Only drivers_license
# has an expiration extractor today; id.id_expiration otherwise LEAKS (homeowners_insurance also emits an
# expiration_date field), so the promotion is scoped to the ID document — never any document that happens
# to carry an expiration_date. Extend when a passport / state-ID expiration extractor lands.
_GOVERNMENT_ID_DOC_TYPES = frozenset({"drivers_license"})


def _borrower_id_expiration(
    snapshot: Snapshot, subject_id: str, subject_raw: object
) -> tuple[JsonValue, str]:
    """id.borrower_id_expiration — the borrower's government-ID expiration date, PER BORROWER (LP-389-A).

    Reads id.id_expiration (a document fact) from the driver's-licence(s) belongs_to-ATTRIBUTED to THIS
    borrower — the per-borrower promotion that fixes ID-5's document→loan subject mismatch (LP-389). One
    borrower's ID never satisfies another's check (belongs_to isolation). FAIL-CLOSED: NO attributable ID
    → unknown ("no driver's licence found for this borrower"), never a guessed pass; ID documents that
    DISAGREE on the expiration → unknown (ambiguous), never a silently-picked date."""
    if not isinstance(subject_raw, BorrowerSubject):
        return _UNKNOWN, "the ID expiration is a per-borrower recipe (needs a borrower subject)"
    if snapshot.tags.absent:
        return (
            _UNKNOWN,
            "this borrower: no tags materialized to read an ID expiration from",
        )
    # Key by the NORMALIZED date (coerce_date, mirroring the operand's `type: date`), not the raw string, so the
    # same expiration in two renderings ("2027-01-15" vs "01/15/2027") is ONE value, not a spurious conflict.
    # Unparseable values fall back to their raw string as the key — kept distinct, still fail-closed.
    values: dict[object, str] = {}
    for entry in _borrower_attributed_documents(snapshot, subject_id):
        if entry.document_type not in _GOVERNMENT_ID_DOC_TYPES:
            continue  # only a government photo ID carries the expiration ID-5 checks
        tag = snapshot.tags.by_subject.get(entry.content_id, {}).get("id.id_expiration")
        if tag is None or str(tag.value) == _UNKNOWN:
            continue
        raw = str(tag.value)
        values[coerce_date(raw) or raw] = raw
    if not values:
        return _UNKNOWN, "this borrower: no driver's licence found for this borrower"
    if len(values) > 1:
        return _UNKNOWN, (
            f"this borrower: the borrower's ID documents disagree on the expiration date "
            f"({', '.join(sorted(values.values()))}) — ambiguous"
        )
    expiration = next(iter(values.values()))
    return (
        expiration,
        f"this borrower: government-ID expiration {expiration} (from their attributed ID)",
    )


def _loan_closing_date(
    snapshot: Snapshot, _subject_id: str, _subject_raw: object
) -> tuple[JsonValue, str]:
    """contract.loan_closing_date — the loan's single closing date, promoted to loan level from the
    document-subject contract.closing_date (LP-389-A; that tag stays a document fact). Mirrors
    housing.insurance_monthly's document→loan promotion. FAIL-CLOSED: NO closing date in the file →
    unknown; documents that DISAGREE on it → unknown (ambiguous), never a silently-picked date."""
    if snapshot.tags.absent:
        return _UNKNOWN, "no tags materialized to read a closing date from"
    # Normalize before the disagreement check (coerce_date, mirroring the operand's `type: date`), so one closing
    # date rendered two ways ("2027-01-15" vs "01/15/2027") is ONE value, not a spurious conflict; an unparseable
    # value falls back to its raw string as the key — kept distinct, still fail-closed.
    values: dict[object, str] = {}
    for tags in snapshot.tags.by_subject.values():
        tag = tags.get("contract.closing_date")
        if tag is None or str(tag.value) == _UNKNOWN:
            continue
        raw = str(tag.value)
        values[coerce_date(raw) or raw] = raw
    if not values:
        return _UNKNOWN, "no closing date is stated in the file"
    if len(values) > 1:
        return _UNKNOWN, (
            f"the file's documents disagree on the closing date "
            f"({', '.join(sorted(values.values()))}) — ambiguous"
        )
    closing = next(iter(values.values()))
    return closing, f"the loan's closing date {closing} (from the contract document)"


def _loan_effective_date(
    snapshot: Snapshot, _subject_id: str, _subject_raw: object
) -> tuple[JsonValue, str]:
    """ins.loan_effective_date — the loan's single homeowners-insurance effective date, promoted to LOAN
    level from the document-subject ins.effective_date (LP-417; ins.effective_date stays a document fact,
    read from the homeowners_insurance binder's effective_date). Mirrors _loan_closing_date's promotion +
    housing.insurance_monthly's multi-binder abstain: IH-3 (loan-enumerated) compares this to
    contract.loan_closing_date. FAIL-CLOSED: NO binder effective date in the file → unknown; binders that
    DISAGREE on it → unknown (ambiguous — the multi-binder abstain, LP-374), never a silently-picked date.
    DESCRIPTIVE — the date only; whether it is after closing is IH-3's judgment (LP-400).

    ⚠️ Scoped to ``homeowners_insurance`` documents ONLY. UNLIKE contract.closing_date — which only the
    purchase_agreement extractor emits — the ``effective_date`` FIELD is ALSO emitted by the divorce_decree
    extractor, so the parsed ins.effective_date tag leaks onto a decree (a document tag is scoped by field
    name, not document type). Reading it from every subject would let a divorce decree's date drive (or, via a
    false multi-binder disagreement, suppress) the insurance verdict. This is the SAME leak _borrower_id_
    expiration guards (homeowners_insurance also emits an expiration date)."""
    if snapshot.documents.absent:
        return _UNKNOWN, "no documents in the file — no homeowners insurance binder to read"
    # Dedup by the parsed date (coerce_date, mirroring the operand's `type: date`), so one date rendered two
    # ways is ONE value; >1 distinct date → the binders disagree (the multi-binder abstain). Scoped to
    # homeowners_insurance binders — never a divorce_decree that happens to carry an effective_date field.
    values: dict[object, str] = {}
    for entry in snapshot.documents.entries:
        if entry.document_type != "homeowners_insurance":
            continue
        tag = snapshot.tags.by_subject.get(entry.content_id, {}).get("ins.effective_date")
        if tag is None or str(tag.value) == _UNKNOWN:
            continue
        raw = str(tag.value)
        values[coerce_date(raw) or raw] = raw
    if not values:
        return _UNKNOWN, "no homeowners insurance binder states an effective date in the file"
    if len(values) > 1:
        return _UNKNOWN, (
            f"the file's homeowners insurance binders disagree on the effective date "
            f"({', '.join(sorted(values.values()))}) — ambiguous"
        )
    effective = next(iter(values.values()))
    return (
        effective,
        f"the loan's insurance effective date {effective} (from the homeowners binder)",
    )


def _ins_policy_expired(
    snapshot: Snapshot, _subject_id: str, _subject_raw: object
) -> tuple[JsonValue, str]:
    """ins.policy_expired — has the homeowners policy already lapsed as at the file date? (LP-509-D1)

    ⚠️ COMPARED TO THE SNAPSHOT'S OWN BUILD DATE, NEVER THE CLOSING DATE, and that is the whole point.
    LF-WCHG carried an ACORD 27 running 06/25/2024 to 06/25/2025 — thirteen months lapsed at processing,
    and the single most useful thing anyone could have said about that file. Nothing reported it. The
    only rule reading those binder dates was IH-3, which compares the EFFECTIVE date to the CLOSING
    date, so with no closing date on the file it abstained — and a couldnt_check about closing
    swallowed a fact that is true no matter when closing is.

    Expiry needs no closing date to be established, so this depends on none. A file with no closing
    date still gets a straight answer.

    Scoped to ``homeowners_insurance`` documents ONLY, for the reason _loan_effective_date documents:
    ``expiration_date`` is a field name the flood-policy and insurance-quote extractors also emit, and
    a document tag is scoped by field name rather than document type — so reading it from every subject
    would let a flood policy's date decide the hazard verdict, or manufacture a false disagreement that
    suppresses it. FAIL-CLOSED: no binder expiration date, an unparseable one, or binders that DISAGREE
    → unknown (IH-9 abstains), never a guessed "not expired".
    """
    if snapshot.documents.absent:
        return _UNKNOWN, "no documents in the file — no homeowners insurance binder to read"

    values: dict[date, str] = {}
    unparseable = False
    for entry in snapshot.documents.entries:
        if entry.document_type != "homeowners_insurance":
            continue
        tag = snapshot.tags.by_subject.get(entry.content_id, {}).get("ins.expiration_date")
        if tag is None or str(tag.value) == _UNKNOWN:
            continue
        raw = str(tag.value)
        parsed = coerce_date(raw)
        if parsed is None:
            unparseable = True
            continue
        values[parsed] = raw

    if unparseable and not values:
        return _UNKNOWN, (
            "the homeowners insurance binder states an expiration date that could not be read as a "
            "date — abstaining rather than reading an unreadable date as current cover"
        )
    if not values:
        return _UNKNOWN, "no homeowners insurance binder states an expiration date in the file"
    if len(values) > 1:
        return _UNKNOWN, (
            f"the file's homeowners insurance binders disagree on the expiration date "
            f"({', '.join(sorted(values.values()))}) — ambiguous"
        )

    expires_on, raw = next(iter(values.items()))
    as_at = snapshot.created_at.date()
    if expires_on < as_at:
        lapsed_days = (as_at - expires_on).days
        return "yes", (
            f"the homeowners insurance policy expired {raw} — {lapsed_days} day(s) before the file "
            f"date {as_at.isoformat()}, so the property is currently uninsured"
        )
    return "no", (
        f"the homeowners insurance policy runs to {raw}, which is on or after the file date "
        f"{as_at.isoformat()}"
    )


# --------------------------------------------------------------------------- #
# LP-447 — ins.dwelling_settlement_basis: the homeowners binder's DWELLING loss-settlement basis, normalised
# to a controlled vocabulary for IH-1 (insurance adequacy, ADR-340 — Priya's replacement-cost-basis ruling,
# effective 2026-03-18). Per-DOCUMENT (the binder subject), reading ONLY the typed-core field LP-446 added —
# NEVER the forms_and_endorsements list — so a personal-property or ACV-ROOF endorsement (a list row) can
# never be read as the dwelling basis (the Occidental anti-conflation, ADR-351). A free-form string is
# matched against an EXPLICIT allow-list of known phrasings (casefold + collapsed whitespace, NOT a fuzzy
# matcher, D3): a term outside it → "unknown" → IH-1 couldnt_check (fail closed — an unreadable basis is
# never a fabricated pass, LP-447 D3).
# --------------------------------------------------------------------------- #
# Known replacement-cost phrasings (all settle the dwelling at replacement cost — IH-1 satisfied). Guaranteed/
# extended RC are STRONGER forms, still replacement-cost. Matched after casefold + whitespace-collapse.
_REPLACEMENT_COST_BASIS_TERMS = frozenset(
    {
        "replacement cost",
        "replacement cost value",
        "replacement cost coverage",
        "rcv",
        "guaranteed replacement cost",
        "extended replacement cost",
        "full replacement cost",
    }
)
# Known actual-cash-value phrasings (depreciated settlement — IH-1 fired, inadequate).
_ACTUAL_CASH_VALUE_BASIS_TERMS = frozenset({"actual cash value", "acv"})


def _normalize_settlement_basis(raw: str) -> str | None:
    """Map a free-form dwelling loss-settlement string to the controlled vocabulary, or None if unrecognised.

    An EXPLICIT allow-list (D3), not a fuzzy matcher: casefold + collapse internal whitespace, then an EXACT
    membership test. "Replacement Cost" and "replacement cost" both normalise to ``replacement_cost``; an
    unknown phrasing ("guaranteed replacement cost NOT included", a carrier's novel wording) returns None so
    the caller fails closed to "unknown" — never a guessed ``satisfied``."""
    key = " ".join(raw.casefold().split())
    if key in _REPLACEMENT_COST_BASIS_TERMS:
        return "replacement_cost"
    if key in _ACTUAL_CASH_VALUE_BASIS_TERMS:
        return "actual_cash_value"
    return None


def _dwelling_settlement_basis(
    _snapshot: Snapshot, _subject_id: str, subject_raw: object
) -> tuple[JsonValue | None, str]:
    """ins.dwelling_settlement_basis — the homeowners binder's DWELLING loss-settlement basis (LP-447), read
    from the typed-core ``replacement_cost_or_coinsurance_basis`` field (LP-446) and normalised to
    ``replacement_cost`` / ``actual_cash_value`` / ``unknown``. Per-document, but scoped to binders: returns
    ``None`` (DECLINE — the producer materialises no tag) for any NON-homeowners subject, so the tag lands only
    on the documents IH-1 reads instead of an ``unknown`` on every document (LP-447 review). For a binder it
    abstains ("unknown") on an absent or UNRECOGNISED basis (fail closed — D3). DESCRIPTIVE: whether the basis
    is adequate is IH-1's judgment (ADR-340). Reads ONLY the typed field, never the forms_and_endorsements list
    — an ACV-roof / personal-property endorsement cannot drive it (ADR-351)."""
    if (
        not isinstance(subject_raw, DocumentEntry)
        or subject_raw.document_type != "homeowners_insurance"
    ):
        return None, "not a homeowners insurance binder — no basis tag"
    field = subject_raw.fields.get("replacement_cost_or_coinsurance_basis")
    # A plain (non-PII) typed field. A PiiField is a SEPARATE type (not a Field subclass), so
    # ``isinstance(field, Field)`` already excludes a masked value → unreadable → unknown (fail closed): the
    # masked display is never compared, and no PiiField-specific check is needed.
    raw = field.value if isinstance(field, Field) and field.is_present else None
    if raw is None or not str(raw).strip():
        return _UNKNOWN, "the binder does not state a dwelling loss-settlement basis"
    normalized = _normalize_settlement_basis(str(raw))
    if normalized is None:
        return _UNKNOWN, (
            f"the stated loss-settlement basis {str(raw)!r} is not a recognised replacement-cost or "
            f"actual-cash-value term — fail closed (couldnt_check, never a guessed pass)"
        )
    return normalized, (
        f"the binder's dwelling loss-settlement basis is {normalized} (stated: {str(raw)!r})"
    )


# --------------------------------------------------------------------------- #
# LP-487 — IH-2's LENDER-NAME NORMALISATION. Declared data, mirrored in IH-2's spec reference_values;
# test_ih2_vocabulary_matches_the_spec pins the two identical so the spec (where the vocabulary is
# reviewed) and the recipe (which runs) cannot drift — the CR-12 arrangement.
#
# ⚠️ WHY THIS IS DETERMINISTIC AND NOT AI. The catalog planned IH-2 as `ai_fuzzy_match`, which predates
# typed extraction: the PERCEPTION step — reading the clause off the binder — is already spent by the
# extractor, which lands it in `mortgagee_name` on 14 of 15 binders. What remains is comparing two
# strings that differ by ISAOA/ATIMA, a corporate suffix, case and punctuation. rule_kinds.csv is
# amended accordingly (LP-487).
#
# ⚠️ AND WHY A MISMATCH IS NEVER `fired`. The corpus's one file pairing a binder with a Closing
# Disclosure reads "Sistar Mortgage Company" on the CD against "United Wholesale Mortgage" in the
# clause. In broker and correspondent deals the CD names the CREDITOR and the clause names the
# INVESTOR/SERVICER who will hold the loan, and they legitimately differ. A rule that fires there is
# WRONG ON A CORRECT FILE, so IH-2's spec routes a mismatch to needs_review — "the clause names X, the
# file's lender is Y, confirm" — never to a failure.
# --------------------------------------------------------------------------- #

# Everything from a marker onward is ADDRESSING, not the mortgagee's identity: ISAOA/ATIMA ("its
# successors and/or assigns, as their interests may appear") is a boilerplate assignment clause, and
# "c/o" introduces the servicer's mailing agent — LAKEVIEW LOAN SERVICING LLC C/O LOAN CARE LLC is
# Lakeview's clause, not Loan Care's.
_CLAUSE_TRUNCATE_MARKERS: tuple[str, ...] = ("c/o", "isaoa", "atima", "its successors")

# Dropped from BOTH sides, so the comparison stays symmetric and no name is privileged.
_CORPORATE_SUFFIX_TOKENS: frozenset[str] = frozenset(
    {
        "llc",
        "lc",
        "inc",
        "incorporated",
        "corp",
        "corporation",
        "co",
        "company",
        "na",
        "lp",
        "llp",
        "fsb",
        "fa",
        "ltd",
        "plc",
        "bank",
    }
)
_NAME_PUNCT = re.compile(r"[.,/&'\"()\[\]\-]+")

# LP-509-A4 — CREDIT-BUREAU ABBREVIATIONS, expanded on BOTH sides before comparison.
#
# A tradeline's creditor name reaches the application through the bureaus, which truncate it to a
# fixed-width field: the application stated "UNITED WHSLE MORT" for the servicer whose mortgage
# statement says "United Wholesale Mortgage, LLC". Normalisation reduced those to
# ['united','whsle','mort'] and ['united','wholesale','mortgage'] — no equality, no token-prefix, so
# RE-1 and DT-6 both reported that the file's mortgage was not disclosed on the application, when it
# is stated plainly. Telling a processor a mortgage may be undisclosed when it is not is the kind of
# false alarm that costs the whole output its credibility.
#
# A TABLE, NOT A DISTANCE FUNCTION. This module's normalisation is deliberately "declared steps only
# — no stemming, no fuzzy distance, no inference", and that is worth keeping: an edit-distance or
# consonant-skeleton match would also equate names that merely look alike, and the failure it buys
# is a FALSE SATISFIED — a genuinely undisclosed mortgage silently matched to an unrelated stated
# tradeline. Every entry below is a real bureau abbreviation of one specific word, so expansion can
# only ever make two spellings of the SAME word agree. Extend it when the corpus shows a new one.
# Kept deliberately SHORT. Anything genuinely ambiguous is left out rather than guessed: "cap"
# (capital/capitol), "amer" (america/american), "res" (residential/reserve), "nat" and "fin" are all
# short enough to be a name fragment in their own right, and a wrong expansion here does not cause a
# missed match — it causes a WRONG one, which lands as `satisfied` and is never re-read. Every entry
# is an abbreviation seen on real tradeline names.
#
# `services`/`servicing` is a CANONICALISATION rather than an expansion: both spellings appear in
# servicer legal names ("PennyMac Loan Services" vs a statement's "Loan Servicing"), so both sides
# are folded onto one token. Same purpose — make two spellings of one entity agree.
_LENDER_ABBREVIATIONS: dict[str, str] = {
    "whsle": "wholesale",
    "whlsl": "wholesale",
    "whls": "wholesale",
    "mort": "mortgage",
    "mtg": "mortgage",
    "mtge": "mortgage",
    "mtgs": "mortgage",
    "fincl": "financial",
    "fncl": "financial",
    "svc": "servicing",
    "svcs": "servicing",
    "svcng": "servicing",
    "services": "servicing",
    "natl": "national",
    "fed": "federal",
    "assn": "association",
    "ln": "loan",
    "lns": "loan",
    "hm": "home",
    "bk": "bank",
    "bnk": "bank",
    "cu": "credit union",
}


def _expand_lender_abbreviations(tokens: list[str]) -> list[str]:
    """Bureau abbreviations to their full words (LP-509-A4).

    An entry may expand to two tokens (``cu`` -> ``credit union``), so the result is re-flattened;
    that keeps the token-prefix rule in :func:`_lender_names_agree` comparing like with like.
    """
    out: list[str] = []
    for token in tokens:
        out.extend(_LENDER_ABBREVIATIONS.get(token, token).split())
    return out


def _normalise_lender_name(raw: str) -> list[str]:
    """A lender/mortgagee name reduced to comparable tokens. Declared steps only — no stemming, no
    fuzzy distance, no inference.

    casefold → collapse whitespace → truncate at the first assignment/care-of marker → strip
    punctuation → drop corporate-suffix tokens. Returns ``[]`` when nothing identifying survives, which
    the caller treats as an abstain rather than as an empty match.
    """
    text = _WS.sub(" ", raw).strip().casefold()
    for marker in _CLAUSE_TRUNCATE_MARKERS:
        index = text.find(marker)
        if index != -1:
            text = text[:index]
    text = _NAME_PUNCT.sub(" ", text)
    # Expand bureau abbreviations BEFORE dropping corporate suffixes, so an abbreviation that
    # expands to a suffix token ("bk" -> "bank") is dropped by the same rule as the spelled-out
    # form — otherwise the two spellings would normalise to different token counts.
    expanded = _expand_lender_abbreviations([tok for tok in text.split() if tok])
    return [tok for tok in expanded if tok not in _CORPORATE_SUFFIX_TOKENS]


def _lender_names_agree(clause: list[str], lender: list[str]) -> bool:
    """Do two normalised names refer to the same entity?

    Equal token lists, or one a TOKEN-PREFIX of the other with at least two tokens in common.

    ⚠️ TOKEN-PREFIX, NOT SUBSTRING. Substring matching on the raw string would let a two-letter suffix
    fragment match inside an unrelated word; comparing whole tokens in order cannot. The prefix rule is
    what absorbs the real corpus variance — "amerihome mortgage company llc a delaware limited liability
    company" against a CD's "amerihome mortgage" agrees on both tokens it states.

    ⚠️ THE KNOWN FALSE-SATISFIED DIRECTION, stated rather than discovered later: a CD naming "First
    National" against a clause naming "First National Bank of Chicago" agrees under this rule. Two
    tokens of agreement is a real tolerance, and `satisfied` is the one verdict no human re-reads. It is
    accepted because the alternative — demanding equality — would route the ordinary ISAOA/suffix
    variance to needs_review on nearly every binder and train a processor to click past IH-2.
    """
    if not clause or not lender:
        return False
    if clause == lender:
        return True
    shorter, longer = (clause, lender) if len(clause) < len(lender) else (lender, clause)
    return len(shorter) >= _IH2_MIN_PREFIX_TOKENS and longer[: len(shorter)] == shorter


def _parsed_strings(snapshot: Snapshot, tag_id: str) -> list[str]:
    """Every non-empty, non-``unknown`` value of ``tag_id`` across the file's subjects, in subject order."""
    if snapshot.tags.absent:
        return []
    out: list[str] = []
    for tags in snapshot.tags.by_subject.values():
        tag = tags.get(tag_id)
        if tag is None or str(tag.value) == _UNKNOWN:
            continue
        text = str(tag.value).strip()
        if text:
            out.append(text)
    return out


def _file_lender_name(snapshot: Snapshot) -> tuple[str | None, str]:
    """This loan's lender, and where it came from.

    ⚠️ THE CD OUTRANKS THE LE, deliberately. The Closing Disclosure is the final, binding statement of
    the creditor; a Loan Estimate is preliminary and can be superseded by a re-issue. The LE is a
    FALLBACK so that a file early in processing — which has no CD yet — is still checkable rather than a
    permanent couldnt_check.

    ⚠️ Disagreement WITHIN a source abstains. Two Closing Disclosures naming different creditors is a
    contradiction the file has to resolve; picking one would be a guess.
    """
    for tag_id, label in (
        ("loan.lender_name_cd", "the Closing Disclosure"),
        ("loan.lender_name_le", "the Loan Estimate"),
    ):
        values = _parsed_strings(snapshot, tag_id)
        if not values:
            continue
        # ⚠️ Dedup on the NORMALISED TOKENS, not the raw string (reported finding). The token normaliser
        # lives in this same module and strips punctuation and entity suffixes; keying on the raw text
        # meant "United Wholesale Mortgage, LLC" on the initial CD and "UNITED WHOLESALE MORTGAGE LLC" on
        # the final CD read as TWO creditors and IH-2 abstained. Nearly every real file carries both, so a
        # comma silently killed the rule. The abstain is for GENUINELY different creditors; this keeps it.
        distinct = {tuple(_normalise_lender_name(v)): v for v in values}
        if len(distinct) > 1:
            return None, (
                f"{label} names more than one creditor ({', '.join(sorted(distinct.values()))}) — "
                "ambiguous, so the mortgagee clause is not checked against a guess"
            )
        return next(iter(distinct.values())), label
    return None, "no Closing Disclosure or Loan Estimate in the file states a lender"


def _mortgagee_clause_correct(
    snapshot: Snapshot, _subject_id: str, subject_raw: object
) -> tuple[JsonValue | None, str]:
    """ins.mortgagee_clause_correct — does THIS binder's mortgagee clause name this loan's lender? (IH-2)

    Per BINDER, like IH-1: returns ``None`` (DECLINE — no tag materialises) for any non-homeowners
    subject, so the tag lands only on the documents IH-2 reads. ``yes`` / ``no`` / ``unknown``; a ``no``
    is routed to needs_review by the spec, never to a failure — see the module note above.
    """
    if (
        not isinstance(subject_raw, DocumentEntry)
        or subject_raw.document_type != "homeowners_insurance"
    ):
        return None, "not a homeowners insurance binder — no mortgagee-clause tag"
    field = subject_raw.fields.get("mortgagee_name")
    raw = field.value if isinstance(field, Field) and field.is_present else None
    if raw is None or not str(raw).strip():
        return _UNKNOWN, "this binder states no mortgagee name"
    lender, source = _file_lender_name(snapshot)
    if lender is None:
        return _UNKNOWN, source
    clause_tokens = _normalise_lender_name(str(raw))
    lender_tokens = _normalise_lender_name(lender)
    if not clause_tokens or not lender_tokens:
        return _UNKNOWN, (
            f"nothing identifying survives normalisation of {str(raw)!r} or {lender!r} — abstaining "
            "rather than reading an empty name as a match"
        )
    if _lender_names_agree(clause_tokens, lender_tokens):
        return "yes", (
            f"the mortgagee clause names {str(raw)!r}, which matches the lender on {source} ({lender!r})"
        )
    return "no", (
        f"the mortgagee clause names {str(raw)!r} but {source} names {lender!r} — these may both be "
        "correct (a correspondent's creditor and the investor who will hold the loan differ), so this "
        "is raised for confirmation rather than treated as an error"
    )


# --------------------------------------------------------------------------- #
# LP-487 — IH-7's CONDO MASTER POLICY adequacy.
#
# THRESHOLD PROVENANCE (ADR-361 — cited, never recalled):
#   general liability >= $1,000,000 per occurrence
#     Fannie Mae Selling Guide B7-4-01, "General Liability Insurance Requirements for Project
#     Developments", page dated 08/05/2026: "The amount of coverage must be at least $1 million for
#     bodily injury and property damage for any single occurrence."
#     ⚠️ B7-4-01, NOT B7-3-03 — B7-3-03 is MASTER PROPERTY insurance and states no liability limit.
#   replacement-cost basis
#     Fannie Mae Selling Guide B7-3-03, "Master Property Insurance Requirements for Project
#     Developments", page dated 08/05/2026: "The master property insurance coverage amount must equal
#     at least 100% of the estimated replacement cost value of the project improvements, including
#     common elements and residential structures." The same section accepts GUARANTEED and EXTENDED
#     replacement cost as ways to substantiate it — hence both are in the recognised vocabulary.
#
# ⚠️ THE BASIS FIELD IS PROSE, NOT A CODE — and this widens ADR-376 deliberately, so the widening is
# stated rather than slipped in. The four master policies in the corpus read:
#     "Guaranteed Replacement Cost"
#     "Replacement Cost"
#     "REPLACEMENT COST AT AGREED VALUE WITH NO CO-INSURANCE"
#     "Replacement Cost (RCV) at Agreed Value with no coinsurance; 100% replacement cost for ..."
# An EXACT closed-set match — CR-12's rule — would abstain on three of the four and leave IH-7
# permanently couldnt_check. So the recognised phrases are matched as a LEADING PHRASE: every value
# above STATES its basis first and then elaborates (agreed value, no coinsurance, the association's
# portion), and an elaboration is not a contradiction.
#
# The abstain that ADR-376 actually protects is kept intact, in two places: an unrecognised leading
# phrase is `unknown`, never "inadequate"; and an actual-cash-value phrase ANYWHERE in the string
# abstains even when the value opens with a replacement-cost phrase, because a mixed basis ("ACV roof,
# replacement cost dwelling") is a human question, not a pass.
# --------------------------------------------------------------------------- #

# ⚠️ NAMED, not inlined, so the spec↔code drift test can pin the CODE (reported finding). It was
# hardcoded as `>= 2` while the spec declared min_prefix_tokens_for_match: "2" and the drift test compared
# the spec's literal against the literal "2" — so changing the code to 3 left the test green and the spec
# silently wrong about what runs. The other two IH-2 vocabulary values were already pinned spec↔constant.
_IH2_MIN_PREFIX_TOKENS = 2

_CONDO_MIN_LIABILITY_PER_OCCURRENCE = Decimal("1000000")
# The document type whose PRESENCE answers "is there a master policy on this file?" — mirrors the
# document_type scope of the condo.* parsed declarations in tag_production.yaml, so presence and the
# fields read from it can never disagree about which document they mean.
_CONDO_MASTER_POLICY_DOC_TYPES = frozenset({"master_insurance_policy_for_condominium"})

# CO-1's document types, NAMED for the same reason (reported finding — the new recipe inlined the literal
# and reverted the convention the comment above establishes).
#   _CONDO_QUESTIONNAIRE_DOC_TYPES — what SATISFIES CO-1.
#   _CONDO_PROJECT_ADJACENT_DOC_TYPES — the sibling the classifier is told is confusable with it. Its
#   presence is not a pass, but it is not a confirmed gap either: CO-1 abstains so a human can judge.
_CONDO_QUESTIONNAIRE_DOC_TYPES = frozenset({"condo_questionnaire"})
_CONDO_RESERVE_DOC_TYPES = frozenset({"condo_questionnaire", "hoa_statement"})
_CONDO_PROJECT_ADJACENT_DOC_TYPES = frozenset({"hoa_certification"})

_MASTER_POLICY_RC_PHRASES: tuple[str, ...] = (
    "guaranteed replacement cost",
    "extended replacement cost",
    "replacement cost",
    "100% replacement cost",
    "full replacement cost",
)
_MASTER_POLICY_ACV_PHRASES: tuple[str, ...] = (
    "actual cash value",
    "acv",
)


def _master_policy_basis(raw: str) -> str | None:
    """``"replacement_cost"`` / ``"actual_cash_value"`` / ``None`` (unrecognised → abstain)."""
    text = _NAME_PUNCT.sub(" ", _WS.sub(" ", raw).strip().casefold())
    text = _WS.sub(" ", text).strip()
    has_acv = any(phrase in text for phrase in _MASTER_POLICY_ACV_PHRASES)
    has_rc = any(phrase in text for phrase in _MASTER_POLICY_RC_PHRASES)
    # ⚠️ A MIXED BASIS ABSTAINS, whichever phrase leads. "ACV roof, replacement cost dwelling" states
    # two bases for two parts of the building; neither reading is the policy's basis, and calling it
    # actual_cash_value would fire IH-7 on a policy that may well be adequate for the structure.
    if has_acv and has_rc:
        return None
    if has_acv and text.startswith(_MASTER_POLICY_ACV_PHRASES):
        return "actual_cash_value"
    if has_rc and text.startswith(_MASTER_POLICY_RC_PHRASES):
        return "replacement_cost"
    return None


# --- LP-494 — the CONDO PROJECT lane (CO-4 reserves, CO-5 project eligibility). ---------------------- #
#
# THRESHOLD PROVENANCE (ADR-361 — cited, never recalled from memory). ⚠️ EVERY CONSTANT BELOW IS PINNED
# AGAINST ITS SPEC'S DECLARED reference_values BY TEST, so the code and the citation cannot drift apart.
#
#   Replacement reserves — ⚠️ A DATE-KEYED PAIR, THE FIRST IN THE SYSTEM (ADR-379).
#     10% of the annual budgeted assessment income — Fannie Mae Selling Guide B4-2.2-02, "Full Review
#     Process", page dated 08/05/2026 (tier P, fetched): "provides for the funding of replacement reserves
#     for capital expenditures and deferred maintenance that is at least 10% of the budget".
#     15%, for loan applications dated ON OR AFTER 2027-01-04 — Fannie Mae Lender Letter LL-2026-03,
#     issued 2026-03-18. ⚠️ TIER S, NOT P: the primary is behind an HTTP 403 to this client on
#     singlefamily.fanniemae.com (both the landing page and the PDF at /media/44986/display; robots.txt
#     ALLOWS both paths — the refusal is bot protection, and working around it was declined). Confirmed
#     verbatim against two independent secondary sources. ⚠️ The 08/05/2026 Selling Guide page still
#     states 10% with no sunset, which is consistent: a Lender Letter sits outside the Guide until
#     incorporated. This is why CO-4's bar carries threshold_needs_signoff.
#
#   Delinquency — more than 15% of total units 60+ days past due. B4-2.2-02 (08/05/2026, tier P,
#     fetched): "No more than 15% of the total units in a project are 60 days or more past due on common
#     expense assessments".
#
#   Commercial / mixed-use — more than 35%. B4-2.1-03, "Ineligible Projects", page dated 08/05/2026
#     (tier P, fetched): "no more than 35% of a condo or co-op project or 35% of the building in which the
#     project is located be commercial space".
#
#   Single-entity ownership — ⚠️ THE TICKET'S SOURCES CONFLICTED (>20% vs 10%) AND THE PRIMARY RESOLVES IT
#     RATHER THAN EITHER BEING GUESSED. B4-2.1-03 (08/05/2026, tier P, fetched) is TIERED, and neither
#     figure in the ticket describes it: "projects with 21 or more units - 20%", and projects of 5-20 units
#     allow a maximum of 2 units. Under 5 units the guide states no single-entity limit, so this leg
#     abstains there rather than inventing one.
#
# ⚠️ NO LITIGATION THRESHOLD EXISTS AND NONE IS INVENTED. B4-2.1-03 turns on the NATURE and SCOPE of the
# litigation, which is a judgment; the catalog rationale says "Surface". So disclosed litigation is
# SURFACED to the processor with the questionnaire's own words, and never adjudicated here.
_CONDO_RESERVE_MIN_PCT_BEFORE = Decimal("10")
_CONDO_RESERVE_MIN_PCT_FROM = Decimal("15")
_CONDO_RESERVE_STEP_UP_DATE = date(2027, 1, 4)
_CONDO_MAX_DELINQUENT_PCT = Decimal("15")
_CONDO_MAX_COMMERCIAL_PCT = Decimal("35")
_CONDO_SINGLE_ENTITY_MAX_PCT_21_PLUS = Decimal("20")
_CONDO_SINGLE_ENTITY_MAX_UNITS_SMALL = Decimal("2")
# (the condo document-type sets are defined once, above — a second binding here silently won.)


# ⚠️ A CLOSED VOCABULARY (ADR-376) — an unrecognised litigation answer ABSTAINS, and that direction is the
# whole point: "PENDING - SEE ATTACHED" must never be read as "no litigation" and clear the project.
_CONDO_LITIGATION_YES = frozenset({"yes", "y", "true", "pending", "disclosed"})
# ⚠️ "n/a"/"na" are NOT here (reported finding). They assert NOTHING about litigation — a form that
# leaves the line not-applicable has not told us there is none — so reading them as "no" is exactly
# the direction this block's own comment and the vocabulary description forbid ("an unfamiliar answer
# can never be read as 'no litigation'"). They fall through to the abstain.
_CONDO_LITIGATION_NO = frozenset({"no", "n", "false", "none"})


# --------------------------------------------------------------------------- #
# LP-509-B1 — property.type, from the STATED type or, failing that, the MISMO project indicators.
# --------------------------------------------------------------------------- #

# The DB's PropertyType enum -> the tag's declared vocabulary (sfr | condo | pud | 2-4unit |
# manufactured | coop | unknown). These are two different value spaces and were never reconciled,
# because `properties.property_type` has been null on every file so far — the passthrough this
# replaces would have emitted "single_family", a value outside the tag's own enum.
#
# `townhouse` and `other` map to NOTHING on purpose. A townhouse may be a condo, a PUD or fee-simple
# depending on how the project is organised, and that distinction is the whole point of the condo
# rules — mapping it to any one of them would be a guess that reads as fact.
_DB_PROPERTY_TYPE_TO_TAG: dict[str, str] = {
    "single_family": "sfr",
    "condo": "condo",
    "multi_family": "2-4unit",
    "manufactured": "manufactured",
}

# ConstructionMethodType values that mean a manufactured home, casefolded.
_MANUFACTURED_CONSTRUCTION = frozenset({"manufactured", "mobilehome", "mobile home"})


def _mismo_bool(snapshot: Snapshot, key: str) -> bool | None:
    """A MISMO indicator as a tri-state. Absent/blank/unparseable -> None (abstain, never False)."""
    text = _mismo_str(snapshot, key)
    if text is None:
        return None
    lowered = text.strip().casefold()
    if lowered in {"true", "yes", "y", "1"}:
        return True
    if lowered in {"false", "no", "n", "0"}:
        return False
    return None


def _property_type(
    snapshot: Snapshot, _subject_id: str, _subject_raw: object
) -> tuple[JsonValue, str]:
    """property.type — the STATED type, else derived from the MISMO project indicators.

    LF-WCHG's export states an EMPTY PropertyType, so this tag never materialized and CO-1, CO-3,
    CO-4 and IH-7 each reported "the property type has not been determined" — four findings asking a
    processor to supply something the file already contains. The same export carries
    PropertyInProjectIndicator, PUDIndicator, FinancedUnitCount and ConstructionMethodType.

    ⚠️ `in_project` IS THE DECISIVE CONDO SIGNAL, and `attachment_type` is deliberately not used as
    one. A condominium is by definition a property in a project, so `in_project == false` rules it
    out. "Detached" does NOT: Fannie Mae recognises DETACHED CONDOMINIUMS, so reading detached as
    "not a condo" would clear the condo rules on a file they were written for. This was checked
    specifically rather than assumed.

    FAIL-CLOSED THROUGHOUT. Every branch that cannot decide returns None (the tag is absent and the
    rules abstain) rather than a default. In particular an `in_project == true` file is NOT called a
    condo: a co-op and a project PUD are also "in a project", and the indicators alone cannot
    separate them.
    """
    stated = _mismo_str(snapshot, "property.type")
    if stated:
        mapped = _DB_PROPERTY_TYPE_TO_TAG.get(stated.strip().casefold())
        if mapped is not None:
            return mapped, f"the loan file states a property type of {stated!r}"
        return None, (
            f"the loan file states a property type of {stated!r}, which does not correspond to a "
            "single value in this tag's vocabulary — abstaining rather than choosing one"
        )

    in_project = _mismo_bool(snapshot, "property.in_project")
    is_pud = _mismo_bool(snapshot, "property.is_pud")
    construction = (_mismo_str(snapshot, "property.construction_method") or "").strip().casefold()
    units_text = _mismo_str(snapshot, "property.financed_unit_count")

    if construction in _MANUFACTURED_CONSTRUCTION:
        return "manufactured", (
            f"the loan file states no property type; its construction method ({construction!r}) is a "
            "manufactured home"
        )
    if in_project is None:
        return None, (
            "the loan file states no property type, and no project indicator "
            "(PropertyInProjectIndicator) either — whether this is a condominium cannot be "
            "determined, and a detached dwelling is not evidence against one"
        )
    if in_project:
        return None, (
            "the loan file states no property type; it states only that the property IS in a "
            "project, which a condominium, a co-operative and a project PUD all are — the type "
            "cannot be narrowed further from the indicators alone"
        )
    # Not in a project: a condominium and a co-op are both ruled out.
    if is_pud:
        return "pud", (
            "the loan file states no property type; it is not in a project and is flagged a PUD"
        )
    if is_pud is None:
        return None, (
            "the loan file states no property type; it is not in a project, but states no PUD "
            "indicator, so a planned-unit development cannot be ruled out"
        )
    units = _to_int_or_none(units_text)
    if units is None:
        return None, (
            "the loan file states no property type; it is neither in a project nor a PUD, but "
            "states no financed unit count, so a one-unit dwelling cannot be distinguished from a "
            "2-4 unit property"
        )
    if units >= 2:
        return "2-4unit", (
            "the loan file states no property type; it is neither in a project nor a PUD and "
            f"finances {units} units"
        )
    return "sfr", (
        "the loan file states no property type; it is not in a project (so not a condominium or "
        f"co-op), not a PUD, and finances {units} unit — a single-family residence"
    )


def _to_int_or_none(text: str | None) -> int | None:
    """A MISMO count as an int; anything unparseable is None (abstain, never a default)."""
    if text is None:
        return None
    try:
        return int(Decimal(text.strip()))
    except (ArithmeticError, ValueError):
        return None


def _condo_scope(snapshot: Snapshot) -> tuple[str | None, str]:
    """The shared condo applicability read: (None, reason) when this is not a condo file to judge.

    ⚠️ ONE implementation for both recipes, so CO-4 and CO-5 can never disagree about whether the subject
    property is a condominium — the ADR-375 discipline applied to a scoping read rather than a matcher.
    """
    property_types = {v.casefold() for v in _parsed_strings(snapshot, "property.type")}
    if not property_types:
        return None, "the file does not state the property type, so condo scoping is undecided"
    if len(property_types) > 1:
        return None, (
            f"the file states more than one property type ({', '.join(sorted(property_types))}) — "
            "ambiguous"
        )
    if next(iter(property_types)) != "condo":
        return "n/a", "the subject property is not a condominium"
    return "condo", ""


def _condo_decimal(snapshot: Snapshot, tag_id: str) -> tuple[Decimal | None, str | None]:
    """One numeric questionnaire value, or (None, reason). Disagreement across questionnaires abstains.

    Never returns 0 for a missing value: a blank reserve line is not a project with no reserves.
    """
    raw = _parsed_strings(snapshot, tag_id)
    if not raw:
        return None, None
    parsed: set[Decimal] = set()
    for value in raw:
        try:
            parsed.add(Decimal(value.replace("%", "").replace(",", "").strip()))
        except (InvalidOperation, ValueError):
            return None, f"{tag_id} reads {value!r}, which is not a number — abstaining"
    if len(parsed) > 1:
        return None, (
            f"the file's condo questionnaires state different values for {tag_id} "
            f"({', '.join(str(v) for v in sorted(parsed))}) — abstaining rather than picking one"
        )
    return next(iter(parsed)), None


_CONDO_FIDELITY_YES = frozenset({"yes", "y", "true", "present", "included", "covered"})
_CONDO_FIDELITY_NO = frozenset(
    {"no", "n", "false", "none", "not included", "not covered", "excluded"}
)
# B7-4-02 (08/05/2026, tier P): exempt at 20 units or fewer, or where the required coverage would be
# $5,000 or less. Recorded for the reasoning text — NOT applied, because no document states the count.
_CONDO_FIDELITY_EXEMPT_MAX_UNITS = 20


def _condo_fidelity_coverage(
    snapshot: Snapshot, _subject_id: str, _subject_raw: object
) -> tuple[JsonValue, str]:
    """ins.condo_fidelity_coverage — does the project's master policy EVIDENCE fidelity/crime cover? (CO-3)

    ⚠️ THIS IS THE ONE CONDO-INSURANCE QUESTION NO LIVE RULE ASKS. IH-7's spec header excludes fidelity
    explicitly, so this is not a second verdict on the same comparison (ADR-375) — it is the gap IH-7
    documented and left open.

    ⚠️ PRESENCE, NOT ADEQUACY, AND THE LIMIT IS STATED RATHER THAN FUDGED. B7-4-02 sets the required
    amount at "the sum of three months of assessments on all units in the project" and exempts projects of
    20 units or fewer. NEITHER the unit count NOR the assessment base resolves on any document in the
    corpus, so this recipe does not compare the amount against anything. It reports whether coverage is
    EVIDENCED — itself a Fannie requirement the lender must verify — and carries the amount inline so a
    processor can finish the arithmetic the file cannot.
    """
    scope, reason = _condo_scope(snapshot)
    if scope != "condo":
        return (scope or _UNKNOWN), (
            reason
            if scope != "n/a"
            else "the subject property is not a condominium — no project fidelity coverage is required"
        )

    has_policy = any(
        entry.document_type in _CONDO_MASTER_POLICY_DOC_TYPES
        for entry in (() if snapshot.documents.absent else snapshot.documents.entries)
    )
    if not has_policy:
        return _UNKNOWN, (
            "the file carries no condominium master insurance policy, so the project's fidelity/crime "
            "coverage cannot be read — IH-7 reports the missing policy itself"
        )

    answers = {
        v.casefold().strip() for v in _parsed_strings(snapshot, "condo.fidelity_present_raw")
    }
    if not answers:
        return (
            _UNKNOWN,
            "the master policy on file does not state whether fidelity/crime coverage is carried",
        )
    if answers <= _CONDO_FIDELITY_YES:
        # ⚠️ THE AMOUNT IS EVIDENCE, NOT A GATE (reported finding). This recipe deliberately does not
        # judge the amount — B7-4-02's required figure needs a unit count and an assessment base that
        # resolve on no document here. So a PROBLEM reading it (two master policies stating $50,000 and
        # $75,000 — a prior-year certificate beside the current renewal, a routine pairing) must not flip
        # a clearly-evidenced "present" to couldnt_check. The disagreement is reported inline instead, so
        # the processor sees both figures and finishes the arithmetic the file cannot.
        amount, problem = _condo_decimal(snapshot, "condo.fidelity_amount")
        if problem is not None:
            detail = f" (the amount could not be read: {problem})"
        elif amount is not None:
            detail = f" of ${amount:,}"
        else:
            detail = ""
        return "present", (
            f"the condominium project's master policy evidences fidelity/crime coverage{detail}. ⚠️ The "
            "AMOUNT is not verified against Fannie B7-4-02's requirement (three months of assessments on "
            "all units): neither the project's unit count nor its assessment base is stated on any "
            "document in the file"
        )
    if answers <= _CONDO_FIDELITY_NO:
        return "absent", (
            "the condominium project's master policy states that no fidelity/crime coverage is carried; "
            f"Fannie B7-4-02 requires it unless the project has {_CONDO_FIDELITY_EXEMPT_MAX_UNITS} units "
            "or fewer, or would need $5,000 of coverage or less"
        )
    if answers & _CONDO_FIDELITY_YES and answers & _CONDO_FIDELITY_NO:
        # ⚠️ DISAGREEMENT IS ITS OWN ANSWER (reported finding) — the same bug fixed one function below in
        # _condo_project_eligibility. Two master policies answering "Yes" and "No" match neither subset,
        # fell to the unrecognised branch, and reported sorted(answers)[0]: "the indicator reads 'no',
        # which is not a recognised yes/no answer". 'no' IS recognised; the reason was false and it hid a
        # contradiction BETWEEN DOCUMENTS.
        return _UNKNOWN, (
            f"the file's master policies disagree about fidelity/crime coverage "
            f"({', '.join(sorted(answers))}) — abstaining rather than picking one"
        )
    return _UNKNOWN, (
        f"the master policy's fidelity/crime indicator reads {sorted(answers)[0]!r}, which is not a "
        "recognised yes/no answer — abstaining rather than reporting the project as uncovered"
    )


def _condo_reserve_adequacy(
    snapshot: Snapshot, _subject_id: str, _subject_raw: object
) -> tuple[JsonValue, str]:
    """condo.reserve_adequacy — do the HOA's budgeted replacement reserves meet the floor? (CO-4)

    ⚠️ THE FLOOR IS DATE-KEYED, and the date is the APPLICATION's, never today's. Fannie LL-2026-03 raises
    the minimum from 10% to 15% for applications dated on or after 2027-01-04, so a rule keyed on the
    current date would apply next year's floor to an application taken this year and fire on a compliant
    project. An ABSENT application date is the one input that cannot be defaulted: it SELECTS the floor,
    so its absence abstains (ADR-379).
    """
    scope, reason = _condo_scope(snapshot)
    if scope != "condo":
        return (scope or _UNKNOWN), (
            reason
            if scope != "n/a"
            else "the subject property is not a condominium — no HOA reserve floor applies"
        )

    # ⚠️ TWO INDEPENDENT SOURCES, NEITHER PREFERRED. The HOA statement's reserve_percentage resolves on
    # real data (6/59, four of them "10"); the condo questionnaire's is the same fact from the association's
    # own form. Read together so a disagreement ABSTAINS instead of one silently overriding the other —
    # IH-7's no-cross-document-pooling finding, applied across document TYPES rather than copies.
    reserve_pct, problem = _condo_decimal(snapshot, "condo.reserve_pct")
    if problem is not None:
        return _UNKNOWN, problem
    questionnaire_pct, problem = _condo_decimal(snapshot, "condo.reserve_pct_questionnaire")
    if problem is not None:
        return _UNKNOWN, problem
    if (
        reserve_pct is not None
        and questionnaire_pct is not None
        and reserve_pct != questionnaire_pct
    ):
        return _UNKNOWN, (
            f"the HOA statement states a replacement-reserve allocation of {reserve_pct}% and the condo "
            f"questionnaire states {questionnaire_pct}% — abstaining rather than judging the project by "
            "one of two figures the association itself reports differently"
        )
    reserve_pct = reserve_pct if reserve_pct is not None else questionnaire_pct
    if reserve_pct is None:
        has_source = any(
            entry.document_type in _CONDO_RESERVE_DOC_TYPES
            for entry in (() if snapshot.documents.absent else snapshot.documents.entries)
        )
        return _UNKNOWN, (
            "neither the condo questionnaire nor the HOA statement on file states the budgeted "
            "replacement-reserve percentage"
            if has_source
            else "the file carries no condo questionnaire or HOA statement stating the budgeted "
            "replacement-reserve percentage"
        )

    application_dates = _parsed_strings(snapshot, "loan.application_received_date")
    if not application_dates:
        return _UNKNOWN, (
            "the file does not state the loan application date, and the date is what selects the reserve "
            "floor (10% before 2027-01-04, 15% on or after) — abstaining rather than applying one of them"
        )
    application_date = coerce_date(application_dates[0])
    if application_date is None:
        return _UNKNOWN, (
            f"the loan application date reads {application_dates[0]!r}, which is not a date — abstaining "
            "rather than selecting a reserve floor from an unreadable date"
        )

    from_2027 = application_date >= _CONDO_RESERVE_STEP_UP_DATE
    floor = _CONDO_RESERVE_MIN_PCT_FROM if from_2027 else _CONDO_RESERVE_MIN_PCT_BEFORE
    citation = (
        "Fannie Mae LL-2026-03, which raises the minimum to 15% for applications dated on or after "
        "2027-01-04"
        if from_2027
        else "Fannie Mae Selling Guide B4-2.2-02 (08/05/2026)"
    )
    if reserve_pct < floor:
        return "inadequate", (
            f"the association budgets {reserve_pct}% of its annual assessment income to replacement "
            f"reserves, below the {floor}% required for an application dated {application_date} "
            f"({citation})"
        )
    return "adequate", (
        f"the association budgets {reserve_pct}% of its annual assessment income to replacement reserves, "
        f"at or above the {floor}% required for an application dated {application_date} ({citation})"
    )


def _condo_delinquent_60day_pct(
    snapshot: Snapshot, _subject_id: str, _subject_raw: object
) -> tuple[JsonValue, str]:
    """condo.delinquent_units_pct — units 60+ DAYS past due as a percent of total units (CO-5).

    ⚠️ COMPUTED FROM THE 60-DAY COUNT, not the questionnaire's generic ``delinquency_percentage``
    (reported finding). B4-2.2-02's 15% cap is stated on units **60 or more days** past due; the generic
    field carries whatever period the form chose — commonly 30+ — and the extractor prompt attaches no
    definition to it. Comparing a 30-day figure to a 60-day cap fires CO-5 on a compliant project.

    Abstains when either input is missing or ``total_units`` is not positive: a percentage cannot be
    built from half a fraction, and a fabricated 0 would read as a clean project.
    """
    count, problem = _condo_decimal(snapshot, "condo.units_delinquent_over_60_days")
    if problem is not None:
        return _UNKNOWN, problem
    total, problem = _condo_decimal(snapshot, "condo.total_units")
    if problem is not None:
        return _UNKNOWN, problem
    if count is None or total is None:
        return _UNKNOWN, (
            "the questionnaire does not state both the 60-day delinquent unit count and the total unit "
            "count, so the 60-day delinquency rate cannot be computed"
        )
    if total <= 0:
        return _UNKNOWN, "the questionnaire states a total unit count of zero or less"
    pct = (count / total * Decimal(100)).quantize(Decimal("0.01"))
    return str(pct), (
        f"{count} of the project's {total} units are 60+ days past due on common expense assessments "
        f"({pct}%)"
    )


def _condo_project_eligibility(
    snapshot: Snapshot, _subject_id: str, _subject_raw: object
) -> tuple[JsonValue, str]:
    """condo.project_eligibility — delinquency, concentration and litigation surfaced (CO-5).

    ⚠️ "clear" REQUIRES ALL FOUR LEGS TO HAVE BEEN READ. A blank questionnaire resolves to "unknown", never
    "clear": telling a processor a project is eligible because nobody answered the questions is the exact
    false all-clear this lane exists to prevent.
    """
    scope, reason = _condo_scope(snapshot)
    if scope != "condo":
        return (scope or _UNKNOWN), (
            reason
            if scope != "n/a"
            else "the subject property is not a condominium — no project review applies"
        )

    delinquent_pct, problem = _condo_decimal(snapshot, "condo.delinquent_units_pct")
    if problem is not None:
        return _UNKNOWN, problem
    commercial_pct, problem = _condo_decimal(snapshot, "condo.commercial_space_pct")
    if problem is not None:
        return _UNKNOWN, problem
    total_units, problem = _condo_decimal(snapshot, "condo.total_units")
    if problem is not None:
        return _UNKNOWN, problem
    single_entity_units, problem = _condo_decimal(snapshot, "condo.single_entity_owned_units")
    if problem is not None:
        return _UNKNOWN, problem

    # THE HARD LIMITS FIRST — an ineligible project outranks a litigation disclosure, because it is a
    # decided fact about the project rather than something for a processor to weigh.
    if delinquent_pct is not None and delinquent_pct > _CONDO_MAX_DELINQUENT_PCT:
        return "ineligible_threshold", (
            f"{delinquent_pct}% of the project's units are 60+ days past due on common expense "
            f"assessments; Fannie B4-2.2-02 (08/05/2026) allows no more than "
            f"{_CONDO_MAX_DELINQUENT_PCT}%"
        )
    if commercial_pct is not None and commercial_pct > _CONDO_MAX_COMMERCIAL_PCT:
        return "ineligible_threshold", (
            f"{commercial_pct}% of the project is commercial or mixed-use space; Fannie B4-2.1-03 "
            f"(08/05/2026) allows no more than {_CONDO_MAX_COMMERCIAL_PCT}%"
        )
    concentration_read = False
    if total_units is not None and single_entity_units is not None and total_units > 0:
        # ⚠️ READ, not "missing" (reported finding). B4-2.1-03's tiers do not extend below 5 units, so a
        # 4-unit project has no stated single-entity limit — but that is the leg being ANSWERED (no limit
        # applies), not unanswered. Setting it here rather than inside the tiers stops the roll-call below
        # reporting "the condo questionnaire does not answer the single-entity concentration" about a form
        # that answered it, which made every small project permanently couldnt_check and sent a processor
        # to chase a figure already on the page. The genuinely missing case is total_units or
        # single_entity_units being ABSENT, which this branch already excludes.
        concentration_read = True
        if total_units >= 21:
            share = single_entity_units / total_units * Decimal(100)
            if share > _CONDO_SINGLE_ENTITY_MAX_PCT_21_PLUS:
                return "ineligible_threshold", (
                    f"a single entity owns {single_entity_units} of the project's {total_units} units "
                    f"({share:.1f}%); Fannie B4-2.1-03 (08/05/2026) allows no more than "
                    f"{_CONDO_SINGLE_ENTITY_MAX_PCT_21_PLUS}% in a project of 21 or more units"
                )
        elif total_units >= 5:
            if single_entity_units > _CONDO_SINGLE_ENTITY_MAX_UNITS_SMALL:
                return "ineligible_threshold", (
                    f"a single entity owns {single_entity_units} of the project's {total_units} units; "
                    f"Fannie B4-2.1-03 (08/05/2026) allows a maximum of "
                    f"{_CONDO_SINGLE_ENTITY_MAX_UNITS_SMALL} units in a project of 5 to 20 units"
                )

    litigation_raw = _parsed_strings(snapshot, "condo.litigation_disclosed")
    litigation_answers = {v.casefold().strip() for v in litigation_raw}
    litigation_disclosed: bool | None = None
    if litigation_answers:
        if litigation_answers <= _CONDO_LITIGATION_YES:
            litigation_disclosed = True
        elif litigation_answers <= _CONDO_LITIGATION_NO:
            litigation_disclosed = False
        elif litigation_answers & _CONDO_LITIGATION_YES and (
            litigation_answers & _CONDO_LITIGATION_NO
        ):
            # ⚠️ DISAGREEMENT IS ITS OWN ANSWER (reported finding). Two questionnaires answering "Yes"
            # and "No" match neither subset and fell into the unrecognised-value branch, which then
            # reported sorted(...)[0] — rendering "the litigation answer reads 'no', which is not a
            # recognised yes/no answer". The verdict was right and the reason was false, and it hid a
            # contradiction BETWEEN DOCUMENTS. _condo_decimal already carries this branch.
            return _UNKNOWN, (
                f"the file's questionnaires disagree about litigation "
                f"({', '.join(sorted(litigation_answers))}) — abstaining rather than picking one"
            )
        else:
            return _UNKNOWN, (
                f"the questionnaire's litigation answer reads {sorted(litigation_answers)[0]!r}, which is "
                "not a recognised yes/no answer — abstaining rather than reading it as no litigation"
            )
    if litigation_disclosed:
        return "litigation_disclosed", (
            "the condo questionnaire discloses litigation involving the project; Fannie B4-2.1-03 turns on "
            "the nature and scope of the action, which is a judgment for the file, not a threshold"
        )

    missing = [
        name
        for name, seen in (
            ("the delinquency percentage", delinquent_pct is not None),
            ("the commercial space percentage", commercial_pct is not None),
            ("the single-entity concentration", concentration_read),
            ("the litigation answer", litigation_disclosed is not None),
        )
        if not seen
    ]
    if missing:
        return _UNKNOWN, (
            f"the condo questionnaire does not answer {', '.join(missing)} — a project cannot be reported "
            "eligible on questions nobody answered"
        )
    return "clear", (
        f"the project's delinquency ({delinquent_pct}%), commercial space ({commercial_pct}%) and "
        f"single-entity concentration are all within Fannie's limits, and the questionnaire discloses no "
        "litigation"
    )


def _condo_master_policy(
    snapshot: Snapshot, _subject_id: str, _subject_raw: object
) -> tuple[JsonValue, str]:
    """ins.condo_master_policy — is the condo master policy present and adequate? (IH-7)

    LOAN-scoped, because ``absent`` is a statement about the FILE and no per-document tag can be
    produced for a document that is not there.

    ``n/a`` when the property is not a condo · ``absent`` when no master policy states a policy number ·
    ``present_adequate`` / ``present_inadequate`` on the basis and liability limit · ``unknown`` whenever
    an input is missing or unrecognised. Never reads a missing input as adequate.
    """
    # ⚠️ THE SHARED SCOPE (reported finding). _condo_scope's docstring claims to be "ONE implementation
    # ... so CO-4 and CO-5 can never disagree", while this byte-identical block sat inline here for live
    # IH-7 — so a future fix (accepting a MISMO "Condominium" spelling, say) would land in one copy and
    # IH-7 would then disagree with CO-4/CO-5 about whether the subject is a condo.
    scope, why = _condo_scope(snapshot)
    if scope is None:
        return _UNKNOWN, why
    if scope == "n/a":
        return "n/a", "the subject property is not a condominium — no master policy is required"

    # ⚠️ PRESENCE IS ABOUT THE DOCUMENT, not one extracted field (reported finding). Keying `absent` on
    # condo.master_policy_number alone meant a master-policy certificate that IS on the file but whose
    # number failed to extract reported "absent" and FIRED, telling a processor to request a document
    # already in front of them. That contradicts this recipe's own discipline two branches down, where an
    # unreadable basis abstains "rather than inferring". A present-but-unreadable document abstains.
    has_document = any(
        entry.document_type in _CONDO_MASTER_POLICY_DOC_TYPES
        for entry in (() if snapshot.documents.absent else snapshot.documents.entries)
    )
    if not _parsed_strings(snapshot, "condo.master_policy_number"):
        if has_document:
            return _UNKNOWN, (
                "the file carries a condominium master-policy document but no policy number could be "
                "read from it — abstaining rather than reporting the policy as missing"
            )
        return "absent", (
            "the property is a condominium but the file carries no master insurance policy stating a "
            "policy number"
        )

    bases = _parsed_strings(snapshot, "condo.master_policy_basis_raw")
    if not bases:
        return _UNKNOWN, "the master policy does not state a replacement-cost basis"
    normalised = {_master_policy_basis(b) for b in bases}
    if None in normalised:
        unrecognised = [b for b in bases if _master_policy_basis(b) is None]
        return _UNKNOWN, (
            f"the master policy's coverage basis reads {unrecognised[0]!r}, which is not a recognised "
            "replacement-cost or actual-cash-value term — abstaining rather than inferring"
        )
    # ⚠️ NO CROSS-DOCUMENT POOLING (reported finding). These values are gathered across EVERY master-policy
    # document with no pairing, so two certificates — a current one and a superseded one — were being
    # judged as if they described one policy. Mixed bases fired `present_inadequate` with reasoning that
    # flatly asserted "written on an actual-cash-value basis" when one of them was replacement cost.
    # Disagreement is not a finding, it is an unresolved subject: abstain, exactly as _file_lender_name
    # does directly above and as the two-binder housing.insurance_monthly rule does.
    if len(normalised) > 1:
        return _UNKNOWN, (
            f"the file's master-policy documents state different coverage bases "
            f"({', '.join(sorted(str(b) for b in normalised))}) — abstaining rather than judging one "
            "policy by another's terms"
        )
    if normalised != {"replacement_cost"}:
        return "present_inadequate", (
            "the condominium master policy is written on an actual-cash-value basis; Fannie Mae "
            "B7-3-03 requires coverage equal to at least 100% of replacement cost"
        )

    limits = _parsed_strings(snapshot, "condo.master_liability_limit")
    if not limits:
        return _UNKNOWN, "the master policy does not state a general liability limit"
    parsed_limits: list[Decimal] = []
    for value in limits:
        try:
            parsed_limits.append(Decimal(value.replace(",", "").replace("$", "").strip()))
        except (InvalidOperation, ValueError):
            return _UNKNOWN, (
                f"the master policy's general liability limit reads {value!r}, which is not a number — "
                "abstaining rather than treating it as zero"
            )
    # ⚠️ Same reasoning as the basis above: `min()` across unrelated certificates judged the CURRENT
    # policy by a SUPERSEDED one's limit — a live $2,000,000 certificate beside an old $500,000 one fired.
    if len({*parsed_limits}) > 1:
        return _UNKNOWN, (
            "the file's master-policy documents state different general liability limits "
            f"({', '.join(f'${v:,}' for v in sorted(set(parsed_limits)))}) — abstaining rather than "
            "judging the policy by the lowest figure on file"
        )
    lowest = min(parsed_limits)
    if lowest < _CONDO_MIN_LIABILITY_PER_OCCURRENCE:
        return "present_inadequate", (
            f"the master policy's general liability limit is ${lowest:,} per occurrence; Fannie Mae "
            "B7-4-01 requires at least $1,000,000 for any single occurrence"
        )
    return "present_adequate", (
        f"the condominium master policy is written on a replacement-cost basis with a general "
        f"liability limit of ${lowest:,} per occurrence"
    )


# --------------------------------------------------------------------------- #
# LP-453 (step D.2) — the tradelines list consumer: DETERMINISTIC numeric OBSERVATIONS over the credit
# report's `tradelines` list. Scoped EXPLICITLY to credit_report documents (document_type filter, LP-453
# review) — a list-name is not a unique key, so a future extractor reusing `tradelines` cannot pollute the
# credit aggregate.
#
# ⚠️ THE D3 FINDING (the LP-448 lesson, second instance): the row VOCABULARY is OPEN-ENDED bureau text —
# account_type is terse bureau codes (AUTO / INST / REV, and elsewhere MTG / EDU / COLL / CHG …), account_status
# is bureau phrasing (AS AGREED / PAID …), payment_status is Metro-2 codes (I1 / R1 …), is_disputed is FREE-TEXT
# that includes NON-disputes (forbearance, "closed by grantor"), and payment_history_24mo is a VARIABLE-LENGTH
# 0/- string (16 to 84 chars on one real report), NOT a fixed position-per-month encoding. So classifying
# mortgage / student / collection, interpreting a dispute, or parsing "recent lates" is JUDGMENT, not a lookup —
# a Priya/AI question, deferred to the rule tickets (ADR). This consumer therefore emits ONLY pure numeric
# aggregates that need no classification: a COUNT and a MONTHLY-PAYMENT TOTAL. Tags DESCRIBE; rules judge —
# NEVER a threshold, a "is_derogatory", a "has_unacceptable_lates". Fail closed: no tradelines captured → the
# tag abstains to "unknown" (the standard derived-abstain value, materialised on the loan subject — a gated
# rule reads couldnt_check), NEVER a fabricated 0.
#
# LIMITATION (reported): loan-level aggregate — a file with MULTIPLE overlapping bureau reports could
# double-count. LF-96SV has one 18-row report + one empty; no double-count. Multi-report dedup is a future
# concern (a rule's, once it reconciles bureaus).
# --------------------------------------------------------------------------- #
def _credit_undisclosed_tradeline(
    snapshot: Snapshot, _subject_id: str, _subject_raw: object
) -> tuple[JsonValue, str]:
    """credit.undisclosed_tradeline — the BORROWER-level rollup of the per-liability judgment (ADR-375).

    "yes" when ANY credit-report tradeline was judged NOT in the application; "no" when every judged
    tradeline is accounted for. DEMOTED from an AI tag to this recipe so the borrower answer is a pure
    function of the per-liability answers — CR-4 and CR-1 cannot disagree about the same file.

    ⚠️ FAIL-CLOSED, and this is the seam where a false all-clear would slip in. It ABSTAINS to "unknown"
    (NEVER "no") when there is nothing to aggregate — no credit report, no tradeline subjects, or no
    ``liab.in_application`` produced on any of them. "No undisclosed debt" on a file with no credit report
    is a false ALL-CLEAR, which is worse than saying nothing. A subject the matcher answered "unknown" for
    does not count as accounted-for: if EVERY answer is unknown the rollup is unknown, and a single
    confident "no" still yields "yes" (one undisclosed debt is the finding, regardless of the others).
    """
    # LAZY import (init-order — rule_engine ↔ tag_materialization, as _stmt_min_account_months does).
    from app.verification.rule_engine.enumerators import _SOURCE_CREDIT_REPORT, liability_rows

    if snapshot.tags.absent:
        return _UNKNOWN, "no tags materialized, so no per-liability judgment to aggregate"
    reported = [r for r in liability_rows(snapshot) if r.source == _SOURCE_CREDIT_REPORT]
    if not reported:
        return (
            _UNKNOWN,
            "no credit-report tradelines on the file — nothing to compare against the 1003",
        )
    judged = 0
    undisclosed = 0
    for row in reported:
        tag = snapshot.tags.by_subject.get(row.subject_id, {}).get("liab.in_application")
        if tag is None or tag.value in (None, _UNKNOWN):
            continue
        judged += 1
        if str(tag.value) == "no":
            undisclosed += 1
    if judged == 0:
        return (
            _UNKNOWN,
            f"{len(reported)} tradelines, but none carries a usable in-application judgment "
            "(absent or unknown) — cannot conclude the application is complete",
        )
    if undisclosed:
        return "yes", (
            f"{undisclosed} of {judged} judged tradelines are not reflected in the application's "
            "stated liabilities"
        )
    return (
        "no",
        f"all {judged} judged tradelines are reflected in the application's stated liabilities",
    )


def _credit_tradeline_count(
    snapshot: Snapshot, _subject_id: str, _subject_raw: object
) -> tuple[JsonValue, str]:
    """credit.tradeline_count — how many tradelines the file's credit report(s) list (a pure OBSERVATION, no
    open/closed classification — distinct from the extractor's open_tradeline_count). Abstains to "unknown"
    when no tradelines are captured — never a fabricated 0. Returned as a numeric STRING (the derived numeric
    convention, matching stmt.nsf_count)."""
    rows = all_list_rows(snapshot, "tradelines", document_type="credit_report")
    if not rows:
        return _UNKNOWN, "no credit-report tradelines captured in the file"
    return str(len(rows)), f"{len(rows)} tradelines observed across the file's credit report(s)"


def _credit_tradeline_monthly_payment_total(
    snapshot: Snapshot, _subject_id: str, _subject_raw: object
) -> tuple[JsonValue, str]:
    """credit.tradeline_monthly_payment_total — the sum of the tradelines' monthly_payment (a coerced number
    per row), the OBSERVATION CR-1 cross-checks against the DTI's liability payments. A present 0 (a paid-off
    account) contributes 0 honestly. ABSTAINS to unknown (NEVER 0) when no tradeline carries a payment figure —
    fail-closed, so a rule reads couldnt_check on missing data rather than a fabricated 0."""
    rows = all_list_rows(snapshot, "tradelines", document_type="credit_report")
    if not rows:
        return _UNKNOWN, "no credit-report tradelines captured in the file"
    total = Decimal(0)
    seen = False
    for row in rows:
        field = row.fields.get("monthly_payment")
        if field is not None and field.is_present and field.value is not None:
            try:
                total += Decimal(str(field.value))
                seen = True
            except (InvalidOperation, ValueError):
                continue  # an unparseable payment is skipped, never guessed
    if not seen:
        return _UNKNOWN, f"{len(rows)} tradelines but none carry a monthly payment figure"
    return (
        str(total),
        f"total monthly tradeline payment {total} (sum across {len(rows)} tradelines' monthly_payment)",
    )


# The address normalizer chain for property-address matching (LP-407-4) — the consistency normalizers
# (casefold / drop_punct / collapse_ws), REUSED, never a new fuzzy matcher. NOT drop_entity_suffix (that is
# for company names).
_ADDRESS_NORMALIZERS = ("casefold", "drop_punct", "collapse_ws")

_MISMO_PROPERTY_ADDRESS_KEYS = (
    "property.address_line",
    "property.address_line_2",
    "property.city",
    "property.state",
    "property.postal_code",
)

# LP-407-4 review — deterministic address canonicalization, applied AFTER the base normalizers. A freeform
# contract ``property_address`` and the component-assembled MISMO address legitimately differ, for the SAME
# property, on standard surface forms the base normalizers leave untouched — USPS street suffixes, US state
# names, and ZIP+4 vs ZIP5. Canonicalizing those (below) stops PC-3 from routing the common same-property file
# to needs_review just because one side wrote "Street"/"Illinois"/"62711-1234". SAFETY: each map unifies ONLY
# true synonyms of ONE token, and the SAME transform runs on both sides — so two GENUINELY different addresses
# cannot be merged (they still differ on house number / street name / city), and a semantically-off mapping
# (e.g. a city named like a state) still transforms both sides identically, so it never fabricates a mismatch.
# Unit designators (apt / # / unit / suite) and directionals (N / North) are DELIBERATELY not canonicalized —
# their surface forms are too varied to unify safely; those residues still route to needs_review (ADR-325 — the
# deferred AI-tolerant match handles them).
_STREET_SUFFIX_CANON = {
    "street": "st", "st": "st",
    "avenue": "ave", "ave": "ave", "av": "ave",
    "road": "rd", "rd": "rd",
    "lane": "ln", "ln": "ln",
    "drive": "dr", "dr": "dr",
    "boulevard": "blvd", "blvd": "blvd",
    "court": "ct", "ct": "ct",
    "circle": "cir", "cir": "cir",
    "place": "pl", "pl": "pl",
    "terrace": "ter", "ter": "ter",
    "parkway": "pkwy", "pkwy": "pkwy",
    "highway": "hwy", "hwy": "hwy",
    "trail": "trl", "trl": "trl",
    "square": "sq", "sq": "sq",
    "loop": "loop",
    "way": "way",
}  # fmt: skip
# US state / territory names -> the USPS 2-letter code. Multi-word names are replaced as PHRASES first (below),
# so "north carolina" is not mistaken for the directional "north" + "carolina".
_STATE_CANON = {
    "alabama": "al", "alaska": "ak", "arizona": "az", "arkansas": "ar", "california": "ca",
    "colorado": "co", "connecticut": "ct", "delaware": "de", "florida": "fl", "georgia": "ga",
    "hawaii": "hi", "idaho": "id", "illinois": "il", "indiana": "in", "iowa": "ia",
    "kansas": "ks", "kentucky": "ky", "louisiana": "la", "maine": "me", "maryland": "md",
    "massachusetts": "ma", "michigan": "mi", "minnesota": "mn", "mississippi": "ms", "missouri": "mo",
    "montana": "mt", "nebraska": "ne", "nevada": "nv", "new hampshire": "nh", "new jersey": "nj",
    "new mexico": "nm", "new york": "ny", "north carolina": "nc", "north dakota": "nd", "ohio": "oh",
    "oklahoma": "ok", "oregon": "or", "pennsylvania": "pa", "rhode island": "ri", "south carolina": "sc",
    "south dakota": "sd", "tennessee": "tn", "texas": "tx", "utah": "ut", "vermont": "vt",
    "virginia": "va", "washington": "wa", "west virginia": "wv", "wisconsin": "wi", "wyoming": "wy",
    "district of columbia": "dc", "puerto rico": "pr",
}  # fmt: skip
_MULTIWORD_STATE_PATTERNS = tuple(
    (re.compile(rf"\b{re.escape(name)}\b"), code)
    for name, code in _STATE_CANON.items()
    if " " in name
)


def _norm_address(raw: str) -> str:
    """Base-normalize (casefold / drop_punct / collapse_ws) then canonicalize the standard surface forms two
    renderings of the SAME property differ on — street suffixes, US state names, ZIP+4 -> ZIP5 — so PC-3's
    equality compare stops flagging them (see the table comment for the safety argument)."""
    # LAZY import (init-order — rule_engine <-> tag_materialization, as income_employer_coverage does).
    from app.verification.rule_engine.consistency import _normalize

    text = _normalize(raw, _ADDRESS_NORMALIZERS)
    for (
        pattern,
        code,
    ) in _MULTIWORD_STATE_PATTERNS:  # multi-word states as phrases, before tokenizing
        text = pattern.sub(code, text)
    out: list[str] = []
    for tok in text.split():
        if tok.isdigit() and len(tok) == 9:  # ZIP+4 (drop_punct removed the hyphen) -> ZIP5
            out.append(tok[:5])
        elif tok in _STREET_SUFFIX_CANON:
            out.append(_STREET_SUFFIX_CANON[tok])
        elif tok in _STATE_CANON:  # single-word state name -> code
            out.append(_STATE_CANON[tok])
        else:
            out.append(tok)
    return " ".join(out)


def _property_address_match(
    snapshot: Snapshot, _subject_id: str, _subject_raw: object
) -> tuple[JsonValue, str]:
    """property.address_normalized_match — does the purchase contract's SUBJECT-PROPERTY address match the loan
    file's (1003/MISMO) subject-property address? Unblocks PC-3.

    Compares the purchase_agreement's typed-core ``property_address`` against the MISMO SUBJECT-property address
    (property.address_line [+ _2] + city + state + postal_code), after the consistency normalizers PLUS the
    deterministic address canonicalization (_norm_address: street suffixes / US state names / ZIP+4 -> ZIP5 —
    REUSED normalizers, no fuzzy matcher). DESCRIPTIVE enum yes/no/unknown; PC-3 JUDGES (no -> needs_review,
    ADR-325 — the canonicalizer does not resolve EVERY surface form, e.g. unit designators, so a residual
    mismatch is surfaced for a human, not fired as certain).

    ⚠️ THE MAILING-ADDRESS TRAP (LP-407-4 D1): reads the MISMO SUBJECT-property address (property.address_*), NEVER
    the borrower's ``current_address`` (which the MISMO parser can fill with a MAILING address) and NEVER a
    retained-property tax bill (a different property). A file lacking a complete subject-property address ->
    unknown (couldnt_check), never a comparison against the wrong address type.

    FAIL-CLOSED: no purchase contract / contracts DISAGREE on the address / no complete MISMO subject address ->
    unknown. The reasoning names BOTH addresses (the finding's provenance — the AS-8 break_detail pattern; the
    operand path is decimal/date only and cannot string-compare, so this is an enum branch, not an interpolated
    operand)."""
    if snapshot.documents.absent:
        return (
            _UNKNOWN,
            "no documents in the file — no purchase contract to read a property address from",
        )
    contract_addrs: dict[str, str] = {}  # normalized -> an original rendering (for the reason)
    for entry in snapshot.documents.entries:
        if entry.document_type != "purchase_agreement":
            continue
        field = entry.fields.get("property_address")
        if isinstance(field, Field) and field.is_present and str(field.value).strip():
            raw = str(field.value).strip()
            contract_addrs[_norm_address(raw)] = raw
    if not contract_addrs:
        return _UNKNOWN, "no purchase contract states a property address"
    if len(contract_addrs) > 1:
        return _UNKNOWN, (
            "the file's purchase contracts disagree on the property address "
            f"({', '.join(sorted(contract_addrs.values()))}) — ambiguous"
        )
    contract_norm, contract_raw = next(iter(contract_addrs.items()))

    # The file's SUBJECT-property address from MISMO — require the street line + city + state + postal so a
    # PARTIAL address is never compared (fail-closed; postal_code alone or a mailing fragment must not match).
    line, line2, city, state, postal = (
        _mismo_str(snapshot, k) for k in _MISMO_PROPERTY_ADDRESS_KEYS
    )
    if not (line and city and state and postal):
        return _UNKNOWN, (
            "the loan file (1003/MISMO) does not state a complete subject-property address — cannot compare "
            "(never a comparison against a partial or mailing address)"
        )
    file_raw = " ".join(p for p in (line, line2, city, state, postal) if p)
    if contract_norm == _norm_address(file_raw):
        return "yes", (
            f"the purchase contract's property address matches the loan file's subject property "
            f"('{contract_raw}' vs the file's '{file_raw}')"
        )
    return "no", (
        f"the purchase contract is for '{contract_raw}' but the loan file states the subject property is "
        f"'{file_raw}' — confirm they describe the same property"
    )


# --------------------------------------------------------------------------- #
# LP-410 — the derived-producer wave: three tags that unblock PC-7 / AS-8 / IN-6.
# Four Bucket 2 Phase 0s established these rules' inputs are produced but their CHECKS are not
# expressible in the DSL (PC-7: no `today` operand; AS-8: ordered-pairwise, ADR-322; IN-6: set-coverage,
# ADR-323). Each is answered by DERIVING the fact here, so a trivial rule can branch on it. THE TAGS
# DESCRIBE (a number / an observed-state enum); the RULES JUDGE — no threshold/policy lives in a
# producer (LP-400). Each fail-closes to "unknown"; each emits a value that lets its rule reach
# not_applicable where there is nothing to check. All are DERIVED (no AI call) and ADDITIVE.
# --------------------------------------------------------------------------- #


def _contract_days_until_closing(
    snapshot: Snapshot, _subject_id: str, _subject_raw: object
) -> tuple[JsonValue, str]:
    """contract.days_until_closing — SIGNED days from the file (snapshot) date to the loan's closing date.

    Positive = the closing date is in the FUTURE; negative = it is in the PAST (a stale/past closing
    date). Unblocks PC-7. Mirrors income.days_since_most_recent_pay for the snapshot-date arithmetic
    (recency against ``snapshot.created_at`` — deterministic, never a wall-clock ``now()``) and
    _loan_closing_date for gathering the single closing date (dedup by parsed date; documents that
    DISAGREE → unknown). DESCRIPTIVE — it emits the NUMBER; PC-7's 'realistic window' (how far past/future
    is acceptable) is the RULE's, Priya-validated, never the tag's (LP-400). FAIL-CLOSED to unknown."""
    if snapshot.tags.absent:
        return _UNKNOWN, "no tags materialized to read a closing date from"
    # Only PARSEABLE closing dates (a number needs a real date for the arithmetic), deduped by the parsed
    # date so one date rendered two ways is ONE value; >1 distinct parsed date → the documents disagree.
    dates: dict[date, str] = {}
    for tags in snapshot.tags.by_subject.values():
        tag = tags.get("contract.closing_date")
        if tag is None or str(tag.value) == _UNKNOWN:
            continue
        raw = str(tag.value)
        parsed = coerce_date(raw)
        if parsed is not None:
            dates[parsed] = raw
    if not dates:
        return _UNKNOWN, "no (parseable) closing date is stated in the file"
    if len(dates) > 1:
        return _UNKNOWN, (
            f"the file's documents disagree on the closing date "
            f"({', '.join(sorted(dates.values()))}) — ambiguous"
        )
    closing = next(iter(dates))
    days = (closing - snapshot.created_at.date()).days
    return (
        str(days),
        f"the closing date {closing.isoformat()} is {days} day(s) from the file date "
        f"({'future' if days >= 0 else 'past'})",
    )


# --------------------------------------------------------------------------- #
# LP-485 — the date-compare family (CL-1 / CR-13 / PR-6).
#
# All three mirror _contract_days_until_closing: gather ONE date across subjects, dedup by the PARSED date
# (one date rendered two ways is one value), abstain to _UNKNOWN when none parse AND when documents
# DISAGREE, and emit ONLY the number. ⚠️ The tag is DESCRIPTIVE — the acceptable window belongs to the
# RULE (its reference_values), never to the tag. A tag carrying a threshold is a rule in disguise.
# --------------------------------------------------------------------------- #


def _parsed_dates(snapshot: Snapshot, tag_id: str) -> dict[date, str]:
    """Every distinct parseable value of ``tag_id`` across the file's subjects, as {date: raw}."""
    if snapshot.tags.absent:
        return {}
    dates: dict[date, str] = {}
    for tags in snapshot.tags.by_subject.values():
        tag = tags.get(tag_id)
        if tag is None or str(tag.value) == _UNKNOWN:
            continue
        parsed = coerce_date(str(tag.value))
        if parsed is not None:
            dates[parsed] = str(tag.value)
    return dates


def _single_parsed_date(snapshot: Snapshot, tag_id: str) -> tuple[date | None, str | None]:
    """The file's ONE parseable value of ``tag_id`` as a date, or ``(None, reason)``.

    ⚠️ ABSTAIN-ON-DISAGREEMENT. Correct only for a tag that states ONE FACT many times — ``contract
    .closing_date`` is the case it was written for: every document restates the same closing, so two
    distinct values mean the file genuinely contradicts itself and there is no answer to pick.

    It is WRONG for a per-document date on a type that legitimately recurs — see
    :func:`_most_recent_parsed_date` and :func:`_earliest_parsed_date`, which those use instead.
    """
    dates = _parsed_dates(snapshot, tag_id)
    if not dates:
        return None, "not stated (or not parseable) anywhere in the file"
    if len(dates) > 1:
        return (
            None,
            f"the file's documents disagree ({', '.join(sorted(dates.values()))}) — ambiguous",
        )
    return next(iter(dates)), None


# ⚠️ THE DATE-SELECTION POLICY IS PER TAG, NOT PER FAMILY (a reported regression, corrected here).
#
# A per-document date tag can appear several times on one file, and the right pick differs by tag. An
# earlier fix replaced abstain-on-disagreement with most-recent-wins for ALL THREE date tags on the
# grounds that "a re-pull, a re-issued LE and a 1004D are all second documents". That reasoning holds for
# exactly one of them and introduced a false-satisfied in the other two:
#
#   credit.report_date        max()  — the GUIDELINE says so. B1-1-03 ages credit documents from the MOST
#                                      RECENT pull, so a fresh pull genuinely resets the clock.
#   property.appraisal_date   min()  — B4-1.2-04 measures BOTH bands (4-month update, 12-month new
#                                      appraisal) from the ORIGINAL effective date; a Form 1004D update
#                                      does NOT restart it. And the classifier has ONE `appraisal` type,
#                                      so a 1004D is indistinguishable from a replacement report — max()
#                                      let an update reset the 12-month clock and turned PR-6's
#                                      "a NEW appraisal is required" band into `satisfied`, contradicting
#                                      PR-6's own spec text.
#   rate_lock.expiration      min()  — the value is an EXPIRY, not a document date, so max() means "the
#                                      most permissive expiry anywhere in the file". A superseded LE
#                                      locked through September masks a re-lock that expired in July.
#
# The rule where the guideline is silent: take the CONSERVATIVE date — the one that makes the rule MORE
# likely to flag. Both bars call the false-negative the costly direction (a stale appraisal / a lapsed
# lock closes the loan; the false positive is a processor checking one date).
def _most_recent_parsed_date(snapshot: Snapshot, tag_id: str) -> tuple[date | None, str | None]:
    """The LATEST parseable value of ``tag_id``, or ``(None, reason)`` when none parses.

    Correct ONLY where a newer document genuinely supersedes its predecessor for the question being
    asked — today that is ``credit.report_date`` alone (B1-1-03 ages from the most recent pull). See the
    policy note above before pointing a new tag at this.
    """
    dates = _parsed_dates(snapshot, tag_id)
    if not dates:
        return None, "not stated (or not parseable) anywhere in the file"
    return max(dates), None


def _earliest_parsed_date(snapshot: Snapshot, tag_id: str) -> tuple[date | None, str | None]:
    """The EARLIEST parseable value of ``tag_id``, or ``(None, reason)`` when none parses.

    The conservative pick, for a tag whose duplicates cannot be ranked by supersession from the snapshot
    alone (see the policy note above): the oldest appraisal effective date, the soonest lock expiry.

    ⚠️ It trades a known false-positive for an unacceptable false-negative, deliberately. A file carrying
    a genuinely REPLACED appraisal (a second full report, not a 1004D) ages from the superseded one and
    may flag when it need not — a processor confirms which report governs. The alternative is closing a
    loan on a fifteen-month-old value because an update reset the clock. Given PR-6/CL-1's stated
    FN >> FP asymmetry, flagging is the safe error.
    """
    dates = _parsed_dates(snapshot, tag_id)
    if not dates:
        return None, "not stated (or not parseable) anywhere in the file"
    return min(dates), None


def _shift_months(anchor: date, months: int) -> date:
    """``anchor`` shifted by ``months`` calendar months, clamped to the target month's last day."""
    total = (anchor.year * 12 + anchor.month - 1) + months
    year, month = divmod(total, 12)
    month += 1
    if month == 12:
        last = 31
    else:
        last = (date(year + (month // 12), (month % 12) + 1, 1) - timedelta(days=1)).day
    return date(year, month, min(anchor.day, last))


def _completed_months(earlier: date, later: date) -> int:
    """COMPLETE calendar months from ``earlier`` to ``later`` — a partial month does NOT count.

    ⚠️ THE COUNTERPART TO :func:`_age_months_ceiling`, AND THE DIRECTION MATTERS MORE THAN THE NAME.
    Rounding is not a stylistic choice here; it decides which way the rule fails:

    * AGEING a document (CR-13, PR-6) — a bigger number makes the rule MORE likely to fire, so rounding
      UP is the conservative side. That is :func:`_age_months_ceiling`.
    * SEASONING an event (CR-6) — a bigger number makes the rule more likely to CLEAR the borrower, so
      rounding up is the PERMISSIVE side. A bankruptcy discharged 47 months and 1 day before closing
      ceilings to 48 and satisfies a 48-month waiting period ~29 days early. Seasoning uses THIS.

    Reach for the one whose rounding closes the costly direction for the rule you are writing.
    """
    months = (later.year - earlier.year) * 12 + (later.month - earlier.month)
    if later.day < earlier.day:
        months -= 1
    return months


def _age_months_ceiling(earlier: date, later: date) -> int:
    """Calendar months from ``earlier`` to ``later``, ROUNDED UP on any partial month.

    ⚠️ CALENDAR MONTHS, NOT A DAY COUNT. Fannie's B1-1-03 / B4-1.2-04 windows are stated in months, and a
    30-day approximation differs from the calendar by up to three days at four months.

    ⚠️ AND IT ROUNDS UP — the reported finding. The previous version floored to COMPLETE months while
    CR-13/PR-6 compare with strict ``>``, so ``floor(age) > 4`` only fired at five complete months and a
    document up to a full month past its window passed: a credit report pulled 2026-03-02 against a
    2026-08-01 closing is **152 days** old — 4 months 30 days — and floored to ``4``, clearing a four-month
    limit. Measured, not argued. That is the catastrophic FN the bar names (a stale report closes the
    loan), and it dwarfed the 3-day calendar-vs-day-count drift the floor was chosen to avoid.

    Rounding up makes "is it OVER four months" true the moment it is, while an exact four months
    (04-01 → 08-01) still returns ``4`` and passes — the guides' "no more than four months" is inclusive.

    It also fixes the month-end case: 01-31 → 02-28 is a full elapsed month and floored to ``0``.

    Negative when ``later`` precedes ``earlier`` (the caller decides what that means — see
    :func:`_age_in_months_at_closing`, which refuses to age a document dated after closing).

    ⚠️ FOR AGEING A DOCUMENT ONLY. Rounding up is conservative when a bigger number makes the rule
    MORE likely to fire. For SEASONING — where a bigger number CLEARS the borrower — it is the
    permissive direction and clears an event early; use :func:`_completed_months` there.
    """
    months = (later.year - earlier.year) * 12 + (later.month - earlier.month)
    if later.day < earlier.day:
        months -= 1
    if months >= 0 and _shift_months(earlier, months) < later:
        months += 1  # a partial month remains — round up
    return months


def _age_in_months_at_closing(
    snapshot: Snapshot,
    document_date_tag: str,
    label: str,
    *,
    pick: Callable[[Snapshot, str], tuple[date | None, str | None]],
) -> tuple[JsonValue, str]:
    """Shared body for CR-13 / PR-6: COMPLETE calendar months from a document's date to the closing date.

    ⚠️ THE OPERAND SUBSTITUTION, stated where it happens: the guideline measures to the **note date**; the
    snapshot carries only ``contract.closing_date``. They are usually the same day and not always. Recorded
    as an explicit assumption in docs/tickets/LP-485.md rather than silently treated as identical.

    Fail-closed: either date absent, unparseable, or disagreed-upon → ``unknown`` (never 0, never a default).

    ⚠️ ``pick`` is the caller's DATE-SELECTION POLICY and is deliberately explicit — see the policy note
    above :func:`_most_recent_parsed_date`. Credit ages from the newest pull; an appraisal ages from the
    ORIGINAL effective date. Defaulting either way silently is how the 1004D regression happened.
    The CLOSING date stays abstain-on-disagreement: that is one fact restated, so a contradiction is real.
    """
    doc_date, why = pick(snapshot, document_date_tag)
    if doc_date is None:
        return _UNKNOWN, f"the {label} date is {why}"
    closing, why_closing = _single_parsed_date(snapshot, "contract.closing_date")
    if closing is None:
        return _UNKNOWN, f"the closing date is {why_closing} — cannot age the {label}"
    if doc_date > closing:
        # ⚠️ Reported finding: a negative age matched no `>` outcome and fell through to the DEFAULT
        # `satisfied`, rendering "-3 complete calendar month(s) before closing" as a clean pass. A document
        # dated after closing is a mis-parse, a transposition, or a stale closing date — never a fact to
        # certify. Every other path in this family fails closed; so does this one now.
        return _UNKNOWN, (
            f"the {label} date {doc_date.isoformat()} is AFTER the closing date "
            f"{closing.isoformat()} — the dates are inconsistent, so the age cannot be trusted"
        )
    months = _age_months_ceiling(doc_date, closing)
    return (
        str(months),
        f"the {label} dated {doc_date.isoformat()} is {months} calendar month(s) old at the "
        f"closing date {closing.isoformat()} (a partial month counts as a full one)",
    )


def _credit_report_age_months(
    snapshot: Snapshot, _subject_id: str, _subject_raw: object
) -> tuple[JsonValue, str]:
    """credit.report_age_months_at_closing — calendar months from the credit pull to closing (CR-13).

    MOST RECENT pull: B1-1-03 ages the credit documents from the newest report, so a re-pull resets it.
    """
    return _age_in_months_at_closing(
        snapshot, "credit.report_date", "credit report", pick=_most_recent_parsed_date
    )


def _appraisal_age_months(
    snapshot: Snapshot, _subject_id: str, _subject_raw: object
) -> tuple[JsonValue, str]:
    """property.appraisal_age_months_at_closing — calendar months from the appraisal's EFFECTIVE date to
    closing (PR-6). B4-1.2-04 measures from the effective date, not the report/signature date.

    ⚠️ EARLIEST effective date. Both of PR-6's bands run from the ORIGINAL appraisal — a Form 1004D update
    does not restart the twelve-month clock, and the classifier cannot tell an update from a replacement
    (one `appraisal` type). Taking the newest let an update reset the clock and reported a fifteen-month-old
    value as `satisfied`.
    """
    return _age_in_months_at_closing(
        snapshot, "property.appraisal_date", "appraisal", pick=_earliest_parsed_date
    )


def _rate_lock_days_to_closing(
    snapshot: Snapshot, _subject_id: str, _subject_raw: object
) -> tuple[JsonValue, str]:
    """rate_lock.days_to_closing — SIGNED days from the closing date to the rate lock's expiration (CL-1).

    POSITIVE = the lock still has room at closing; NEGATIVE = it expires BEFORE closing (CL-1 fires).
    A day count is correct here (unlike the month-stated guideline windows): a lock expires on a date, and
    the question is simply which date comes first. Fail-closed to unknown on either side.
    """
    # ⚠️ SOONEST expiry, not the latest. This tag's value is an EXPIRY, not a document date, so "latest"
    # means "the most permissive lock anywhere in the file" — a superseded loan estimate locked through
    # September would mask a re-lock that expired in July, and CL-1 would pass an expired lock.
    expiry, why = _earliest_parsed_date(snapshot, "rate_lock.expiration")
    if expiry is None:
        return _UNKNOWN, f"the rate lock expiration is {why}"
    closing, why_closing = _single_parsed_date(snapshot, "contract.closing_date")
    if closing is None:
        return (
            _UNKNOWN,
            f"the closing date is {why_closing} — cannot compare it to the lock expiration",
        )
    days = (expiry - closing).days
    return (
        str(days),
        # `days` is SIGNED, so the sentence must not ALSO say before/after — "-14 day(s) BEFORE closing"
        # is the double negative the CL-1 spec was corrected for; this string is processor-visible too
        # (CL-1's evidence_required asks for the signed number inline on the finding).
        f"the rate lock expires {expiry.isoformat()}; lock-to-closing margin {days} day(s) "
        f"against the closing date {closing.isoformat()} (negative = the lock lapses first)",
    )


# --------------------------------------------------------------------------- #
# LP-486 / ADR-376 — the CLOSED-VOCABULARY ABSTAIN pattern, for CR-12 (disputed accounts).
#
# ⚠️ WHY THIS EXISTS. `is_disputed` carries a CLEAN Y/N on the two bench credit reports (34 N, 1 Y across
# 35 rows) and FREE TEXT on LF-96SV — a different bureau format — where the same field holds
# "ACCOUNT IN FORBEARANCE", "ACCOUNT CLOSED BY CREDIT GRANTOR" and
# "ACCOUNT PREVIOUSLY IN DISPUTE-NOW RESOLVED-REPORTED BY SUBSCRIBER". ONE FIELD, TWO ENCODINGS.
#
# A rule written as `is_disputed == "Y"` would read the free-text report as NOT disputed — a silent false
# negative on a fraud-adjacent rule that ships `auto`. So the recipe recognises a CLOSED SET and ABSTAINS
# on anything else. It NEVER classifies open vocabulary, never stems, never fuzzy-matches, never infers.
#
# ⚠️ "PREVIOUSLY IN DISPUTE-NOW RESOLVED" is deliberately NOT in either list: it is unrecognised, so it
# abstains. Reading it as "not disputed" would be an inference the bureau did not state.
#
# The vocabulary is DOMAIN DATA and is mirrored in CR-12's spec reference_values, where Priya edits it;
# test_cr12_vocabulary_matches_the_spec pins the two identical so they cannot drift.
# --------------------------------------------------------------------------- #
_DISPUTE_PHRASES: frozenset[str] = frozenset(
    {
        "y",
        "yes",
        "account disputed by consumer",
        "consumer disputes this account",
        "dispute in progress",
        "account information disputed by consumer",
        "consumer disputes account information",
    }
)
_NOT_DISPUTE_PHRASES: frozenset[str] = frozenset(
    {
        "n",
        "no",
        "account in forbearance",
        "account closed by credit grantor",
        "paid account",
        "transferred",
        "account closed",
        "deferred",
    }
)
_WS = re.compile(r"\s+")


def _normalise_vocab(raw: str) -> str:
    """Case-fold + collapse whitespace. The ONLY normalisation applied — no stemming, no fuzzy match."""
    return _WS.sub(" ", raw).strip().casefold()


# --------------------------------------------------------------------------------------------- #
# LP-556 — liab.creditor_name: which debt a per-liability finding is about
# --------------------------------------------------------------------------------------------- #
# Four active rules enumerate per_liability (CR-1, CR-6, CR-8, CR-12) and every one of their findings
# reads "a debt on this file", because the label layer has no name to use. On the real file CR-6 shipped
# FOUR identical rows — a processor could not tell which account each was about, or that they were four
# different accounts rather than one repeated.
#
# The AS-12 fix (LP-554/555) is the precedent: an identifying value the finding carries INLINE, as
# provenance, so the read path needs no snapshot. `liab.is_disputed` proves the shape for this subject.
#
# SCRUBBED, NOT RAW. A bureau prints an account number inside the creditor field often enough that
# the liability CONTEXT builder routes every list value through `_scrub_list_value` for exactly this
# reason. A tag whose whole purpose is to be RENDERED to a processor must not be the one place that
# skips it.
_CREDITOR_NAME_MAX = 60  # a label, not a paragraph — a bureau string can run long


def liability_creditor_name(
    _snapshot: Snapshot, _subject_id: str, subject_raw: object
) -> tuple[JsonValue, str]:
    """liab.creditor_name — the account holder this liability names, for the finding's subject label.

    Resolved through the CANONICAL alias map, never a raw column: a tradeline calls it `creditor_name`
    and a MISMO stated liability calls it `holder_name`, and reading either directly would abstain on
    half the subjects (the ADR-376 lesson `liab.is_disputed` records).
    """
    # LAZY, for the same init-order reason `liab.is_disputed` imports LiabilityRow lazily.
    from app.verification.rule_engine.enumerators import LiabilityRow
    from app.verification.tag_materialization.subjects import _scrub_list_value

    if not isinstance(subject_raw, LiabilityRow):
        return _UNKNOWN, "not a liability subject"
    field = subject_type("liability").read_field(subject_raw, "creditor_name")
    if field is None or not field.is_present:
        return _UNKNOWN, "this liability names no holder"
    value = field.display if isinstance(field, PiiField) else field.value
    if value is None or not str(value).strip():
        return _UNKNOWN, "this liability names no holder"
    scrubbed = str(_scrub_list_value(str(value))).strip()
    if not scrubbed:
        return _UNKNOWN, "this liability's holder resolved to nothing once scrubbed"
    return scrubbed[:_CREDITOR_NAME_MAX], f"the account is held by {scrubbed[:_CREDITOR_NAME_MAX]}"


# --------------------------------------------------------------------------- #
# LP-573 — THE REFINANCED-LIEN DOUBLE COUNT (DT-8).
#
# DTI is forward-looking: it measures what is owed AFTER the loan funds. On a refinance the mortgage
# being replaced is paid off at closing, so counting its payment ALONGSIDE the new housing payment
# charges the same property twice. LF-WCHG read a back-end DTI of 58.59% for exactly this reason;
# the figure worked by hand with the domain expert is 34.39%.
#
# These two tags DESCRIBE; DT-8 judges. Neither decides whether a given mortgage is the one being
# refinanced — that is the question the rule hands to a processor, because getting it wrong in the
# permissive direction removes a real obligation from the ratio and can pass a loan that should fail.
# --------------------------------------------------------------------------- #


def _liability_stated_is_mortgage(
    _snapshot: Snapshot, _subject_id: str, subject_raw: object
) -> tuple[JsonValue | None, str]:
    """liab.stated_is_mortgage — is this stated liability a mortgage, per the application itself?

    Reads MISMO's own ``LiabilityType`` and compares it to one value. This is NOT the open-vocabulary
    classification ADR-353 defers: nothing here maps a bureau's ``MTG`` / ``REV`` onto a vocabulary
    term. It DECLINES on a credit-report tradeline for precisely that reason — deciding what ``MTG``
    means is the judgment `liab.account_type` has no parsed producer for.
    """
    # LAZY import (init-order: rule_engine <-> tag_materialization, as the recipes above do).
    from app.verification.rule_engine.enumerators import _SOURCE_MISMO, LiabilityRow

    if not isinstance(subject_raw, LiabilityRow):
        return None, "not a liability subject"
    if subject_raw.source != _SOURCE_MISMO:
        return None, "not a stated liability — a reported tradeline's type is not read here"
    field = subject_type("liability").read_field(subject_raw, "account_type")
    if field is None or not field.is_present:
        return _UNKNOWN, "the application states no type for this liability"
    # A PiiField here would mean the column had been PII-routed; neither a liability TYPE nor a
    # payoff marking is, so read the display form rather than assume a `.value` exists.
    raw = field.display if isinstance(field, PiiField) else field.value
    value = str(raw or "").strip()
    if not value:
        return _UNKNOWN, "the application states no type for this liability"
    # Exact, case-insensitive, against MISMO's own enumeration. An unrecognised type is "no" rather
    # than unknown ONLY because the question is "is it MortgageLoan", which a different value answers.
    is_mortgage = value.casefold() == "mortgageloan"
    return (
        ("yes" if is_mortgage else "no"),
        f"the application states this liability's type as {value}",
    )


def _liability_payoff_marked(
    _snapshot: Snapshot, _subject_id: str, subject_raw: object
) -> tuple[JsonValue | None, str]:
    """liab.payoff_marked — has this obligation been MARKED as retired at closing? (LP-568)

    A fact about the MARKING, not about the world — which is why an absent flag is "no" rather than
    "unknown" and that is not a §8 violation. The question is "has anyone said so", and nobody
    having said so is a definite no. Whether the obligation actually survives closing is the
    question DT-8 asks; this tag only reports whether it has already been answered.
    """
    from app.verification.rule_engine.enumerators import _SOURCE_MISMO, LiabilityRow

    if not isinstance(subject_raw, LiabilityRow):
        return None, "not a liability subject"
    if subject_raw.source != _SOURCE_MISMO:
        return None, "a reported tradeline carries no payoff marking"
    field = subject_type("liability").read_field(subject_raw, "paid_off_at_closing")
    if field is None or not field.is_present:
        return "no", "no one has marked this obligation as paid off at closing"
    raw = field.display if isinstance(field, PiiField) else field.value
    marked = str(raw or "").strip().casefold() == "true"
    return (
        ("yes" if marked else "no"),
        (
            "this obligation is marked paid off at closing"
            if marked
            else "no one has marked this obligation as paid off at closing"
        ),
    )


def _liability_payoff_contradicted(
    snapshot: Snapshot, _subject_id: str, subject_raw: object
) -> tuple[JsonValue | None, str]:
    """liab.payoff_contradicted — does the application contradict its own payoff marking? (LP-597)

    DT-8's satisfied branch rests entirely on ``liab.payoff_marked``, whose own docstring says it is
    "a fact about the MARKING, not about the world". That is defensible — an application is
    authoritative about the borrower's own intent — but it is unguarded: an LO who ticks payoff on a
    mortgage secured by a property the borrower KEEPS removes that payment from the ratio, and nothing
    asks. DT-8's guideline text says so in words: "A mortgage secured by other property the borrower
    retains remains an obligation and stays in the ratio."

    This is the cheapest possible guard and it needs NO threshold: LP-596 put the 1003's
    real-estate-owned schedule in the snapshot, and that schedule says, per property, whether the
    borrower is retaining it. A lien marked paid off whose property is marked ``Retain`` is the
    application disagreeing with itself. That is not a judgment call about plausibility — it is two
    sections of one form saying opposite things, which is exactly what a processor should look at.

    Matched by BALANCE, which is what joins the two sections: in the real export the five
    ``OwnedPropertyLienUPBAmount`` values equal the five ``LiabilityUnpaidBalanceAmount`` values
    exactly. No match means no contradiction was established — "no", never a guess, and never a
    reason to disturb a file whose export simply omits the schedule.
    """
    from app.verification.rule_engine.enumerators import _SOURCE_MISMO, LiabilityRow

    if not isinstance(subject_raw, LiabilityRow):
        return None, "not a liability subject"
    if subject_raw.source != _SOURCE_MISMO:
        return None, "a reported tradeline is not on the application's owned-property schedule"

    # `balance` is the CANONICAL name — MISMO's `unpaid_balance` and a tradeline's `balance` both
    # resolve through it (subjects.py's alias map). Reading the MISMO spelling here would silently
    # return None on every liability, which is exactly what it did on the first run of this code.
    field = subject_type("liability").read_field(subject_raw, "balance")
    if field is None or not field.is_present:
        return "no", "this liability states no balance to match against the schedule"
    raw = field.display if isinstance(field, PiiField) else field.value
    balance = _to_decimal_or_none(str(raw or "").strip())
    if balance is None:
        return "no", "this liability's balance could not be read"

    for row in _owned_property_rows(snapshot):
        if _to_decimal_or_none(row.get("lien_upb")) != balance:
            continue
        if row.get("is_subject", "").strip().lower() == "true":
            # The schedule says this IS the subject property, which corroborates the payoff.
            return "no", "the schedule identifies this as the lien on the subject property"
        if row.get("disposition_status", "").strip().lower() == _RETAINED_DISPOSITION:
            if not _schedule_marks_a_subject(snapshot):
                # This row may BE the subject — the schedule never says. A borrower refinancing
                # their home retains it while the lien is retired, so without knowing which property
                # this loan is against, "Retain" says nothing about whether the lien survives.
                return (
                    "no",
                    "the schedule does not identify which property this loan is against, so a "
                    "retained property is not evidence that this lien survives closing",
                )
            return (
                "yes",
                "the owned-property schedule marks the property securing this lien as retained, "
                "while the liability is marked paid off at closing",
            )
        return "no", "the schedule shows this property is not being retained"
    return "no", "no owned property on the schedule matches this lien's balance"


def _liability_dispute_status(
    _snapshot: Snapshot, _subject_id: str, subject_raw: object
) -> tuple[JsonValue, str]:
    """liab.is_disputed — is THIS tradeline flagged as disputed by the consumer? (CR-12, ADR-376)

    Recognises a CLOSED vocabulary and abstains on everything else. ⚠️ An unrecognised value is
    ``unknown``, NOT "no": the encoding varies by bureau, and inferring from unfamiliar text is exactly how
    a dispute gets missed. Absent field → ``unknown`` too (absent ≠ not disputed).
    """
    # LAZY import (init-order — rule_engine ↔ tag_materialization, as _stmt_min_account_months does).
    from app.verification.rule_engine.enumerators import LiabilityRow

    if not isinstance(subject_raw, LiabilityRow):
        return _UNKNOWN, "not a liability subject"
    # ⚠️ Resolve the CANONICAL name through the liability alias map, never the raw column. The alias map
    # is the documented place a ListSpec rename is absorbed; hard-coding the column meant a rename would
    # keep every other liability reader working while this recipe abstained on every tradeline on every
    # file — the silent false-negative ADR-376 exists to prevent, and one the tests could not catch
    # because their fixtures build the field under the literal name.
    field = subject_type("liability").read_field(subject_raw, "is_disputed")
    if field is None or not field.is_present:
        return _UNKNOWN, "this tradeline states no dispute flag"
    # A list-row field is a plain Field, never a PiiField (model.py) — but the union is what the type says,
    # so read the display for a PiiField rather than assuming. An empty value abstains like an absent one.
    value = field.display if isinstance(field, PiiField) else field.value
    if value is None or str(value).strip() == "":
        return _UNKNOWN, "this tradeline states no dispute flag"
    raw = str(value)
    normalised = _normalise_vocab(raw)
    if normalised in _DISPUTE_PHRASES:
        return "yes", f"the credit report flags this tradeline as disputed ({raw!r})"
    if normalised in _NOT_DISPUTE_PHRASES:
        return "no", f"the credit report states no dispute on this tradeline ({raw!r})"
    return _UNKNOWN, (
        f"the dispute field reads {raw!r}, which is not a recognised dispute or account-status value — "
        "abstaining rather than inferring (the encoding varies by bureau)"
    )


# --------------------------------------------------------------------------- #
# LP-488 — MI-1's LTV. ⚠️ THE ARITHMETIC IS NOT REIMPLEMENTED HERE. app/verification/ltv.py already owns
# it (LP-77) as pure functions, with the two subtleties baked in: a PURCHASE divides by the LESSER OF
# purchase price and appraised value, a REFINANCE by the appraised value alone. This recipe resolves the
# inputs from the snapshot and calls that module, so the rule path and the display path can never drift
# into two different LTVs for one file.
#
# ⚠️ THESE TAGS DESCRIBE, THEY DO NOT JUDGE. `mi.required` exists in fact_tags.csv as an enum "Is MI
# required (LTV>80 conv)" — and it is deliberately left INERT, because materialising it would put the 80%
# threshold inside a PRODUCER. The threshold belongs to MI-1's reference_values, where it is reviewable
# and citable; the tag emits the number and the rule judges it.
# --------------------------------------------------------------------------- #


def _parsed_decimals(snapshot: Snapshot, tag_id: str) -> list[Decimal]:
    """Every parseable value of a numeric tag across the file's subjects."""
    out: list[Decimal] = []
    for raw in _parsed_strings(snapshot, tag_id):
        try:
            out.append(Decimal(raw.replace(",", "").replace("$", "").strip()))
        except (InvalidOperation, ValueError):
            continue
    return out


def _first_loan_decimal(snapshot: Snapshot, tag_id: str) -> Decimal | None:
    """The parseable value of a LOAN-SCOPED numeric tag, or None.

    ⚠️ Correct only for a tag materialised on the loan subject, where there is exactly one — the MISMO
    facts (``loan.amount``, ``loan.note_amount``, ``property.purchase_price``). A PER-DOCUMENT numeric
    tag can appear many times on one file and the right pick is a policy decision, NOT "whichever subject
    iterated first" — see :func:`_conservative_appraised_value`.
    """
    values = _parsed_decimals(snapshot, tag_id)
    return values[0] if values else None


def _appraised_value_from_appraisal(snapshot: Snapshot) -> Decimal | None:
    """The LOWEST value stated by an APPRAISAL DOCUMENT, or None. No stated-value fallback.

    ⚠️ THE STRICT VARIANT, and the one a rule about the appraisal must use. ``property.appraised_value``
    is document-scoped to `appraisal`, so None here means exactly "no appraisal on this file states a
    value" — which is what a rule like PR-2 needs to hear in order to abstain.
    :func:`_conservative_appraised_value` adds a MISMO stated-value fallback for the LTV consumers, and
    that fallback silently turned PR-2's abstain into a false all-clear.

    Lowest-not-first for the same reason as its caller: a file may carry an original plus a replacement
    appraisal, and taking whichever iterated first is an arbitrary answer on an ordinary file shape.
    """
    values = [v for v in _parsed_decimals(snapshot, "property.appraised_value") if v > 0]
    return min(values) if values else None


def _conservative_appraised_value(snapshot: Snapshot) -> Decimal | None:
    """The LOWEST appraised value on the file, or None.

    ⚠️ THE LOWEST, NOT THE FIRST — a reported defect of the same shape as the LP-487 review findings.
    ``property.appraised_value`` is PER APPRAISAL DOCUMENT, so a file carrying two appraisals (an
    original plus a replacement, or a 1004D the classifier cannot distinguish from a full report) used to
    get whichever subject happened to iterate first: an arbitrary LTV denominator on a real, ordinary
    file shape.

    The pick follows the policy LP-485 already set for this document family: where the guideline is
    silent, take the CONSERVATIVE value — the one that makes the rule MORE likely to flag. A lower
    appraised value means a HIGHER loan-to-value, so the lowest appraisal is the one that keeps MI-1's
    costly direction closed. MI-1's own bar names the false-negative (an MI requirement silently cleared)
    as the expensive error; a processor confirming which appraisal governs is the cheap one.
    """
    appraised = _appraised_value_from_appraisal(snapshot)
    if appraised is not None:
        return appraised
    # ⚠️ FALL BACK TO THE WORKSHEET'S OWN FIELDS. The "the rule path and the display path cannot drift
    # into two different LTVs" claim covered only the ARITHMETIC: the worksheet takes `valuation_amount
    # or estimated_value` off the property record, this took the appraisal DOCUMENT's value, so a
    # MISMO-imported file with a valuation and no appraisal PDF showed a real LTV on the worksheet and
    # couldnt_check on the rule. Same fields, same priority, so the two agree on input.
    #
    # ⚠️ AND THE FALLBACK IS WHY THIS FUNCTION IS NOT THE DEFAULT (reported finding). A MISMO-stated
    # value is the BORROWER'S estimate, not an appraisal. That is the right input for an LTV consumer,
    # which needs a denominator; it is the WRONG input for any rule whose question is "what did the
    # appraisal say", because the estimate usually EQUALS the price on a MISMO import — so a file with no
    # appraisal at all produced a gap of zero and PR-2 answered "the appraised value supports the
    # purchase price". Ask for :func:`_appraised_value_from_appraisal` unless you specifically want the
    # worksheet's basis.
    for tag_id in ("property.valuation_amount", "property.estimated_value"):
        stated = [v for v in _parsed_decimals(snapshot, tag_id) if v > 0]
        if stated:
            return min(stated)
    return None


def _loan_ltv_basis_is_appraised(
    snapshot: Snapshot, _subject_id: str, _subject_raw: object
) -> tuple[JsonValue, str]:
    """loan.ltv_basis_is_appraised — is the LTV denominator an APPRAISAL, or the application's estimate?

    ``_conservative_appraised_value`` deliberately falls back to ``property.valuation_amount`` /
    ``property.estimated_value`` so the worksheet always has a denominator, and its own comment states
    the hazard this tag exists to expose: "A MISMO-stated value is the BORROWER'S estimate, not an
    appraisal ... the WRONG input for any rule whose question is 'what did the appraisal say'."

    MI-1's `satisfied` branch is such a question in all but name. Fannie B2-1.2-01: "For refinance
    transactions ... the property value is the current appraised value." So declaring that no mortgage
    insurance is required because the LTV is 79% asserts a ratio the guideline says must rest on an
    appraisal, off a number the borrower supplied. If the appraisal lands lower, the loan crosses 80%
    and MI IS required — a real monthly cost, cleared before the evidence arrived.

    Only the CLEARING direction needs this. A stated value that ALREADY exceeds the threshold is if
    anything optimistic, so MI-1's needs_review branch is safe without it.
    """
    if _appraised_value_from_appraisal(snapshot) is not None:
        return "yes", "an appraisal on the file supplies the value the ratio divides by"
    # ⚠️ THE PURCHASE PRICE IS ONE OF THESE, and leaving it out made this guard INERT on every
    # purchase. `value_basis` divides a purchase by the LESSER of price and appraised value, so a
    # purchase stating a price and carrying no appraisal produces a perfectly good `loan.ltv_percent`
    # — while this returned "unknown", MI-1's `eq "no"` never matched, and MI-1 went on clearing the
    # insurance requirement at 79% off a sales price. That is the exact failure the guard was written
    # for, arriving from the other direction.
    #
    # A sales price is no more an appraisal than the borrower's estimate is: B2-1.2-01 puts the
    # appraised value in the denominator, and a price is what the parties agreed, not what the
    # property is worth.
    for tag_id in (
        "property.valuation_amount",
        "property.estimated_value",
        "property.purchase_price",
    ):
        if [v for v in _parsed_decimals(snapshot, tag_id) if v > 0]:
            return (
                "no",
                "the ratio divides by a value the application states, not by an appraisal",
            )
    return _UNKNOWN, "the file states no value to divide by at all"


def _ltv_purpose(snapshot: Snapshot) -> LtvPurpose:
    """The LTV purpose from the loan's stated purpose + refinance type.

    Mirrors ``app.services.ltv.ltv_purpose_for``, which takes a LoanFile ORM row this recipe does not
    have. Defaults to PURCHASE, exactly as that function does.
    """
    purposes = {v.casefold() for v in _parsed_strings(snapshot, "loan.purpose")}
    if "refinance" not in purposes:
        return LtvPurpose.PURCHASE
    kinds = {v.casefold() for v in _parsed_strings(snapshot, "loan.refinance_type")}
    if "cash_out" in kinds:
        return LtvPurpose.CASH_OUT_REFINANCE
    return LtvPurpose.RATE_TERM_REFINANCE


def _property_value_basis(
    snapshot: Snapshot, _subject_id: str, _subject_raw: object
) -> tuple[JsonValue, str]:
    """property.value_basis — the LTV denominator (LP-488), via app.verification.ltv.value_basis.

    Purchase → the lesser of purchase price and appraised value (whichever are present). Refinance →
    the appraised value. "unknown" when neither forms a positive basis — never 0.
    """
    purpose = _ltv_purpose(snapshot)
    price = _first_loan_decimal(snapshot, "property.purchase_price")
    appraised = _conservative_appraised_value(snapshot)
    basis, label = value_basis(purpose, price, appraised)
    if basis is None:
        return _UNKNOWN, (
            f"the file states no {label} to divide by, so no loan-to-value can be computed"
        )
    return str(basis), f"the value basis is {basis} (the {label})"


def _loan_ltv_percent(
    snapshot: Snapshot, _subject_id: str, _subject_raw: object
) -> tuple[JsonValue, str]:
    """loan.ltv_percent — base loan amount over the value basis, as a percent (LP-488).

    ⚠️ Reads the BASE loan amount (loan.amount = MISMO BaseLoanAmount), NOT the note amount. On an FHA
    file the note amount includes financed upfront MIP, so dividing by it would overstate the LTV and
    could push a conventional-equivalent file over the 80% line for the wrong reason. (MI-4 reads the
    difference between the two deliberately; MI-1 must not.)
    """
    first = _first_loan_decimal(snapshot, "loan.amount")
    if first is None or first <= 0:
        return _UNKNOWN, "the file states no base loan amount"
    purpose = _ltv_purpose(snapshot)
    result = compute_ltv(
        LtvInputs(
            first_loan=first,
            second_loan=Decimal(0),
            heloc_drawn=Decimal(0),
            heloc_limit=Decimal(0),
            purchase_price=_first_loan_decimal(snapshot, "property.purchase_price"),
            appraised_value=_conservative_appraised_value(snapshot),
        ),
        purpose,
    )
    if result.ltv_pct is None or result.ltv_pct_delivered is None:
        return _UNKNOWN, (
            f"the file states no {result.value_basis_label} to divide by, so no loan-to-value can be "
            "computed"
        )
    # LP-496 — THE TAG CARRIES THE DELIVERED WHOLE PERCENT (B2-1.2-01), because its consumer is an
    # ELIGIBILITY threshold: MI-1 asks "is the LTV above 80%?", which is the Fannie question the
    # delivered ratio is defined for. The EXACT figure rides the reasoning so a processor can still tell
    # 80.01% from 80.99% — a bare "81%" on the finding would make the verdict uncheckable.
    exact = f"{result.ltv_pct}%"
    delivered = f"{result.ltv_pct_delivered}%"
    shown = (
        exact
        if result.ltv_pct == result.ltv_pct_delivered
        else f"{exact} (delivered as {delivered})"
    )
    return str(result.ltv_pct_delivered), (
        f"the loan-to-value is {shown} "
        f"({first} over the {result.value_basis_label} of {result.value_basis})"
    )


# --------------------------------------------------------------------------- #
# LP-488 — MI-4's FHA upfront MIP, as a RATE.
#
# ⚠️ WHY THIS IS NOT VACUOUS (ADR-330). The two operands are two DIFFERENT MISMO elements:
# TERMS_OF_LOAN/BaseLoanAmount (the model maps it to loan_amount — its own comment records the mapping)
# and TERMS_OF_LOAN/NoteAmount. On an FHA loan the borrower signs a note for the base amount PLUS the
# financed upfront MIP, so the difference between them is the premium. On the three conventional MISMO
# fixtures in the repo the two are equal, which is exactly right: no UFMIP on a conventional loan.
#
# ⚠️ THE RATE, NOT A VARIANCE — so the 175-bps figure stays in MI-4's reference_values where it is cited
# and reviewable, instead of being hard-coded into this recipe.
# --------------------------------------------------------------------------- #


def _fha_ufmip_percent(
    snapshot: Snapshot, _subject_id: str, _subject_raw: object
) -> tuple[JsonValue, str]:
    """mi.fha_ufmip_percent — financed upfront MIP as a percent of the base loan amount (MI-4).

    ``(note amount - base loan amount) / base loan amount x 100``. Abstains when either amount is
    missing or the base is not positive — never a fabricated 0, which a rule would read as "nothing was
    financed" and treat as a real (if reviewable) answer.
    """
    base = _first_loan_decimal(snapshot, "loan.amount")
    note = _first_loan_decimal(snapshot, "loan.note_amount")
    if base is None:
        return _UNKNOWN, "the file states no base loan amount"
    if note is None:
        return _UNKNOWN, "the file states no note amount"
    if base <= 0:
        return _UNKNOWN, "the base loan amount is not a positive number"
    financed = note - base
    if financed <= 0:
        # ⚠️ The reason text is processor-visible evidence on MI-4's needs_review row, and that row IS the
        # note <= base case — so "exceeds ... by 0.00" (or "by -5000") was the sentence a processor read.
        return "0.0000", (
            f"the note amount ({note}) does not exceed the base loan amount ({base}), so no upfront MIP "
            "was financed into the loan (it may have been paid in cash)"
        )
    percent = (financed / base * Decimal(100)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return str(percent), (
        f"the note amount ({note}) exceeds the base loan amount ({base}) by {financed}, which is "
        f"{percent}% of the base loan amount"
    )


def _condo_questionnaire_present(
    snapshot: Snapshot, _subject_id: str, _subject_raw: object
) -> tuple[JsonValue, str]:
    """condo.questionnaire_present — does the file carry a condo questionnaire? (CO-1, LP-488)

    ⚠️ A DOCUMENT-TYPE PRESENCE READ — the classifier's type label, never extracted fields (the
    IN-8/IN-9/IN-16 discipline). A questionnaire that classified correctly but extracted badly still
    EXISTS; judging its contents is CO-3/CO-5's job, not CO-1's.

    ⚠️ An empty file abstains rather than answering "no". A file with no documents at all is not
    evidence that a questionnaire is missing — it is evidence that nothing has been uploaded yet.
    """
    if snapshot.documents.absent or not snapshot.documents.entries:
        return (
            _UNKNOWN,
            "the file carries no documents, so the questionnaire's absence cannot be read",
        )
    types = {entry.document_type for entry in snapshot.documents.entries}
    if types & _CONDO_QUESTIONNAIRE_DOC_TYPES:
        return "yes", "the file carries a condo questionnaire"
    # ⚠️ ABSTAIN ON THE ADJACENT TYPE (reported finding). `hoa_certification` is a sibling Tier-1 type the
    # classifier is explicitly told is confusable with this one ("the project-eligibility certification,
    # distinct from ... condo_questionnaire"), and it carries the very facts CO-1's how_to_fix asks for —
    # unit counts, owner-occupancy, delinquency, litigation. Firing "request a questionnaire" at a file
    # holding one is the IH-7 defect again: telling a processor to fetch a document already in front of
    # them. Whether a certification SATISFIES the project review is a domain call, so this abstains rather
    # than answering "yes" — the safe half of the fix.
    if types & _CONDO_PROJECT_ADJACENT_DOC_TYPES:
        return _UNKNOWN, (
            "the file carries an HOA/condo project certification but no questionnaire — a human must "
            "confirm whether the certification satisfies the project review"
        )
    return "no", "no document in the file is classified as a condo questionnaire"


# --------------------------------------------------------------------------- #
# LP-488 — AU-3's AUS recommendation. ⚠️ THE `is_disputed` MISTAKE, AVOIDED ON REAL EVIDENCE.
#
# The catalog vocabulary for `aus.recommendation` is DU's: approve_eligible / approve_ineligible / refer
# / out_of_scope. The ONE aus_findings document in the 303-document corpus is an **LPA** (Freddie's Loan
# Product Advisor) whose recommendation reads **"ACCEPT"** — a term that does not appear in that
# vocabulary at all. A rule written as equality against DU's spelling would abstain on, or misread,
# every Freddie file. This is exactly the CR-12 `is_disputed` case: ONE FIELD, TWO VENDOR ENCODINGS.
#
# So the recipe recognises a DECLARED closed vocabulary spanning both engines and ABSTAINS on anything
# else. It never stems, never fuzzy-matches, never infers.
#
# ⚠️ THE DU/LPA EQUIVALENCE IS A DOMAIN CLAIM, and it is logged for Priya rather than buried here.
# DU splits its answer into a recommendation (Approve / Refer) plus an eligibility (Eligible /
# Ineligible); LPA gives a risk class (Accept / Caution) plus an eligibility. Treating LPA "Accept" as
# DU "Approve" is the standard industry equivalence, but it IS a mapping, not a reading.
#
# ⚠️ THIN CORPUS: n=1, and that one is LPA. The DU spellings below are researched, NOT observed in our
# data. They abstain rather than misfire if wrong, which is the safe direction — but no DU file has ever
# exercised them.
# --------------------------------------------------------------------------- #

# Vendor-spanning, mirrored in AU-3's spec reference_values and pinned identical by test.
# ⚠️ SYMMETRIC (reported finding). Approve carried both /eligible and /ineligible while refer carried
# only /eligible, so `Refer/Ineligible` — an ordinary DU recommendation — abstained on a rule already
# caveated at n=1. Slashed forms are normalised before lookup (see _normalise_aus_decision), so the
# equally common spaced rendering "Approve / Eligible" no longer misses either.
_AUS_APPROVE_PHRASES: frozenset[str] = frozenset(
    {
        "approve",
        "approve/eligible",
        "approve/ineligible",
        "accept",
        "accept/eligible",
        "accept/ineligible",
    }
)
_AUS_REFER_PHRASES: frozenset[str] = frozenset(
    {
        "refer",
        "refer/eligible",
        "refer/ineligible",
        "refer with caution",
        "refer w/ caution",
        "caution",
        "caution/eligible",
        "caution/ineligible",
    }
)


def _normalise_aus_decision(raw: str) -> str:
    """A DU/LPA recommendation for vocabulary lookup: casefolded, whitespace-collapsed, and with the
    spaces around a slash removed so "Approve / Eligible" and "Approve/Eligible" are one token."""
    return re.sub(r"\s*/\s*", "/", _normalise_vocab(raw))


_AUS_OUT_OF_SCOPE_PHRASES: frozenset[str] = frozenset(
    {"out of scope", "outofscope", "error", "incomplete"}
)
_AUS_ELIGIBLE_PHRASES: frozenset[str] = frozenset({"eligible", "eligible/approve", "accept"})
_AUS_INELIGIBLE_PHRASES: frozenset[str] = frozenset({"ineligible", "not eligible"})


def _entry_text(entry: DocumentEntry, field_name: str) -> str:
    """A document entry's field as trimmed text, or "" when absent/empty."""
    field = entry.fields.get(field_name)
    if not isinstance(field, Field) or not field.is_present or field.value is None:
        return ""
    return str(field.value).strip()


def _aus_recommendation(
    _snapshot: Snapshot, _subject_id: str, subject_raw: object
) -> tuple[JsonValue | None, str]:
    """aus.recommendation — the AUS decision, normalised across DU and LPA (AU-3, LP-488).

    Per AUS-findings document: returns ``None`` (DECLINE — no tag materialises) for any other subject,
    so the tag lands only on the documents AU-3 reads (the IH-1 shape).

    ``approve_eligible`` / ``approve_ineligible`` / ``refer`` / ``out_of_scope`` / ``unknown``. An
    unrecognised recommendation abstains — it is NEVER read as an approval.
    """
    if not isinstance(subject_raw, DocumentEntry) or subject_raw.document_type != "aus_findings":
        return None, "not an AUS findings document — no recommendation tag"
    # ⚠️ The RUN IDENTITY, inline (reported finding). AU-3's evidence_required promises "the AUS engine …
    # and the submission date — inline on the finding, so a processor can tell a current run from a
    # superseded one without reopening the report", and the spec justifies per-document evaluation on
    # exactly that. Without it, a file with two submissions produced two findings a processor could not
    # tell apart. Both are extracted fields on the entry; CL-1's recipe sets the inline precedent.
    run = ", ".join(
        f"{label} {value}"
        for label, value in (
            ("engine", _entry_text(subject_raw, "aus_engine")),
            ("submitted", _entry_text(subject_raw, "submission_date")),
        )
        if value
    )
    run_suffix = f" [{run}]" if run else ""
    field = subject_raw.fields.get("recommendation")
    raw = field.value if isinstance(field, Field) and field.is_present else None
    if raw is None or not str(raw).strip():
        return _UNKNOWN, f"this AUS findings document states no recommendation{run_suffix}"
    decision = _normalise_aus_decision(str(raw))
    if decision in _AUS_OUT_OF_SCOPE_PHRASES:
        return "out_of_scope", f"the AUS returned an out-of-scope result ({str(raw)!r}){run_suffix}"
    if decision in _AUS_REFER_PHRASES:
        return (
            "refer",
            f"the AUS referred this file for manual underwriting ({str(raw)!r}){run_suffix}",
        )
    if decision not in _AUS_APPROVE_PHRASES:
        return _UNKNOWN, (
            f"the AUS recommendation reads {str(raw)!r}, which is not a recognised DU or LPA "
            f"recommendation — abstaining rather than inferring (the wording varies by engine){run_suffix}"
        )
    # An APPROVE — now the eligibility half. DU may state it inside the recommendation itself
    # ("Approve/Eligible"); LPA states it in a separate field.
    if "ineligible" in decision:
        return "approve_ineligible", (
            f"the AUS approved the loan but found it INELIGIBLE for delivery ({str(raw)!r}){run_suffix}"
        )
    eligibility_field = subject_raw.fields.get("eligibility_status")
    stated = (
        _normalise_vocab(str(eligibility_field.value))
        if isinstance(eligibility_field, Field)
        and eligibility_field.is_present
        and eligibility_field.value is not None
        else ""
    )
    if "eligible" in decision or stated in _AUS_ELIGIBLE_PHRASES:
        return "approve_eligible", (
            f"the AUS approved the loan and found it eligible ({str(raw)!r}"
            + (f", eligibility {stated!r}" if stated else "")
            + f"){run_suffix}"
        )
    if stated in _AUS_INELIGIBLE_PHRASES:
        return "approve_ineligible", (
            f"the AUS approved the loan but found it INELIGIBLE for delivery ({str(raw)!r}, "
            f"eligibility {stated!r})"
        )
    # ⚠️ An approval whose ELIGIBILITY we cannot read abstains. "Approve" alone does not mean
    # deliverable, and reading it as approve_eligible would turn an unread field into a clearance.
    return _UNKNOWN, (
        f"the AUS recommendation reads {str(raw)!r} but the eligibility is not stated in a recognised "
        "form — an approval is not a clearance until the eligibility is known"
    )


# --------------------------------------------------------------------------- #
# LP-490 — CR-6's seasoning arithmetic and CR-10's aggregate.
#
# ⚠️ THE SEASONING IS MEASURED FROM THE EVENT'S OWN DATE, never from the credit report's date. Priya was
# explicit: a discharge, dismissal or completion date is the only honest anchor. Using the report date
# would season an event to whenever the report happened to be pulled — a four-year bankruptcy waiting
# period would "complete" the moment someone re-pulled credit. When the event has no date, this abstains.
#
# ⚠️ THESE RECIPES CARRY NO WAITING PERIOD. The matrix (4 years / 2 years / 7 years by event type) lives
# in CR-6's reference_values, where it is reviewable and cited to Priya. The tag emits ELAPSED MONTHS and
# the rule judges them — tags describe, rules judge.
# --------------------------------------------------------------------------- #


def _derogatory_months_elapsed(
    snapshot: Snapshot, _subject_id: str, subject_raw: object
) -> tuple[JsonValue | None, str]:
    """credit.derogatory_months_elapsed — months from THIS event's own date to closing (CR-6, LP-490).

    Per liability; declines (``None``) for a non-liability subject. Abstains to ``unknown`` when the
    event has no date of its own — NEVER substituting the report date.
    """
    from app.verification.rule_engine.enumerators import LiabilityRow

    if not isinstance(subject_raw, LiabilityRow):
        return None, "not a liability subject"
    tags = snapshot.tags.by_subject.get(_subject_id, {}) if not snapshot.tags.absent else {}
    event = tags.get("liab.derogatory_date")
    raw = None if event is None else str(event.value)
    if raw is None or raw == _UNKNOWN or not raw.strip():
        return _UNKNOWN, (
            "this derogatory event states no discharge, dismissal or completion date — the seasoning "
            "cannot be measured, and is NEVER computed from the credit report's own date"
        )
    parsed = coerce_date(raw)
    if parsed is None:
        return _UNKNOWN, f"the derogatory event's date {raw!r} could not be read as a date"
    closing, reason = _single_parsed_date(snapshot, "contract.closing_date")
    if closing is None:
        return _UNKNOWN, f"the loan's closing date is {reason}, so no seasoning can be measured"
    months = _completed_months(parsed, closing)
    if months < 0:
        return _UNKNOWN, (
            f"the derogatory event's date ({parsed.isoformat()}) is AFTER the loan's closing date "
            f"({closing.isoformat()}) — the file contradicts itself, so this is surfaced, not seasoned"
        )
    return str(months), (
        f"{months} complete month(s) from the event ({parsed.isoformat()}) to closing "
        f"({closing.isoformat()})"
    )


def _non_medical_collection_balances(
    snapshot: Snapshot, _subject_id: str, _subject_raw: object
) -> tuple[list[Decimal] | None, str]:
    """The borrower's non-medical collection balances, or ``(None, reason)`` when it cannot be measured.

    THE ONE PLACE the row filter lives, so the aggregate, the largest-single figure and the
    has-collections gate can never disagree about which rows count. Every guard below is a reported
    finding from LP-490's review; each is commented where it applies.
    """
    from app.verification.rule_engine.enumerators import _SOURCE_CREDIT_REPORT, liability_rows

    if snapshot.tags.absent:
        return None, "no tags materialized, so no collection balances to aggregate"

    # ⚠️ FILE-WIDE ROWS CANNOT BE ATTRIBUTED ON A JOINT FILE. LiabilityRow carries no borrower link, so
    # every borrower would receive BOTH borrowers' collections while CR-10 compares against PER-BORROWER
    # thresholds ($250/$1,000/$2,000/$5,000) — borrower B's collections pushing borrower A over. On a
    # single-borrower file the file total IS that borrower's; on a joint file it is not. Attributing
    # properly needs a document link on the row (an enumerator change), not a guess here.
    # ⚠️ THE JOINT-FILE ABSTAIN IS DEFERRED UNTIL IT MATTERS (reported finding — mine, from the previous
    # review). Abstaining on EVERY multi-borrower file was right in principle and wrong in effect: once
    # CR-10 went live, `credit.has_collections` resolved to "unknown" for both borrowers, and
    # resolve_applicability maps an unknown predicate to couldnt_check — so every joint file (the common
    # case, LF-6T3N included) got a per-borrower finding whose reason a processor cannot act on. That is
    # the flooding CR-6's predicate was added to stop, reintroduced one rule over.
    #
    # The asymmetry that fixes it: when the file-wide set is EMPTY, "this borrower has no collections" is
    # unambiguous for every borrower — no attribution is needed to answer no. Attribution only matters
    # when collections EXIST and must be assigned. So the count is gathered first and the abstain moved
    # below, where it fires on a joint file WITH collections — correct, and rare.
    borrowers = subject_type("borrower").enumerate(snapshot)

    balances: list[Decimal] = []
    reported_rows = 0
    judged_rows = 0
    for row in liability_rows(snapshot):
        if row.source != _SOURCE_CREDIT_REPORT:
            continue
        reported_rows += 1
        tags = snapshot.tags.by_subject.get(row.subject_id, {})
        kind = tags.get("liab.derogatory_type")
        if kind is None:
            continue
        judged_rows += 1
        if str(kind.value) not in {"collection", "charge_off"}:
            continue
        # ⚠️ A charged-off MORTGAGE is not a collection for this rule. CR-10's prompt says "do not fold
        # one into this decision" — which the model cannot do, because it only receives the summed
        # aggregate. One six-figure mortgage charge-off cleared every threshold on a file whose real
        # non-mortgage collections were zero. A charged-off mortgage seasons under CR-6 instead.
        is_mortgage = tags.get("liab.is_mortgage")
        if is_mortgage is not None and str(is_mortgage.value) == "yes":
            continue
        medical = tags.get("liab.is_medical_collection")
        if medical is not None and str(medical.value) == "yes":
            continue  # excluded from the Fannie payoff limits
        balance = tags.get("liab.collection_balance")
        if balance is None or str(balance.value) == _UNKNOWN:
            return None, (
                "a collection on this report states no readable balance — the total would be "
                "understated, which could clear a threshold the file does not actually clear"
            )
        try:
            balances.append(Decimal(str(balance.value)))
        except (InvalidOperation, ValueError):
            return None, (
                f"a collection's balance ({balance.value!r}) is not a number — abstaining rather than "
                "reporting a partial total"
            )
    if balances and len(borrowers) > 1:
        return None, (
            f"the file has {len(borrowers)} borrowers and a credit-report tradeline carries no borrower "
            "attribution, so this borrower's share of the {n} collection(s) on the report cannot be "
            "separated from the co-borrower's".format(n=len(balances))
        )
    if not balances:
        # ⚠️ A CONFIDENT ZERO IS A FALSE ALL-CLEAR unless a credit report was actually read.
        # _credit_undisclosed_tradeline abstains in exactly this situation, for exactly this reason:
        # "no undisclosed debt on a file with no credit report is a false ALL-CLEAR, which is worse
        # than saying nothing."
        if reported_rows == 0:
            return None, (
                "no credit-report tradelines on the file — a $0 collection total would be a false "
                "all-clear rather than a measurement"
            )
        if judged_rows == 0:
            return None, (
                f"{reported_rows} credit-report tradeline(s), but none carries a derogatory-type "
                "judgment — the collection total cannot be concluded to be zero"
            )
    return balances, ""


def _collection_aggregate_balance(
    snapshot: Snapshot, subject_id: str, subject_raw: object
) -> tuple[JsonValue, str]:
    """credit.collection_aggregate_balance — the borrower's NON-MEDICAL collection total (CR-10).

    ⚠️ ABSTAINS IF ANY CONTRIBUTING BALANCE IS UNREADABLE. A partial sum understates the aggregate and
    could clear a $1,000 or $2,000 threshold the file does not actually clear — the one direction that
    turns a missing number into a pass.

    ⚠️ MEDICAL collections are EXCLUDED (Fannie's payoff limits do not count them), and a tradeline
    whose medical status is unknown is treated as CONTRIBUTING: excluding an unknown would be the
    permissive guess. Row selection lives in :func:`_non_medical_collection_balances`.
    """
    rows, why = _non_medical_collection_balances(snapshot, subject_id, subject_raw)
    if rows is None:
        return _UNKNOWN, why
    if not rows:
        return "0", "no non-medical collections on this borrower's credit report"
    total = sum(rows, Decimal(0))
    return str(total), f"{len(rows)} non-medical collection(s) totalling {total}"


def _collection_largest_single_balance(
    snapshot: Snapshot, subject_id: str, subject_raw: object
) -> tuple[JsonValue, str]:
    """credit.largest_single_collection_balance — the biggest single non-medical collection (CR-10).

    ⚠️ THE MISSING HALF OF THE DU MATRIX (reported finding). CR-10's prompt requires "payoff_required if
    any INDIVIDUAL collection is $250 or more, OR the aggregate is above $1,000", but the model received
    only the aggregate — so an investment property with one $300 collection gave aggregate 300 (<= $1,000)
    and no per-collection view, and the model answered no_payoff_required for a collection that must be
    paid. This supplies the individual figure the matrix asks about.

    Shares every guard with the aggregate (same abstains, same mortgage/medical exclusions) by reading its
    per-row work through the same helper, so the two can never disagree about which rows count.
    """
    rows, why = _non_medical_collection_balances(snapshot, subject_id, subject_raw)
    if rows is None:
        return _UNKNOWN, why
    if not rows:
        return "0", "no non-medical collections on this borrower's credit report"
    return str(max(rows)), f"the largest single non-medical collection is {max(rows)}"


def _has_collections(
    snapshot: Snapshot, subject_id: str, subject_raw: object
) -> tuple[JsonValue, str]:
    """credit.has_collections — does this borrower have ANY non-medical collection? (CR-10's gate)

    ⚠️ CR-10 had NO applicability predicate (reported finding), so every borrower on every file got an AI
    call and a needs_review finding — including the overwhelmingly common file with zero collections (all
    three real reports carry none). The spec's own applicability.trigger already said "a borrower with
    none is not applicable"; this makes that expressible, since the predicate DSL is eq/ne on a tag and
    cannot compare the aggregate numerically.
    """
    rows, why = _non_medical_collection_balances(snapshot, subject_id, subject_raw)
    if rows is None:
        return _UNKNOWN, why
    return (
        ("yes", f"{len(rows)} non-medical collection(s) on the credit report")
        if rows
        else (
            "no",
            "no non-medical collections on this borrower's credit report",
        )
    )


# --------------------------------------------------------------------------- #
# LP-491 — TI-1's vested-owner compare. ⚠️ IH-2's SHAPE, AND IT REUSES IH-2's NORMALISER RATHER THAN
# CLONING IT (LP-487): truncate at an assignment/care-of marker, strip punctuation, drop corporate-suffix
# tokens from BOTH sides, compare whole tokens in order with a two-token prefix tolerance. One normaliser,
# so a fix to either rule's name handling reaches both.
#
# ⚠️ THE VESTING TOKENS BELOW ARE SPECULATIVE — the reported finding. ALL FOUR real title commitments
# carry a PLAIN NAME in vested_owner_name (2-3 words, no TRUSTEE / HUSBAND AND WIFE / ET UX); the recital
# lives in `vesting_marital_recital`, which fills 0/4. Real-world titles do carry these forms, so they are
# stripped — but nothing in our corpus exercises them, and that is recorded rather than implied.
# --------------------------------------------------------------------------- #

_VESTING_TRUNCATE_MARKERS: tuple[str, ...] = (
    "et ux",
    "et al",
    "husband and wife",
    "a married man",
    "a married woman",
    "a single man",
    "a single woman",
    "an unmarried man",
    "an unmarried woman",
    "as trustee",
    "trustee of",
    "as joint tenants",
    "as tenants",
)


_VESTING_MARKER_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(m) for m in _VESTING_TRUNCATE_MARKERS) + r")\b"
)


def _normalise_party_name(raw: str) -> list[str]:
    """A title party's name reduced to comparable tokens — IH-2's normaliser plus vesting recitals.

    ⚠️ MARKERS MATCH ON WORD BOUNDARIES, and that is the whole correctness of this function. A bare
    ``str.find`` matched a marker INSIDE an ordinary name and truncated it to a shared prefix, which does
    not merely lose precision — it manufactures agreement:

        'Margaret Alonso'  -> ['margar']   |  'Margaret Alvarez'  -> ['margar']   -> MATCH
        'Janet Allen'      -> ['jan']      |  'Janet Alonzo'      -> ['jan']      -> MATCH

    because "margar|et al|onso" contains "et al". So a title vested in one person and a contract naming a
    different person returned ``title.vested_owner_matches = "yes"`` and TI-1 reported SATISFIED — the one
    verdict the spec says no human re-reads. IH-2's older markers (``c/o``, ``isaoa``, ``atima``) are long
    enough that this never bit; the short vesting recitals ("et al", "et ux") are not.
    """
    text = _WS.sub(" ", raw).strip().casefold()
    match = _VESTING_MARKER_RE.search(text)
    if match is not None:
        text = text[: match.start()]
    return _normalise_lender_name(text)


def _file_counterparty(snapshot: Snapshot) -> tuple[list[list[str]], str]:
    """The parties the vested owner should match, chosen by loan purpose.

    ⚠️ RETURNS EVERY NAME, not the first (reported finding). _title_vested_owner_matches deliberately
    matches against vested_owner_name OR vested_owner_name_2 because 3 of 4 real commitments are
    co-owned — but this side took sellers[0] / names[0] only, so a couple selling jointly whose
    commitment vests in the SECOND seller produced a needs_review on a correct file.

    ⚠️ THE PURPOSE BRANCH LIVES HERE, NOT IN AN APPLICABILITY PREDICATE, and the reason is that TI-1
    applies to BOTH purposes — there is no single predicate value to scope on. The abstain that a
    predicate would have given is preserved exactly: an unstated purpose returns no counterparty, the tag
    resolves to "unknown", and the gate routes that to couldnt_check. A file that does not state its
    purpose is SURFACED, never silently skipped (LP-487/LP-488's finding, honoured by a different means).

    PURCHASE  → the seller on the purchase agreement: whoever is on title today should be selling.
    REFINANCE → the borrower: the borrower should already own the property they are refinancing.
    """
    purposes = {v.casefold() for v in _parsed_strings(snapshot, "loan.purpose")}
    if not purposes:
        return [], "the file does not state whether this is a purchase or a refinance"
    if len(purposes) > 1:
        return [], f"the file states more than one loan purpose ({', '.join(sorted(purposes))})"
    purpose = next(iter(purposes))
    if purpose == "purchase":
        sellers = _parsed_strings(snapshot, "contract.seller_name")
        if not sellers:
            return (
                [],
                "no purchase agreement on the file names a seller to compare the vested owner with",
            )
        parties = [_normalise_party_name(name) for name in sellers]
        return [p for p in parties if p], (
            f"the purchase agreement's seller(s) ({', '.join(repr(x) for x in sellers)})"
        )
    if purpose == "refinance":
        names = _borrower_display_names(snapshot)
        if not names:
            return [], "the file states no borrower name to compare the vested owner with"
        parties = [_normalise_party_name(name) for name in names]
        return [p for p in parties if p], (f"the borrower(s) ({', '.join(repr(x) for x in names)})")
    return [], f"the loan purpose {purpose!r} is not one with a defined set of parties to compare"


def _borrower_display_names(snapshot: Snapshot) -> list[str]:
    """Each MISMO borrower's "first last", in index order."""
    if snapshot.mismo.absent:
        return []
    out: list[str] = []
    index = 1
    while True:
        first = snapshot.mismo.facts.get(f"borrower.{index}.first_name")
        if first is None:
            break
        last = snapshot.mismo.facts.get(f"borrower.{index}.last_name")
        # ⚠️ A borrower name is PII, so a fact here may be a PiiField carrying only a MASKED display.
        # Read the display for one and the value for a plain Field — never assume `.value` exists.
        parts = [
            str(value)
            for f in (first, last)
            if f is not None
            and f.is_present
            and (value := (f.display if isinstance(f, PiiField) else f.value))
        ]
        if parts:
            out.append(" ".join(parts))
        index += 1
    return out


def _title_vested_owner_matches(
    snapshot: Snapshot, _subject_id: str, subject_raw: object
) -> tuple[JsonValue | None, str]:
    """title.vested_owner_matches — does this commitment's vested owner match the file's counterparty?

    Per COMMITMENT (declines for any other subject, the IH-1 shape). ⚠️ Matches against EITHER vested
    owner: 3 of the 4 real commitments carry a second owner, and a co-owned property matching only the
    second name is still a match.
    """
    if (
        not isinstance(subject_raw, DocumentEntry)
        or subject_raw.document_type != "title_commitment"
    ):
        return None, "not a title commitment — no vested-owner tag"
    owners = [
        str(field.value)
        for name in ("vested_owner_name", "vested_owner_name_2")
        if isinstance(field := subject_raw.fields.get(name), Field)
        and field.is_present
        and str(field.value).strip()
    ]
    if not owners:
        return _UNKNOWN, "this commitment states no vested owner"
    counterparty, label = _file_counterparty(snapshot)
    if not counterparty:
        return _UNKNOWN, label
    for owner in owners:
        tokens = _normalise_party_name(owner)
        if not tokens:
            # ⚠️ ABSTAIN, don't answer "no" (reported finding). The vocabulary declares this tag
            # "unknown" when nothing identifying survives normalisation — "never a guessed match" — and
            # IH-2 abstains in exactly this case. Falling through to "no" turned an unreadable name into
            # a needs_review finding instead of an honest couldnt_check.
            return _UNKNOWN, (
                f"the commitment's vested owner ({owner!r}) leaves nothing identifying after normalising "
                "the vesting recital — abstaining rather than guessing a match"
            )
        if any(_lender_names_agree(tokens, party) for party in counterparty):
            return "yes", f"the vested owner ({owner!r}) matches {label}"
    return "no", (
        f"the commitment's vested owner ({', '.join(repr(o) for o in owners)}) does not match {label} — "
        "a vesting difference can be legitimate (a trust, an estate, a name change), so this is raised "
        "for confirmation rather than treated as an error"
    )


# --------------------------------------------------------------------------- #
# LP-491 — TI-6's chain facts. ⚠️ NOT AN ADR-330 VACUITY, and this was the Phase A question. A chain gap
# is grantee[n] vs grantor[n+1] — a continuity check ACROSS ROWS, which is exactly AS-8's shape (a
# statement's ending balance against the next statement's opening). One field judged against itself would
# be vacuous; consecutive rows judged against each other is a real comparison.
#
# ⚠️ DETERMINISTIC CODE COMPUTES THE FACTS; TI-6's AI JUDGES THEM. The count, the gap and the shortest
# interval are arithmetic and a name compare — no judgment in them. Whether a 40-day resale with a price
# jump is a flip is the judgment, and that is the rule's.
#
# ⚠️ THE CORPUS IS THIN HERE: the four real commitments carry 1, 2, 1 and 0 chain rows, so exactly ONE
# consecutive pair exists to test a gap against. Recorded on the spec.
# --------------------------------------------------------------------------- #


def _chain_rows(subject_raw: object) -> list[dict[str, str]]:
    """This commitment's chain_of_title rows as plain dicts, in listed order."""
    if not isinstance(subject_raw, DocumentEntry):
        return []
    rows = (subject_raw.lists or {}).get("chain_of_title") or ()
    out: list[dict[str, str]] = []
    for row in rows:
        out.append(
            {
                k: str(f.value)
                for k, f in row.fields.items()
                if isinstance(f, Field) and f.is_present and str(f.value).strip()
            }
        )
    return out


def _title_chain_transfer_count(
    _snapshot: Snapshot, _subject_id: str, subject_raw: object
) -> tuple[JsonValue | None, str]:
    """title.chain_transfer_count — how many transfers the chain lists (TI-6)."""
    if (
        not isinstance(subject_raw, DocumentEntry)
        or subject_raw.document_type != "title_commitment"
    ):
        return None, "not a title commitment — no chain tag"
    rows = _chain_rows(subject_raw)
    if not rows:
        # ⚠️ NEVER 0. A commitment with no chain section is not a property with no transfers.
        return _UNKNOWN, "this commitment lists no chain of title"
    return str(len(rows)), f"the chain lists {len(rows)} transfer(s)"


def _title_chain_has_gap(
    _snapshot: Snapshot, _subject_id: str, subject_raw: object
) -> tuple[JsonValue | None, str]:
    """title.chain_has_gap — does a transfer's grantee fail to be the next transfer's grantor? (TI-6)

    ⚠️ Uses the SAME name normaliser as TI-1 and IH-2, so a name-handling fix reaches all three. A name
    that does not normalise abstains rather than reading as a gap: an unreadable name is not a break.
    """
    if (
        not isinstance(subject_raw, DocumentEntry)
        or subject_raw.document_type != "title_commitment"
    ):
        return None, "not a title commitment — no chain tag"
    rows = _chain_rows(subject_raw)
    if len(rows) < 2:
        return _UNKNOWN, (
            f"the chain lists {len(rows)} transfer(s) — at least two are needed to check continuity"
        )
    # ⚠️ SORT BY TRANSFER DATE FIRST (reported finding). This paired grantee->grantor in RAW LIST ORDER,
    # and nothing guarantees oldest-first: the extraction prompt gives the model no ordering instruction,
    # and real title commitments commonly list transfers NEWEST-first. On a reversed chain the comparison
    # is inverted and almost always fails, reporting `chain_gap` on a perfectly continuous chain. The
    # sibling _title_chain_shortest_interval already sorts for exactly this reason. A row with no readable
    # date cannot be ordered, so the gap check abstains rather than guessing a sequence.
    datable = [
        (parsed, r) for r in rows if (parsed := coerce_date(r.get("transfer_date", ""))) is not None
    ]
    if len(datable) != len(rows):
        return _UNKNOWN, (
            "a transfer in the chain of title states no readable date, so the transfers cannot be put in "
            "order — abstaining rather than reading an unordered chain as a gap"
        )
    rows = [r for _, r in sorted(datable, key=lambda pair: pair[0])]
    for earlier, later in pairwise(rows):
        grantee = _normalise_party_name(earlier.get("grantee", ""))
        grantor = _normalise_party_name(later.get("grantor", ""))
        if not grantee or not grantor:
            return _UNKNOWN, (
                "a transfer states no readable grantee or grantor, so continuity cannot be checked — "
                "an unreadable name is not a break in the chain"
            )
        if not _lender_names_agree(grantee, grantor):
            return "yes", (
                "a transfer's grantee is not the next transfer's grantor — the chain does not run "
                "continuously through the listed owners"
            )
    return "no", "each transfer's grantee is the next transfer's grantor"


def _title_chain_shortest_interval(
    _snapshot: Snapshot, _subject_id: str, subject_raw: object
) -> tuple[JsonValue | None, str]:
    """title.chain_shortest_interval_days — the shortest gap between consecutive transfers (TI-6)."""
    if (
        not isinstance(subject_raw, DocumentEntry)
        or subject_raw.document_type != "title_commitment"
    ):
        return None, "not a title commitment — no chain tag"
    dates = [
        parsed
        for row in _chain_rows(subject_raw)
        if (parsed := coerce_date(row.get("transfer_date", ""))) is not None
    ]
    if len(dates) < 2:
        return _UNKNOWN, (
            f"{len(dates)} dated transfer(s) — at least two are needed to measure an interval"
        )
    dates.sort()
    shortest = min((b - a).days for a, b in pairwise(dates))
    return str(
        shortest
    ), f"the shortest interval between consecutive transfers is {shortest} day(s)"


def _property_value_vs_price_gap(
    snapshot: Snapshot, _subject_id: str, _subject_raw: object
) -> tuple[JsonValue, str]:
    """property.value_vs_price_gap — appraised value minus purchase price (PR-2, LP-492).

    ⚠️ NOT A VACUITY (ADR-330), traced in Phase A. The appraised value comes from the APPRAISAL
    (`property.appraised_value`, document-scoped) and the price from the MISMO loan file
    (`property.purchase_price`) — two documents. The appraisal's own `contract_price_stated` field is
    deliberately NOT used: it fills on 1 of the 2 real appraisals, and reading it would make PR-2 compare
    the appraisal against itself, which is DT-4's fate.

    ⚠️ TAKES THE LOWEST APPRAISED VALUE (LP-488). A file carrying an original plus a replacement
    appraisal otherwise gets whichever subject iterated first — an arbitrary answer on an ordinary file
    shape. The conservative pick is the lowest: it makes the shortfall larger, and PR-2's costly error is
    missing one.
    """
    # ⚠️ THE STRICT HELPER (reported finding). _conservative_appraised_value falls back to the MISMO
    # stated value for the LTV consumers, and on a MISMO import that estimate usually EQUALS the price —
    # so a file with NO APPRAISAL yielded a gap of 0 and PR-2 answered SATISFIED, "the appraised value
    # supports the purchase price", which this rule's own spec forbids ("never a guessed pass"). The
    # mirror was as bad: a stated value under the price fired a phantom shortfall citing an appraisal
    # that does not exist. PR-2's question is what the APPRAISAL said, so it asks only the appraisal.
    appraised = _appraised_value_from_appraisal(snapshot)
    if appraised is None:
        return _UNKNOWN, "no appraisal in the file states an appraised value"
    # ⚠️ EITHER PRICE SOURCE (reported finding). Reading only the MISMO fact silently narrowed PR-2 to
    # MISMO-IMPORTED files: a document-only file carrying an uploaded purchase contract and an appraisal
    # has both numbers and still couldnt_checked forever. `contract.loan_sales_price` is the loan-level
    # promotion of the contract's sales price that LP-407-2 added for exactly this scope. MISMO first
    # (it is the file's own statement of the deal), the contract as the fallback.
    price = _first_loan_decimal(snapshot, "property.purchase_price") or _first_loan_decimal(
        snapshot, "contract.loan_sales_price"
    )
    if price is None or price <= 0:
        return _UNKNOWN, "the file states no purchase price to compare the appraised value against"
    gap = appraised - price
    return str(gap), (
        f"the appraised value ({appraised}) is {'above' if gap >= 0 else 'BELOW'} the purchase price "
        f"({price}) by {abs(gap)}"
    )


# --------------------------------------------------------------------------- #
# LP-492 — PR-5's condition rating and PR-7's address match.
#
# ⚠️ THE CONDITION VOCABULARY IS CLOSED AND ABSTAINS (ADR-376). Both real appraisals are UAD 2.6-era
# ("9/2011", "9/2011 (Updated 1/2014)") and spell the rating "C4" / "C3". The UAD 3.6 cutover lands in
# Nov 2026 and MAY spell it differently; an equality against one layout is the `is_disputed` mistake, so
# anything unrecognised resolves to "unknown" and the rule couldnt_checks rather than guessing.
# --------------------------------------------------------------------------- #

_CONDITION_RATINGS: tuple[str, ...] = ("c1", "c2", "c3", "c4", "c5", "c6")


def _property_condition_rating(
    _snapshot: Snapshot, _subject_id: str, subject_raw: object
) -> tuple[JsonValue | None, str]:
    """property.condition_rating — the UAD rating normalised to C1-C6 (PR-5, LP-492)."""
    if not isinstance(subject_raw, DocumentEntry) or subject_raw.document_type != "appraisal":
        return None, "not an appraisal — no condition-rating tag"
    field = subject_raw.fields.get("condition_rating")
    raw = field.value if isinstance(field, Field) and field.is_present else None
    if raw is None or not str(raw).strip():
        return _UNKNOWN, "this appraisal states no condition rating"
    text = _WS.sub("", str(raw)).strip().casefold()
    if text in _CONDITION_RATINGS:
        return (
            text.upper(),
            f"the appraisal's condition rating is {text.upper()} (stated: {str(raw)!r})",
        )
    return _UNKNOWN, (
        f"the condition rating reads {str(raw)!r}, which is not one of C1-C6 — abstaining rather than "
        "inferring (the UAD 3.6 layout may spell it differently from the 2.6 forms in our corpus)"
    )


def _property_appraisal_address_match(
    snapshot: Snapshot, _subject_id: str, subject_raw: object
) -> tuple[JsonValue | None, str]:
    """property.appraisal_address_match — does THIS appraisal's subject address match the file's? (PR-7)

    ⚠️ Mirrors PC-3's `_property_address_match` and REUSES its canonicalisers (`_norm_address`: street
    suffixes, US state names, ZIP+4 → ZIP5) rather than cloning them — no fuzzy matcher, so this is a
    deterministic compare and PR-7 carries no model.

    ⚠️ THE MAILING-ADDRESS TRAP (LP-407-4 D1, and the ticket names it again). Reads the MISMO
    SUBJECT-property address only — never a borrower's `current_address`, which the parser can fill with
    a MAILING address. A file lacking a COMPLETE subject address (line + city + state + postal) resolves
    to unknown, never a comparison against a partial or wrong-typed address.
    """
    if not isinstance(subject_raw, DocumentEntry) or subject_raw.document_type != "appraisal":
        return None, "not an appraisal — no address-match tag"
    field = subject_raw.fields.get("subject_property_address")
    raw = field.value if isinstance(field, Field) and field.is_present else None
    if raw is None or not str(raw).strip():
        return _UNKNOWN, "this appraisal states no subject-property address"
    line, line2, city, state, postal = (
        _mismo_str(snapshot, k) for k in _MISMO_PROPERTY_ADDRESS_KEYS
    )
    if not (line and city and state and postal):
        return _UNKNOWN, (
            "the loan file states no complete subject-property address (street, city, state and postal "
            "code are all required), so the appraisal's address is not compared against a partial one"
        )
    mismo_raw = " ".join(part for part in (line, line2, city, state, postal) if part)
    if _norm_address(str(raw)) == _norm_address(mismo_raw):
        return "yes", f"the appraisal's subject address matches the loan file's ({str(raw)!r})"
    return "no", (
        f"the appraisal's subject address ({str(raw)!r}) does not match the loan file's ({mismo_raw!r})"
    )


# --------------------------------------------------------------------------- #
# LP-495a — THE MORTGAGE-STATEMENT ↔ STATED-LIABILITY RECONCILIATION (ADR-375: ONE MATCHER, TWO RULES).
#
# ⚠️ ONE matcher answers two DIFFERENT questions, and RE-1 / DT-6 each read one of them:
#     RE-1  is this statement's obligation DISCLOSED among the app's stated liabilities?  (reo.statement_disclosure)
#     DT-6  for a MATCHED obligation, does the STATED payment cover the statement's true PITIA?
#           (reo.statement_payment_coverage)
# Two matchers would let the two rules disagree about the same pair of documents — the CR-1/CR-4
# precedent that ADR-375 exists to prevent.
#
# ⚠️ NEITHER RULE MAY ASSERT RETENTION, AND NEITHER EVER FIRES. Both SURFACE a discrepancy as
# `needs_review` and hand the question to the processor. An unmatched statement can be a paid-off loan, a
# duplicate, or a co-signed debt; an understated payment can be a property under contract. "Retained" is an
# INFERENCE no document, field or MISMO fact in this system states (LP-495a Phase A), so a rule that
# asserted it would put a PITIA into the DTI for a property being sold and fail a qualified borrower.
#
# ⚠️ `property.is_retained_reo` and `property.retained_pitia` STAY VOCABULARY ORPHANS. Neither recipe here
# reads them; they have no `tag_production.yaml` entry and no producer, exactly as
# `property.is_warrantable_condo` does. A test pins that, so this lane can never be mistaken for coverage
# of the retention question.
#
# ⚠️ NO PROPERTY ADDRESS IS AVAILABLE ON THE STATED SIDE. MISMO emits only
# `liability.{k}.type / .monthly_payment / .unpaid_balance / .holder_name` — there is no address on a
# liability — so the match is on HOLDER NAME, reusing IH-2's `_normalise_lender_name` /
# `_lender_names_agree` rather than cloning a second name matcher.
#
# ⚠️ THE ABSTAIN RATE IS REAL AND STATED, NOT DISCOVERED LATER: `lender_name` fills 54/71 mortgage
# statements (LP-495a Phase A), so ~24% of statements abstain on the name alone. Abstain is the safe
# direction — the alternative is reading an unnamed statement as an undisclosed debt.
# --------------------------------------------------------------------------- #

_REO_STATEMENT_DOC_TYPE = "mortgage_statement"
# The MISMO `liability.{k}.type` value that means "a mortgage", casefolded. StatedLiability carries
# MortgageLoan / Revolving / Installment / HELOC / Open30Day; only MortgageLoan is the comparison set for a
# mortgage statement. ⚠️ HELOC is deliberately NOT included: a HELOC statement is a different document type
# and a HELOC liability is not what a mortgage statement evidences — folding it in would match a first
# mortgage's statement onto a line of credit.
_REO_STATED_MORTGAGE_TYPE = "mortgageloan"


class _StatementMatch(NamedTuple):
    """The ONE matcher's result, read by both RE-1's and DT-6's recipes.

    ``outcome`` is ``matched`` / ``unmatched`` / ``unknown``. The three amounts are carried so DT-6's
    recipe never has to re-read the documents (and so the two rules cannot disagree about which stated
    liability this statement matched).
    """

    outcome: str
    reason: str
    stated_payment: Decimal | None
    statement_payment: Decimal | None
    statement_escrow: Decimal | None
    # LP-575 — the MATCHED liability's payoff marking, carried here rather than re-derived. ADR-375's
    # whole point is that one matcher answers every question about the same pair; a second lookup
    # could pair the statement with a different liability than DT-6's comparison used. Defaulted so
    # the abstaining branches (which have no matched liability) are unchanged.
    stated_paid_off: str | None = None
    # LP-576 — the matched liability's HOLDER, so DT-6's Apply can target the row it just compared
    # against. A governed rule's subjects are content ids, never DB primary keys, so the holder is
    # the business key — and taking it from the matcher means the Apply cannot edit a different
    # liability than the comparison used.
    stated_holder: str | None = None


def _entry_decimal(entry: DocumentEntry, field_name: str) -> Decimal | None:
    """A document entry's field as a Decimal, or None when absent / empty / not a number."""
    text = _entry_text(entry, field_name)
    if not text:
        return None
    try:
        return Decimal(text.replace(",", "").replace("$", "").strip())
    except (InvalidOperation, ValueError):
        return None


def _stated_mortgage_liabilities(snapshot: Snapshot) -> list[dict[str, str]]:
    """The app's stated MISMO liabilities of type MortgageLoan, as ``[{field: text}, …]``.

    Reads the flat ``liability.{k}.{field}`` facts the MISMO section projects. The ``{k}`` index is
    positional and used ONLY to gather one row's fields together, never as an identity.
    """
    if snapshot.mismo.absent:
        return []
    rows: dict[str, dict[str, str]] = {}
    for key, field in snapshot.mismo.facts.items():
        parts = key.split(".")
        if len(parts) != 3 or parts[0] != "liability":
            continue
        _, index, name = parts
        value = field.value if isinstance(field, Field) and field.is_present else None
        if value is None or not str(value).strip():
            continue
        rows.setdefault(index, {})[name] = str(value).strip()
    # UNTYPED ROWS ARE KEPT (reported finding). `liability_type` is nullable and comes straight from
    # optional XML, so filtering strictly to MortgageLoan dropped a row that MATCHES the statement's
    # lender while OTHER typed rows kept the stated list non-empty — the "no stated side" abstain then
    # did not fire and a disclosed obligation was reported UNDISCLOSED. HELOC is the real-world instance:
    # the catalog has no HELOC statement type, so a HELOC servicer's statement classifies as
    # mortgage_statement while the HELOC liability is typed something this filter excluded.
    # Keeping untyped rows only widens what can MATCH; a match still requires the holder names to agree.
    return [
        row
        for _, row in sorted(rows.items(), key=lambda kv: (len(kv[0]), kv[0]))
        if row.get("type", "").casefold().replace(" ", "") in (_REO_STATED_MORTGAGE_TYPE, "")
    ]


def _mortgage_statement_entries(snapshot: Snapshot) -> list[DocumentEntry]:
    """Every mortgage statement on the file — the set the one-to-one pairing check counts against."""
    if snapshot.documents.absent:
        return []
    return [e for e in snapshot.documents.entries if e.document_type == _REO_STATEMENT_DOC_TYPE]


def _reo_match_statement(snapshot: Snapshot, entry: DocumentEntry) -> _StatementMatch:
    """⚠️ THE ONE MATCHER (ADR-375) — match ONE mortgage statement to the app's stated mortgage liabilities.

    Tolerant on the holder/lender name (IH-2's normaliser + token-prefix agreement), and ABSTAINS rather
    than guessing at every ambiguity:

    * the statement states no lender name (the 54/71 fill — ~24% of statements) → ``unknown``;
    * nothing identifying survives normalisation → ``unknown``;
    * the file states NO MISMO mortgage liabilities at all → ``unknown``, **never ``unmatched``**. A file
      with no stated side is a file that cannot be reconciled — reporting every statement as an
      undisclosed debt because the application was never imported is the fail-OPEN direction;
    * MORE THAN ONE stated liability matches the name → ``unknown``. Two loans with the same servicer is
      ordinary (a first and a second), and picking one would attach DT-6's payment comparison to a
      liability chosen by list order.
    """
    lender = _entry_text(entry, "lender_name")
    statement_payment = _entry_decimal(entry, "monthly_payment")
    statement_escrow = _entry_decimal(entry, "escrow_amount")
    if not lender:
        return _StatementMatch(
            _UNKNOWN,
            "this mortgage statement states no lender name, so the obligation it evidences cannot be "
            "matched against the liabilities stated on the application",
            None,
            statement_payment,
            statement_escrow,
        )
    lender_tokens = _normalise_lender_name(lender)
    if not lender_tokens:
        return _StatementMatch(
            _UNKNOWN,
            f"nothing identifying survives normalisation of the statement's lender name ({lender!r}) — "
            "abstaining rather than reading an empty name as an unmatched obligation",
            None,
            statement_payment,
            statement_escrow,
        )
    stated = _stated_mortgage_liabilities(snapshot)
    if not stated:
        return _StatementMatch(
            _UNKNOWN,
            "the application states no mortgage liabilities to reconcile against — with no stated side "
            "there is nothing to match, so this is not read as an undisclosed obligation",
            None,
            statement_payment,
            statement_escrow,
        )
    matches = [
        row
        for row in stated
        if (holder := row.get("holder_name"))
        and _lender_names_agree(_normalise_lender_name(holder), lender_tokens)
    ]
    if len(matches) > 1:
        return _StatementMatch(
            _UNKNOWN,
            f"the statement's lender ({lender!r}) matches {len(matches)} of the mortgage liabilities "
            "stated on the application — abstaining rather than comparing the payment against one of "
            "several the application itself does not distinguish",
            None,
            statement_payment,
            statement_escrow,
        )
    if not matches and any(not row.get("holder_name") for row in stated):
        # A NAMELESS STATED ROW IS NOT EVIDENCE OF ABSENCE (reported finding). holder_name is nullable
        # and mismo_section emits it only when the XML carries it, so the walrus filter above drops such
        # rows from `matches` and control fell through to "unmatched" — reporting "does not correspond to
        # any mortgage liability stated on the application" about an application that DOES state one, we
        # simply cannot compare names. This is the symmetric case of the abstain directly above, and the
        # lesson this ticket itself recorded: a negative search on ONE side does not close a
        # cross-source rule.
        return _StatementMatch(
            _UNKNOWN,
            f"the application states a mortgage liability with no holder name, so this statement's "
            f"lender ({lender!r}) cannot be reconciled against it either way",
            None,
            statement_payment,
            statement_escrow,
        )
    if not matches:
        return _StatementMatch(
            "unmatched",
            f"no mortgage liability stated on the application names a holder matching this statement's "
            f"lender ({lender!r})",
            None,
            statement_payment,
            statement_escrow,
        )
    # ONE-TO-ONE, BOTH WAYS (reported finding). The guard above covers one statement matching MANY
    # stated liabilities; nothing covered MANY STATEMENTS matching ONE. The matcher runs per statement, so
    # two statements from the same servicer — a first at 1450 and a second at 310, which the comments
    # themselves call ordinary — BOTH matched the single stated liability and BOTH returned satisfied,
    # clearing the genuinely undisclosed second lien; DT-6 then compared the 310 statement against the
    # 1450 stated payment and also read "covered". Both rules auto-ship with no ratification, so that
    # satisfied is the verdict nobody re-reads. When the file carries more mortgage statements naming
    # this lender than the application states liabilities for it, the pairing is undetermined — abstain.
    competing = [
        other
        for other in _mortgage_statement_entries(snapshot)
        if (other_lender := _entry_text(other, "lender_name"))
        and _lender_names_agree(_normalise_lender_name(other_lender), lender_tokens)
    ]
    if len(competing) > len(matches):
        return _StatementMatch(
            _UNKNOWN,
            f"the file carries {len(competing)} mortgage statements naming {lender!r} but the "
            f"application states {len(matches)} liability for it — which statement corresponds to the "
            "stated obligation cannot be determined, so neither is read as disclosed or undisclosed",
            None,
            statement_payment,
            statement_escrow,
        )
    holder = matches[0].get("holder_name", "")
    raw_payment = matches[0].get("monthly_payment")
    stated_payment: Decimal | None = None
    if raw_payment is not None:
        try:
            stated_payment = Decimal(raw_payment.replace(",", "").replace("$", "").strip())
        except (InvalidOperation, ValueError):
            stated_payment = None
    return _StatementMatch(
        "matched",
        f"the application states a mortgage liability held by {holder!r}, which matches this "
        f"statement's lender ({lender!r})",
        stated_payment,
        statement_payment,
        statement_escrow,
        matches[0].get("paid_off_at_closing"),
        holder or None,
    )


def _reo_statement_disclosure(
    snapshot: Snapshot, _subject_id: str, subject_raw: object
) -> tuple[JsonValue | None, str]:
    """reo.statement_disclosure — is THIS statement's obligation disclosed on the application? (RE-1)

    Per mortgage statement: returns ``None`` (DECLINE — no tag materialises) for any other subject, so the
    tag lands only on the documents RE-1 reads (the IH-1 / IH-2 shape).

    ⚠️ ``undisclosed`` is a DISCREPANCY, NOT A DEFECT, and RE-1 routes it to ``needs_review``, never to a
    finding. A statement with no matching stated liability can be a loan paid off since the application, a
    duplicate of a liability recorded under a servicer's different name, or a debt the borrower co-signed
    and is not obliged on. The rule surfaces the question; the processor answers it.
    """
    if (
        not isinstance(subject_raw, DocumentEntry)
        or subject_raw.document_type != _REO_STATEMENT_DOC_TYPE
    ):
        return None, "not a mortgage statement — no disclosure tag"
    match = _reo_match_statement(snapshot, subject_raw)
    if match.outcome == "matched":
        return "disclosed", match.reason
    if match.outcome == "unmatched":
        return "undisclosed", match.reason
    return _UNKNOWN, match.reason


def _reo_statement_matched_holder(
    snapshot: Snapshot, _subject_id: str, subject_raw: object
) -> tuple[JsonValue | None, str]:
    """reo.statement_matched_holder — WHICH stated liability this statement matched (LP-576).

    DT-6's Apply target. Only resolves on a `matched` outcome: with no single matched liability there
    is no row to raise, and the apply resolver drops the whole block when a field is unresolvable —
    which is the correct outcome, not a gap.
    """
    if not isinstance(subject_raw, DocumentEntry):
        return None, "not a document subject"
    if (subject_raw.document_type or "") != _REO_STATEMENT_DOC_TYPE:
        return None, "not a mortgage statement"
    match = _reo_match_statement(snapshot, subject_raw)
    if match.outcome != "matched" or not match.stated_holder:
        return _UNKNOWN, "this statement was not matched to exactly one stated mortgage liability"
    return (
        match.stated_holder,
        f"this statement matches the liability held by {match.stated_holder}",
    )


def _reo_statement_billed_payment(
    snapshot: Snapshot, _subject_id: str, subject_raw: object
) -> tuple[JsonValue | None, str]:
    """reo.statement_billed_payment — the servicer's TOTAL monthly payment (LP-576).

    The figure DT-6's Apply writes onto the stated liability. THIS IS ALREADY THE PITIA and is NOT
    added to `escrow_amount` — the extractor defines `monthly_payment` as "the total monthly payment
    (principal+interest+escrow)" and `escrow_amount` as the PORTION within it. Summing them is the
    mistake DT-6's own spec header calls its single most important correctness point, and an Apply
    that did it would write an inflated payment straight onto the loan.
    """
    if not isinstance(subject_raw, DocumentEntry):
        return None, "not a document subject"
    if (subject_raw.document_type or "") != _REO_STATEMENT_DOC_TYPE:
        return None, "not a mortgage statement"
    match = _reo_match_statement(snapshot, subject_raw)
    if match.statement_payment is None:
        return _UNKNOWN, "this statement states no total monthly payment"
    return (
        str(match.statement_payment),
        f"the servicer bills {match.statement_payment} in total each month",
    )


def _reo_statement_liability_paid_off(
    snapshot: Snapshot, _subject_id: str, subject_raw: object
) -> tuple[JsonValue | None, str]:
    """reo.statement_liability_paid_off — is the liability THIS statement matched marked as retired at
    closing? (LP-575, DT-6's scope)

    DT-6 asks whether the application's stated payment covers the servicer's billed PITIA, and its
    remedy is to RAISE the stated figure to the full payment. That remedy is right only where the
    obligation survives closing. On a refinance the subject property's lien does not: it is paid off,
    and DT-8 is the rule that asks about it. Once someone has answered that question, DT-6 must stop
    recommending the opposite — a processor told to raise a payment AND to remove it is being given
    two contradictory instructions about one debt.

    So this is DT-6's SCOPE, not an outcome. `not_applicable` means the rule is irrelevant to the
    subject's nature (§8), and a statement for a loan being retired is exactly that — the stated and
    billed figures still disagree and always will, they simply stop mattering for the ratio. Calling
    it `satisfied` would be a false all-clear.

    Reads the ONE matcher (ADR-375), so DT-6 cannot end up scoped by a different pairing than the one
    its payment comparison used. Per mortgage statement; DECLINES on any other subject.
    """
    if not isinstance(subject_raw, DocumentEntry):
        return None, "not a document subject"
    if (subject_raw.document_type or "") != _REO_STATEMENT_DOC_TYPE:
        return None, "not a mortgage statement"
    match = _reo_match_statement(snapshot, subject_raw)
    if match.outcome != "matched":
        # An unmatched or ambiguous statement has no liability whose marking could be read. `unknown`
        # keeps DT-6 IN scope, where it resolves to its own couldnt_check — an abstain must not be
        # laundered into a scope exclusion (§8).
        return _UNKNOWN, "this statement was not matched to exactly one stated mortgage liability"
    marked = (match.stated_paid_off or "").strip().casefold() == "true"
    return (
        ("yes" if marked else "no"),
        (
            "the stated liability this statement matches is marked paid off at closing, so its "
            "payment no longer belongs in the debt-to-income ratio at all"
            if marked
            else "the stated liability this statement matches is not marked paid off at closing"
        ),
    )


def _reo_statement_payment_coverage(
    snapshot: Snapshot, _subject_id: str, subject_raw: object
) -> tuple[JsonValue | None, str]:
    """reo.statement_payment_coverage — does the STATED payment cover this statement's PITIA? (DT-6)

    ⚠️ THE STATEMENT'S ``monthly_payment`` IS ALREADY THE PITIA — IT IS NOT ADDED TO ``escrow_amount``.
    The extractor's own prompt defines the fields as ``monthly_payment (number) the total monthly payment
    (principal+interest+escrow)`` and ``escrow_amount (number) the escrow PORTION of the payment``. Escrow
    is a COMPONENT of the total, not an addend. Summing them would double-count escrow on all 50 of the 67
    statements that fill both fields and report a shortfall on nearly every file — the CO-5 mistake (a
    30-day figure compared against a 60-day cap) in a new place. The escrow figure is carried into the
    REASONING instead, because it is usually the EXPLANATION for a real shortfall: a 1003 commonly states
    principal and interest only, and the escrow is exactly the gap.

    ⚠️ NO TOLERANCE BAND, AND THAT IS A CHECKED CONCLUSION, NOT AN OMISSION (ADR-361). No source
    establishes a de-minimis difference between a stated housing payment and a servicer's billed PITIA, so
    any band here would be invented. The comparison is exact, and a difference of any size routes to
    ``needs_review`` — which costs a processor one glance, never an automatic finding.

    ⚠️ UNMATCHED IS ``unknown``, NOT A PASS AND NOT A SECOND REPORT. RE-1 already surfaces an unmatched
    statement; DT-6 cannot compare a payment against a liability it never found, so it abstains rather
    than double-reporting the same discrepancy under a second rule.
    """
    if (
        not isinstance(subject_raw, DocumentEntry)
        or subject_raw.document_type != _REO_STATEMENT_DOC_TYPE
    ):
        return None, "not a mortgage statement — no payment-coverage tag"
    match = _reo_match_statement(snapshot, subject_raw)
    if match.outcome != "matched":
        return _UNKNOWN, (
            "this statement's obligation was not matched to a single stated mortgage liability, so the "
            f"payment stated on the application cannot be compared against it — {match.reason}"
        )
    if match.statement_payment is None:
        return _UNKNOWN, (
            "this mortgage statement states no total monthly payment, so there is nothing to compare the "
            "application's stated payment against"
        )
    if match.stated_payment is None:
        return _UNKNOWN, (
            "the matching liability on the application states no monthly payment, so it cannot be "
            "compared against the statement's total monthly payment"
        )
    escrow_note = (
        f" The statement shows an escrow portion of {match.statement_escrow} within that total, which is "
        "the usual explanation for a short stated figure (a 1003 often carries principal and interest "
        "only)."
        if match.statement_escrow is not None
        else ""
    )
    if match.stated_payment < match.statement_payment:
        return "short", (
            f"the application states a monthly payment of {match.stated_payment} for this liability, but "
            f"the servicer's statement bills a total monthly payment of {match.statement_payment}."
            f"{escrow_note} If the property is being retained, the debt-to-income ratio may understate "
            "this obligation; if it is under contract or being sold, the stated figure may be correct"
        )
    return "covered", (
        f"the application states a monthly payment of {match.stated_payment} for this liability, at or "
        f"above the total monthly payment of {match.statement_payment} the servicer's statement bills"
    )


# --------------------------------------------------------------------------- #
# LP-495a — LO-2, LETTER-OF-EXPLANATION COMPLETENESS.
#
# ⚠️ THE APPROVED DIRECTIVE SAID "explanation_summary + referenced_date + borrower_signature_present,
# document_type-scoped across ALL SIX LOX TYPES". THOSE THREE FIELDS EXIST ON EXACTLY ONE OF THEM.
# Verified against every extractor in `app/ai/extraction/` and against the bench corpus:
#
#     document type                     docs  extractor fields for these three legs
#     letter_of_explanation                9  ALL THREE (summary 9/9, date 6/9, signature 7/9)
#     letter_of_explanation_misc           9  none — issue_orquestion / reason_or_cause / signature_date
#     letter_of_explanation_asset          7  none — source_or_origin_of_funds / letter_date
#     letter_of_explanation_property       7  none — reason_or_cause / letter_date / signature_date
#     letter_of_explanation_income         2  none — reason_or_cause / letter_date / signature_date
#     letter_of_explanation_child_care     0  none — no_expense_reason / letter_date
#     credit_explanation_letter            4  ⚠️ NO EXTRACTOR AT ALL (bench status: `no_extractor`)
#     application_loe                      0  borrower_signature_present only; no summary, no referenced_date
#
# ⚠️ PHASE A'S "9/34 · 6/34 · 7/34" DENOMINATORS ARE THE WHOLE FAMILY, BUT THE NUMERATORS CAN ONLY EVER
# COME FROM THE 9 BASE DOCUMENTS. Read as a sparse fill across 34 letters, those rates invite a rule that
# reports 25 of 34 LOX documents incomplete; read correctly they are 9/9, 6/9 and 7/9 on the ONLY type
# whose extractor has the fields. Building "across all six types" on them would have produced a false
# finding on every letter of the other types — the same shape of error as LP-494's CO-3 drop and LP-495a's
# own RE-1/DT-6 drop: a number believed without checking what its denominator ranged over.
#
# ⚠️ SO THE LEGS ARE NOT ALIASED ONTO THE OTHER TYPES' FIELDS, DELIBERATELY. `letter_date` is when the
# letter was written; `referenced_date` is the date of the event being explained — different facts.
# `borrower_certification` / `accuracy_certification` are a prose attestation; `borrower_signature_present`
# is whether a signature is on the page — different facts. Mapping one onto the other would answer LO-2's
# question with a fact that is not its answer.
#
# ⚠️ EVERY LOE TYPE IS STILL IN SCOPE — NONE IS SILENTLY SKIPPED. A letter whose type carries no
# completeness fields resolves to `unknown` → LO-2 `couldnt_check` ("an explanation letter is on file but
# its completeness cannot be read"), which is a DIFFERENT verdict from "no explanation letter exists" and
# a different verdict from "this letter is incomplete". Fail closed: absent ≠ empty ≠ unknown.
#
# ⚠️ THE AMOUNT LEG IS DELIBERATELY ABSENT. `referenced_amount` fills 0/34 across the family and 0/9 on
# the one type that declares it — the TI-3/4/5 block. A leg that never resolves cannot be load-bearing.
# ⚠️ Only `letter_of_explanation_asset` produces list rows (`transfer_path_or_chronology`, 8 rows); the
# base type's `explanation_items` produces none, so no per-item completeness read is available.
#
# ⚠️ `borrower_signature_present` IS A TYPED EXTRACTOR FIELD, so the catalog's "signature (AI for scans)"
# is STALE — LP-487's question answering yes a sixth time. REPORTED, NOT RE-KINDED: re-kinding needs its
# own Phase A, and rule_kinds.csv stays 135 rows this ticket.
# --------------------------------------------------------------------------- #

# The one document type whose extractor carries all three completeness legs. Named, not inlined, so the
# spec↔code drift test can pin it (the _IH2_MIN_PREFIX_TOKENS lesson).
_LOE_FULL_FIELD_DOC_TYPE = "letter_of_explanation"
# Every LOE-family document type in the classifier catalog. A letter of ANY of these types is in LO-2's
# scope; the ones outside `_LOE_FULL_FIELD_DOC_TYPE` abstain because their extractor has no completeness
# fields, NOT because they are out of scope.
_LOE_DOC_TYPES: frozenset[str] = frozenset(
    {
        "letter_of_explanation",
        "letter_of_explanation_asset",
        "letter_of_explanation_child_care",
        "letter_of_explanation_income",
        "letter_of_explanation_misc",
        "letter_of_explanation_property",
        "credit_explanation_letter",
        "application_loe",
    }
)
# The affirmative vocabulary for `borrower_signature_present` (a free-text yes/no field). An unrecognised
# answer abstains — it is never read as "unsigned", which would be a finding built on a value nobody
# defined (ADR-376's discipline).
_LOE_SIGNATURE_YES: frozenset[str] = frozenset({"yes", "y", "true", "present", "signed"})
_LOE_SIGNATURE_NO: frozenset[str] = frozenset(
    {"no", "n", "false", "absent", "unsigned", "not present"}
)


def _loe_is_explanation_letter(
    _snapshot: Snapshot, _subject_id: str, subject_raw: object
) -> tuple[JsonValue | None, str]:
    """loe.is_explanation_letter — is this document an explanation letter? (LO-2's applicability predicate)

    ⚠️ A SEPARATE PREDICATE TAG EXISTS BECAUSE THE APPLICABILITY DSL HAS ONLY ``eq`` / ``ne``, and LO-2's
    scope is EIGHT document types. Gating on ``document.document_type eq letter_of_explanation`` would
    silently drop the other seven; gating on the completeness tag itself would resolve every NON-letter in
    the file to ``couldnt_check`` (an absent predicate tag is undetermined, not out-of-scope — LP-487), so
    a file of pay stubs would report LO-2 as unchecked on each one.

    Materialises on EVERY document (``yes`` / ``no``), so a non-letter resolves to ``not_applicable`` and
    a letter resolves into scope.
    """
    # Deferred, like every other rule_engine import in this module — importing the package at module
    # level would pull in the evaluators, which import tag_materialization back.
    from app.verification.rule_engine.reasons import document_label

    if not isinstance(subject_raw, DocumentEntry):
        return None, "not a document subject"
    doc_type = subject_raw.document_type
    if doc_type is None or doc_type == _UNKNOWN_DOC_TYPE:
        # An UNCLASSIFIED document cannot be declared "not a letter" — fail closed to unknown so the
        # applicability layer couldnt_checks it rather than skipping a letter nobody typed.
        # THE SENTINEL IS THE SLUG "unknown", NOT None (reported finding). classification.py stores
        # document_type="unknown" both when the model is unsure AND when the call never completed
        # (infra_failure), so checking only None let the real production shape fall through to the
        # confident "no" branch — rendering "this document is a unknown, not an explanation letter", the
        # exact fail-open this comment forbids. RE-1/DT-6 read the same value through the enumerator,
        # which maps it correctly, so LF-6T3N's four unclassified documents couldnt_check'd for them and
        # not_applicable'd here — the split that exposed it.
        return (
            _UNKNOWN,
            "this document has no classified type, so it cannot be ruled out as a letter",
        )
    if doc_type in _LOE_DOC_TYPES:
        return "yes", (
            f"this document is a {document_label(doc_type)}, one of the explanation-letter types"
        )
    return "no", f"this document is a {document_label(doc_type)}, not an explanation letter"


def _loe_completeness(
    _snapshot: Snapshot, _subject_id: str, subject_raw: object
) -> tuple[JsonValue | None, str]:
    """loe.completeness — is THIS explanation letter complete enough to rely on? (LO-2)

    Per LOE-family document: returns ``None`` (DECLINE — no tag materialises) for any other subject.

    ``complete`` (all three legs present) / ``incomplete`` (a leg is missing on a letter whose extractor
    HAS that leg) / ``unknown`` (the letter's type carries no completeness fields, or the signature answer
    is unrecognised). See the module note above for why the other seven types abstain rather than alias
    their own fields onto these three.
    """
    from app.verification.rule_engine.reasons import document_label

    if (
        not isinstance(subject_raw, DocumentEntry)
        or subject_raw.document_type not in _LOE_DOC_TYPES
    ):
        return None, "not a letter of explanation — no completeness tag"
    if subject_raw.document_type != _LOE_FULL_FIELD_DOC_TYPE:
        return _UNKNOWN, (
            f"this file carries a {document_label(subject_raw.document_type or 'letter')}, but that "
            "document type's extraction captures no explanation summary, referenced date or signature "
            "indicator — the letter is present and its completeness cannot be read from it"
        )
    missing: list[str] = []
    if not _entry_text(subject_raw, "explanation_summary"):
        missing.append("a summary of what is being explained")
    if not _entry_text(subject_raw, "referenced_date"):
        missing.append("the date of the event being explained")
    signature = _entry_text(subject_raw, "borrower_signature_present").casefold()
    if not signature:
        missing.append("the borrower's signature")
    elif signature in _LOE_SIGNATURE_NO:
        missing.append("the borrower's signature (the letter is unsigned)")
    elif signature not in _LOE_SIGNATURE_YES:
        return _UNKNOWN, (
            f"the letter's signature indicator reads {signature!r}, which is not a recognised yes/no "
            "answer — abstaining rather than reporting the letter as unsigned"
        )
    if missing:
        return "incomplete", (
            "this letter of explanation is missing "
            + ", ".join(missing)
            + " — a letter an underwriter "
            "can rely on states what is being explained, when it happened, and carries the borrower's "
            "signature"
        )
    return "complete", (
        "this letter of explanation states what is being explained and when, and carries the borrower's "
        "signature"
    )


def _decimal_or_none(tag: Tag | None) -> Decimal | None:
    """A statement balance tag's value as a Decimal, or None (absent / unknown / unparseable)."""
    if tag is None or str(tag.value) == _UNKNOWN:
        return None
    try:
        return Decimal(str(tag.value))
    except (InvalidOperation, ValueError):
        return None


def _date_or_none(tag: Tag | None) -> date | None:
    """A date tag's value as a ``date``, or None (absent / unknown / unparseable) — the
    :func:`_decimal_or_none` counterpart, over the same collapse-to-None convention."""
    if tag is None or str(tag.value) == _UNKNOWN:
        return None
    return coerce_date(str(tag.value))


# --------------------------------------------------------------------------------------------- #
# LP-546 — txn.is_recurring: the "pattern across statements" question, answered deterministically
# --------------------------------------------------------------------------------------------- #
# THIS TAG WAS DECLARED AND UNPRODUCED SINCE THE VOCABULARY WAS WRITTEN, and the reason is recorded
# in activation_bars: "FR-5's declared 'pattern across statements' is unanswerable from a context that
# shows one transaction." That is true of an AI group — the transaction context builder sends ONE
# transaction — and it is not true here. A derived producer receives the whole snapshot, so it can see
# every transaction on the file, which is exactly what recurrence requires.
#
# DERIVED, NOT AI, AND THAT IS THE POINT. Whether the same payee appears in two different months is
# a COUNT, not a judgment: it is decidable from the text, identically on every run, with no calibration
# round and no per-transaction model call. The judgment FR-5 needs — does a recurring debit to an
# undisclosed party imply an obligation — stays with the rule, where an expert can weigh it.
_RECURRENCE_MIN_MONTHS = 2

# Digit runs vary between occurrences of the SAME obligation (a statement reference, a confirmation
# number, a masked card), so they are stripped before grouping. Descriptions arrive with 9+-digit
# identifiers already redacted at rest, which leaves shorter runs like a 4-digit suffix.
_DIGITS = re.compile(r"\d+")
_NON_WORD = re.compile(r"[^A-Z ]+")
# THE REDACTION MARKER MUST GO FIRST, and it is not cosmetic. Descriptions have 9+-digit identifiers
# replaced with "[REDACTED-ID]" at rest, so one occurrence of an obligation can carry the marker where
# the next carries a short reference the redactor left alone. Stripping only digits left
# "UNITEDWHOLESALE LOAN PAYMT REDACTED ID" against "UNITEDWHOLESALE LOAN PAYMT" — the same monthly
# mortgage payment, in two groups, recurring in neither.
_BRACKETED = re.compile(r"\[[^\]]*\]")


def _payee_key(description: str) -> str:
    """A description reduced to the part that is stable across occurrences of the same obligation."""
    stripped = _BRACKETED.sub(" ", description.upper())
    collapsed = _NON_WORD.sub(" ", _DIGITS.sub(" ", stripped))
    return " ".join(collapsed.split())


def txn_is_recurring(
    snapshot: Snapshot, subject_id: str, _subject_raw: object
) -> tuple[JsonValue, str]:
    """txn.is_recurring — does this transaction's payee appear in two or more DISTINCT MONTHS?

    Months, not occurrences. Two charges from the same merchant three days apart are a shopping habit;
    the same payee in two different months is the shape a monthly obligation makes, which is the only
    shape FR-5 is asking about. It also survives the statement boundary: a file carries a month or two
    per statement, so counting occurrences would let one busy month masquerade as a pattern.

    "unknown" when the transaction has no readable description or no date — absent is not "no" (§8), and
    a payee we cannot name cannot be matched against one we can.
    """
    subject = next(
        (txn for txn in all_transactions(snapshot) if txn.content_id == subject_id), None
    )
    if subject is None:
        return _UNKNOWN, "the transaction is not present in this snapshot"
    description = str(subject.description.value or "")
    if not description or not _payee_key(description):
        return (
            _UNKNOWN,
            "the transaction carries no readable description, so its payee cannot be matched",
        )
    key = _payee_key(description)
    months = {
        (parsed.year, parsed.month)
        for txn in all_transactions(snapshot)
        if _payee_key(str(txn.description.value or "")) == key
        and (parsed := coerce_date(str(txn.date.value or ""))) is not None
    }
    if not months:
        return (
            _UNKNOWN,
            "no dated transaction carries this payee, so recurrence cannot be established",
        )
    if len(months) >= _RECURRENCE_MIN_MONTHS:
        return "yes", (
            f"this payee appears in {len(months)} different months across the file's statements"
        )
    return "no", "this payee appears in only one month across the file's statements"


# --------------------------------------------------------------------------------------------- #
# LP-551 — txn.stated_liability_match: does this payment's payee appear on the 1003?
# --------------------------------------------------------------------------------------------- #
# THE INPUT THAT TURNS FR-5 FROM A LIST INTO A FINDING. Without it FR-5 matches every recurring
# payment to a creditor — a mortgage, a card, a utility autopay — which is every file, so it would ask
# a processor to check the borrower's ordinary bills forever. With it the rule fires only on a payee
# that matches NOTHING disclosed, which on LF-WCHG is zero findings.
#
# BY PAYEE, NEVER BY AMOUNT, and LF-WCHG proves why. Citi is debited $3,122.77 a month against a
# disclosed $49.00 — and the $49 is CORRECT: the borrower pays the card in full, and Fannie uses the
# MINIMUM payment for a revolving account in the DTI. An amount comparison would fire a fraud-adjacent
# finding on a borrower doing exactly the right thing, on the first real file it ever saw.
#
# NOT `borrower_name_matching`, deliberately. That matcher is built for PEOPLE — nickname maps
# (Bob/Robert), "Last, First" reordering, generational suffixes. Pointing it at institutions would
# apply nickname logic to lenders. This is a small purpose-built comparison instead, and the
# difference is stated here so the next reader does not "fix" it by reusing the wrong tool.

# Words that carry no identity: every lender has them, so leaving them in makes unrelated payees look
# alike ("X BANK PAYMENT" vs "Y BANK PAYMENT" share two of three tokens).
_GENERIC_PAYEE_WORDS = frozenset(
    {
        "ACH",
        "AUTOPAY",
        "AUTO",
        "PAY",
        "PAYMENT",
        "PAYMT",
        "PMT",
        "BILL",
        "BILLPAY",
        "XFER",
        "TRANSFER",
        "INST",
        "ONLINE",
        "WEB",
        "EPAY",
        "E",
        "DEBIT",
        "DRAFT",
        "RECURRING",
        "BANK",
        "CREDIT",
        "UNION",
        "CARD",
        "CO",
        "COM",
        "CORP",
        "INC",
        "LLC",
        "NA",
        "USA",
        "THE",
        "OF",
        "AND",
        "SVC",
        "SVCS",
        "SERVICES",
        "FINANCIAL",
        "LOAN",
        "MORT",
        "MORTGAGE",
    }
)
_MIN_TOKEN = 4  # below this a shared token is a coincidence, not an identity


def _payee_tokens(raw: str) -> list[str]:
    """A payee reduced to identity-bearing tokens: no digits, no punctuation, no generic finance words."""
    return [t for t in _payee_key(raw).split() if t not in _GENERIC_PAYEE_WORDS]


def _tokens_relate(left: str, right: str) -> bool:
    """Do two identity tokens plausibly name the same institution?

    Equality, or one a PREFIX of the other — which is the shape abbreviation actually takes on a
    statement: "UNITED WHSLE MORT" on the 1003 against "UNITEDWHOLESALE LOAN PAYMT" on the statement
    share no whole token, and only the prefix test relates them.
    """
    if len(left) < _MIN_TOKEN or len(right) < _MIN_TOKEN:
        return False
    return left == right or left.startswith(right) or right.startswith(left)


def txn_stated_liability_match(
    snapshot: Snapshot, subject_id: str, _subject_raw: object
) -> tuple[JsonValue, str]:
    """txn.stated_liability_match — exact / probable / none / unknown.

    "unknown" IS LOAD-BEARING, not a courtesy value. An application that states NO liabilities must
    not read as "nothing matched": that would fire FR-5 on every payment the borrower makes, on the
    files with the least information. Absent is not none (the §8 contract).
    """
    subject = next(
        (txn for txn in all_transactions(snapshot) if txn.content_id == subject_id), None
    )
    if subject is None:
        return _UNKNOWN, "the transaction is not present in this snapshot"
    payee = _payee_tokens(str(subject.description.value or ""))
    if not payee:
        return (
            _UNKNOWN,
            "the transaction names no payee, so it cannot be compared with the application",
        )

    holders = [
        row["holder_name"]
        for row in _stated_liabilities_all(snapshot)
        if str(row.get("holder_name") or "").strip()
    ]
    if not holders:
        return (
            _UNKNOWN,
            "the application states no liability holder to compare this payment against",
        )

    for holder in holders:
        tokens = _payee_tokens(holder)
        if tokens and tokens == payee:
            return "exact", f"the payee matches the stated liability '{holder}'"
    for holder in holders:
        tokens = _payee_tokens(holder)
        if any(_tokens_relate(a, b) for a in payee for b in tokens):
            return "probable", f"the payee resembles the stated liability '{holder}'"
    return "none", (
        f"no liability on the application resembles this payee "
        f"({len(holders)} stated liabilities compared)"
    )


def _stated_liabilities_all(snapshot: Snapshot) -> list[dict[str, str]]:
    """Every stated MISMO liability row, unfiltered by type — the comparison set.

    `_stated_mortgage_liabilities` filters to mortgages for RE-1/DT-6; this comparison must see a card,
    an installment loan and a HELOC too, since those are exactly the recurring debits FR-5 reads.
    """
    if snapshot.mismo.absent:
        return []
    rows: dict[str, dict[str, str]] = {}
    for key, field in snapshot.mismo.facts.items():
        parts = key.split(".")
        if len(parts) != 3 or parts[0] != "liability":
            continue
        _, index, name = parts
        value = field.value if isinstance(field, Field) and field.is_present else None
        if value is None or not str(value).strip():
            continue
        rows.setdefault(index, {})[name] = str(value).strip()
    return [row for _, row in sorted(rows.items(), key=lambda kv: (len(kv[0]), kv[0]))]


def _stmt_continuity(
    snapshot: Snapshot, _subject_id: str, _subject_raw: object
) -> tuple[JsonValue, str]:
    """stmt.continuity — do each account's consecutive statements CHAIN (statement N's ending balance ==
    statement N+1's beginning balance)? Unblocks AS-8.

    Grouped PER ACCOUNT via resolve_accounts (LP-336: institution + masked last-4, fail-closed — a
    guessed merge could fabricate or hide a break) AND PER BORROWER (sub-grouped by each statement's
    belongs_to, so two different borrowers whose accounts collide on the same institution + last-4 never
    chain against each other — the ID-5/IN-6 isolation class), ordered by statement period. DESCRIPTIVE enum:
      * "chained"          — every account with ≥2 statements carries each ending balance into the next
                             opening balance.
      * "broken"           — some account's consecutive balances do NOT carry over (fire-if-any — a break
                             in one account is never masked by a clean one, the _stmt_min_account_months
                             discipline).
      * "nothing_to_chain" — no account has ≥2 statements (a single statement / no statements) → NOTHING
                             to check → lets AS-8 reach not_applicable (NOT couldnt_check — the LP-406-2 trap).
      * "unknown"          — a needed balance/period is unreadable, or statements exist but cannot be
                             grouped to an account → fail-closed (never a false "chained").
    Precedence broken > unknown > chained > nothing_to_chain: a real break is surfaced; an unread account
    never passes as chained. BALANCE-carryover ONLY — the missing-PERIOD dimension is AS-10's (LP-406-2 D4).
    NO threshold: an exact-equality carryover, no tolerance (statement N's ending IS N+1's opening)."""
    # LAZY import (init-order — mirrors _stmt_min_account_months; rule_engine ↔ tag_materialization).
    from app.verification.rule_engine.enumerators import resolve_accounts

    resolved, unresolvable = resolve_accounts(snapshot)
    if not resolved:
        if unresolvable:
            return _UNKNOWN, (
                "bank statements are present but none could be grouped to an account (missing "
                "institution and/or masked account number) — cannot check chaining"
            )
        return "nothing_to_chain", "no bank statements in the file — nothing to chain"

    # PER-BORROWER isolation: chain only WITHIN a single borrower's statements. resolve_accounts groups by
    # (institution, masked last-4) alone, so two DIFFERENT borrowers whose accounts collide on the same
    # last-4 at the same institution would otherwise merge — chaining one borrower's balances against
    # another's (a false break/chain). We sub-group each account by the statement's belongs_to attribution
    # (bank statements carry it, LP-202): a statement chains only against statements with the SAME account
    # AND the same borrower attribution. Unattributed statements share a bucket of their own (never merged
    # with an attributed one). A consistently-attributed joint account (belongs_to {A,B} on every statement)
    # stays one group and still chains. The account_key is retained for the human-readable break locator.
    entries_by_id = (
        {} if snapshot.documents.absent else {e.content_id: e for e in snapshot.documents.entries}
    )

    def _borrower_key(cid: str) -> frozenset[str]:
        entry = entries_by_id.get(cid)
        if entry is None or entry.belongs_to is None:
            return frozenset()
        return frozenset(str(ref.borrower_id) for ref in entry.belongs_to)

    groups: dict[tuple[str, frozenset[str]], list[str]] = {}
    for account_key, content_ids in resolved.items():
        for cid in content_ids:
            groups.setdefault((account_key, _borrower_key(cid)), []).append(cid)

    by_subject = {} if snapshot.tags.absent else snapshot.tags.by_subject
    saw_break = saw_unknown = saw_chained = False
    break_detail: str | None = (
        None  # the FIRST break's account + balances — an ACTIONABLE reason (AS-8 fires
    )
    # on this, and its finding carries this as provenance, so the processor knows WHICH account/gap to fix).
    for (account_key, _borrower), content_ids in groups.items():
        stmts: list[tuple[date, Decimal | None, Decimal | None]] = []
        period_unreadable = False
        for cid in content_ids:
            tags = by_subject.get(cid, {})
            ps = tags.get("stmt.period_start")
            start = (
                coerce_date(str(ps.value)) if ps is not None and str(ps.value) != _UNKNOWN else None
            )
            if start is None:
                period_unreadable = True
                continue
            stmts.append(
                (
                    start,
                    _decimal_or_none(tags.get("stmt.beginning_balance")),
                    _decimal_or_none(tags.get("stmt.ending_balance")),
                )
            )
        if len(stmts) < 2:
            # Fewer than two ORDERABLE statements. If the account actually HAS >= 2 statements but their
            # periods were unreadable (so we could not order them), we cannot confirm chaining → unknown
            # (fail-closed) — including when EVERY period was unreadable (stmts is empty). Only a genuinely
            # single/absent-statement account is nothing-to-chain (the LP-406-2 not_applicable case). Keyed
            # on len(content_ids), NOT len(stmts): the readable count alone cannot tell a 1-statement
            # account from a 2-statement account whose periods were all unreadable.
            if period_unreadable and len(content_ids) >= 2:
                saw_unknown = True
            continue
        if period_unreadable:
            saw_unknown = True  # cannot order this account reliably → cannot confirm it chains
            continue
        stmts.sort(key=lambda s: s[0])
        account_result: str | None = None
        for (_s0, _b0, end_n), (_s1, begin_n1, _e1) in pairwise(stmts):
            if end_n is None or begin_n1 is None:
                account_result = "unknown"  # a balance we could not read → cannot confirm the chain
                break
            if end_n != begin_n1:
                account_result = "broken"
                if break_detail is None:
                    # account_key is "account:{institution}:{masked}" — display-safe by construction (no raw
                    # PII: bank name + masked last-4). Surface a locator + the two mismatched balances so the
                    # processor knows WHICH account and WHERE the chain breaks, not just "some account".
                    parts = account_key.split(":")
                    locator = f"{parts[1]} {parts[-1]}" if len(parts) >= 3 else account_key
                    break_detail = (
                        f"the {locator} account's statements do not chain — an ending balance of {end_n} "
                        f"does not carry into the next statement's opening balance of {begin_n1}"
                    )
                break
        if account_result == "broken":
            saw_break = True
        elif account_result == "unknown":
            saw_unknown = True
        else:
            saw_chained = True

    if saw_break:
        return (
            "broken",
            (
                break_detail  # the specific account + balances (always set when saw_break); fallback defensive
                or "an account's consecutive statements do not chain — an ending balance does not carry into "
                "the next statement's opening balance"
            ),
        )
    if saw_unknown:
        return _UNKNOWN, (
            "a statement's period or balance could not be read (or an account could not be ordered) — "
            "cannot confirm the statements chain"
        )
    if saw_chained:
        return (
            "chained",
            "every account's consecutive statements chain — each ending balance carries into the next "
            "statement's opening balance",
        )
    return "nothing_to_chain", "no account has two or more statements — nothing to chain"


def _income_employer_coverage(
    snapshot: Snapshot, subject_id: str, subject_raw: object
) -> tuple[JsonValue, str]:
    """income.employer_coverage — PER BORROWER: do this borrower's PAY-STUB employers and W-2 employers
    cover each other (every pay-stub employer has a matching W-2 and vice-versa)? Unblocks IN-6.

    Reads the borrower's OWN income documents (belongs_to, via _borrower_attributed_documents — the shared
    per-borrower primitive, LP-385) and partitions income.employer_normalized by document_type. Matching
    uses the SAME deterministic normalization IN-5's exact bookend uses (casefold / drop_punct /
    collapse_ws / strip / drop_entity_suffix — the consistency normalizers), so it introduces NO new
    unmeasured judgment: IN-6 inherits IN-5's MEASURED employer_normalized (100%, LP-379-D). It does NOT
    invoke IN-5's AI fuzzy-residue judge — a DOCUMENTED limitation (a legal-vs-common variance the
    normalizer cannot reduce, e.g. "Acme" vs "Acme Freight", reports "uncovered" where the AI might
    forgive it; that residue is a later refinement — LP-406-3). DESCRIPTIVE enum:
      * "covered"    — both document types present and their normalized employer sets cover each other.
      * "uncovered"  — both present, but a normalized employer on one side has no match on the other.
      * "one_sided"  — the borrower lacks pay stubs OR W-2s (or has neither) → nothing to cross-check →
                       lets IN-6 reach not_applicable (NOT a finding, NOT couldnt_check — the LP-406-2 trap).
      * "unknown"    — an employer name on a relevant document is unreadable → fail-closed.
    NO threshold. Per-borrower: borrower A's documents never cover borrower B's (belongs_to attribution)."""
    # The MISMO index (on subject_raw) is unused — attribution is by the borrower_id (subject_id); the
    # guard mirrors _income_documented_shortfall (a borrower recipe needs a borrower subject).
    if not isinstance(subject_raw, BorrowerSubject):
        return _UNKNOWN, "employer coverage is a per-borrower recipe (needs a borrower subject)"
    if snapshot.documents.absent:
        return (
            "one_sided",
            "no income documents attributed to this borrower — nothing to cross-check",
        )
    if snapshot.tags.absent:
        # Documents may exist but no tags materialized → we could not read any employer → couldnt_check,
        # NOT one_sided (never claim "nothing to cross-check" when we simply could not read the employers).
        return (
            _UNKNOWN,
            "no tags materialized — cannot read this borrower's income-document employers",
        )
    # LAZY imports (init-order — rule_engine/rules ↔ tag_materialization, as _stmt_min_account_months does).
    from app.verification.rule_engine.consistency import _normalize
    from app.verification.rules.specs import load_rule_spec

    # Reuse IN-5's EXACT normalizer chain — SOURCED from IN-5's spec, never a hardcoded copy that could
    # silently drift (IN-5.yaml documents a path to change it: dropping drop_entity_suffix). This keeps
    # IN-6's coverage matching identical to IN-5's measured employer_normalized exact bookend, so IN-6
    # inherits IN-5's calibration (LP-410) with no divergence possible.
    in5_consistency = load_rule_spec("IN-5").consistency
    assert in5_consistency is not None, (
        "IN-6 employer_coverage reuses IN-5's normalizers — IN-5 must remain a consistency rule"
    )
    norm = in5_consistency.normalization
    paystub: dict[
        str, str
    ] = {}  # normalized -> an original rendering (for a human-readable reason)
    w2: dict[str, str] = {}
    paystub_docs = w2_docs = 0
    any_unreadable = False
    for entry in _borrower_attributed_documents(snapshot, subject_id):
        if entry.document_type not in ("pay_stub", "w2"):
            continue
        bucket = paystub if entry.document_type == "pay_stub" else w2
        if entry.document_type == "pay_stub":
            paystub_docs += 1
        else:
            w2_docs += 1
        tag = snapshot.tags.by_subject.get(entry.content_id, {}).get("income.employer_normalized")
        if tag is None or str(tag.value) == _UNKNOWN:
            any_unreadable = True
            continue
        original = str(tag.value)
        bucket[_normalize(original, norm)] = original

    if paystub_docs == 0 or w2_docs == 0:
        return "one_sided", (
            "this borrower has only one of pay stubs / W-2s (or neither) — nothing to cross-check "
            "between the two"
        )
    if any_unreadable or not paystub or not w2:
        return _UNKNOWN, (
            "an employer name on one of this borrower's income documents could not be read — cannot "
            "confirm coverage"
        )
    uncovered = sorted((set(paystub) - set(w2)) | (set(w2) - set(paystub)))
    if uncovered:
        shown = (paystub | w2)[uncovered[0]]
        return "uncovered", (
            f"employer '{shown}' appears on one of the borrower's pay stubs / W-2s but not the other"
        )
    return "covered", (
        "every employer on this borrower's pay stubs also appears on a W-2 and vice-versa"
    )


def _income_is_self_employed(
    snapshot: Snapshot, subject_id: str, subject_raw: object
) -> tuple[JsonValue, str]:
    """income.is_self_employed — PER BORROWER: does this borrower have self-employment income? Unblocks IN-12.

    IN-12 (self-employed borrower needs 2 years' history) enumerates per-borrower but needs a BORROWER-LEVEL
    self-employment signal that did not exist — income.type is subject:document (LP-396 IN-12 bar). This is
    that signal: a DETERMINISTIC promotion of the already-produced income.type (an AI tag, MEASURED via IN-11)
    to the borrower — NO new AI, NO calibration round (the win: it reads the borrower's OWN income documents'
    income.type via _borrower_attributed_documents, the shared per-borrower primitive, LP-385). DESCRIPTIVE
    enum:
      * "yes"     — at least one of the borrower's income documents states income.type == "self_employment".
      * "no"      — the borrower has income documents with a readable type, but NONE is self-employment ->
                    lets IN-12 reach not_applicable (a non-self-employed borrower is out of scope for the
                    2-year self-employment history requirement — the AS-8 not_applicable lesson; an ENUM can
                    carry this, unlike a NUMBER tag — the LP-407-2 D5 gap).
      * "unknown" — no income document is attributed to the borrower, or none carries a readable income.type
                    -> fail-closed (never a fabricated "no").
    LP-422: a SECOND, stronger deterministic source — Schedule C PRESENCE on the borrower's attributed tax
    returns (the LP-421 surfaced DocumentEntry.schedule_c). This is the signal income.type structurally cannot
    carry: self-employment lives on a tax return, which income_amounts (income.type's producer) does not read.
    Presence, NOT net_profit — a Schedule C showing a LOSS is still self-employment (ADR-324: tags describe,
    rules judge; no threshold). Checked FIRST (it needs only the documents, not the tags layer).

    NO threshold. Per-borrower: borrower A's documents never speak for borrower B (belongs_to attribution)."""
    if not isinstance(subject_raw, BorrowerSubject):
        return _UNKNOWN, "self-employment is a per-borrower recipe (needs a borrower subject)"
    if snapshot.documents.absent:
        return (
            _UNKNOWN,
            "this borrower: no documents to read a self-employment signal from",
        )
    # LP-422 — Schedule C presence is a DETERMINISTIC self-employment FACT (a filed Schedule C business).
    for entry in _borrower_attributed_documents(snapshot, subject_id):
        if entry.schedule_c:
            return "yes", (
                "this borrower: an attributed tax return has a Schedule C (a self-employment "
                "business) — presence, not amount (a loss still counts)"
            )
    if snapshot.tags.absent:
        return _UNKNOWN, "this borrower: no tags to read an income type from"
    any_type_seen = False
    for entry in _borrower_attributed_documents(snapshot, subject_id):
        tag = snapshot.tags.by_subject.get(entry.content_id, {}).get("income.type")
        if tag is None or str(tag.value) == _UNKNOWN:
            continue
        any_type_seen = True
        if str(tag.value) == "self_employment":
            return "yes", (
                "this borrower: an income document states self-employment income "
                "(2-year self-employment history applies)"
            )
    if not any_type_seen:
        return _UNKNOWN, (
            "this borrower: no attributed income document carries a readable income type"
        )
    return "no", (
        "this borrower: the borrower's income documents carry income types, none self-employment "
        "(the 2-year self-employment requirement is not applicable)"
    )


def _income_has_rental_income(
    snapshot: Snapshot, subject_id: str, subject_raw: object
) -> tuple[JsonValue, str]:
    """income.has_rental_income — PER BORROWER: does this borrower have rental income? For IN-13's rental scope.

    The rental analog of income.is_self_employed (LP-418/LP-422), with the SAME dual-signal shape:
      1. Schedule E PRESENCE (the LP-421 surfaced DocumentEntry.schedule_e) on the borrower's attributed tax
         returns — the strongest, DETERMINISTIC signal (rental presence is a FACT, not a judgment; ADR-332).
      2. income.type == "rental" on an attributed income document — the softer signal, MIRRORING
         is_self_employed's income.type == "self_employment" fallback. income.type CAN be "rental":
         income_amounts reads the 1003 (applies_to includes uniform_residential_loan_application) and its value
         space includes "rental", so a 1003-declared rental with no Schedule E in the file is still caught. (This
         is a distinct borrower-level DERIVED tag, not a second producer for the AI-only income.type — a tag has
         exactly one producer.) Presence, NOT rents_received / amount: a Schedule E for a property with no rents
         in a given year is still rental activity (ADR-324: tags describe, rules judge; no threshold).
    DESCRIPTIVE enum:
      * "yes"     — an attributed tax return carries a Schedule E, OR an attributed income document is typed
                    income.type == "rental".
      * "no"      — the borrower has a rental-relevant signal that is definitively NOT rental: a filed tax
                    return with no Schedule E, OR readable income.type(s) none of which is rental -> lets IN-13
                    reach not_applicable for a non-rental borrower (an enum can carry this).
      * "unknown" — no tax return AND no readable income type -> fail-closed (never a fabricated "no").
    Per-borrower: borrower A's documents never speak for borrower B (belongs_to attribution)."""
    if not isinstance(subject_raw, BorrowerSubject):
        return _UNKNOWN, "rental income is a per-borrower recipe (needs a borrower subject)"
    if snapshot.documents.absent:
        return _UNKNOWN, "this borrower: no documents to read a rental signal from"
    # 1. Schedule E presence — the DETERMINISTIC signal (needs only the documents, not the tags layer).
    saw_tax_return = False
    for entry in _borrower_attributed_documents(snapshot, subject_id):
        if entry.document_type == "tax_return":
            saw_tax_return = True
            if entry.schedule_e is not None:
                return "yes", (
                    "this borrower: an attributed tax return has a Schedule E (rental income) — "
                    "presence, not amount (a zero-rent year still counts)"
                )
    # 2. income.type == "rental" — the softer signal (mirrors is_self_employed's self_employment fallback).
    any_type_seen = False
    if not snapshot.tags.absent:
        for entry in _borrower_attributed_documents(snapshot, subject_id):
            tag = snapshot.tags.by_subject.get(entry.content_id, {}).get("income.type")
            if tag is None or str(tag.value) == _UNKNOWN:
                continue
            any_type_seen = True
            if str(tag.value) == "rental":
                return "yes", (
                    "this borrower: an income document is typed rental income "
                    "(rental income is stated even without a Schedule E filed)"
                )
    # 3. A definitive "no": a filed tax return with no Schedule E, or readable income types none rental.
    if saw_tax_return or any_type_seen:
        return "no", (
            "this borrower: no Schedule E on any attributed tax return and no income document "
            "typed rental — no rental income evidenced"
        )
    # 4. Nothing to read → fail-closed (never a fabricated "no").
    return _UNKNOWN, (
        "this borrower: no tax return and no readable income type attributed — "
        "cannot tell if the borrower has rental income"
    )


# --------------------------------------------------------------------------- #
# LP-407-2 — the cheap Bucket 2.5 sub-wave: the loan-level tags PC-2 / DT-2 / DT-4 need, all mirroring
# existing producers (no new mechanism). PC-2 gets a document→loan promotion of the contract sales price
# (the contract.loan_closing_date shape); DT-2 / DT-4 get monthly-conversion producers (the
# housing.insurance_monthly shape). THE TAGS DESCRIBE (a number); the rules JUDGE (LP-400). Each fail-
# closes to "unknown" (absent≠0 — a fabricated 0 makes a downstream DTI/compare confidently wrong).
# DT-5 is NOT here: "premium used vs binder" resolves to the binder's annual_premium on BOTH sides (the
# DTI's insurance line and housing.insurance_monthly read the same field), so it is a vacuous self-compare
# with no independent operand today — not wired (LP-407-2 D1).
# --------------------------------------------------------------------------- #


def _loan_sales_price(
    snapshot: Snapshot, _subject_id: str, _subject_raw: object
) -> tuple[JsonValue, str]:
    """contract.loan_sales_price — the loan's single contract sales price, promoted to LOAN level from the
    document-subject contract.sales_price (contract.sales_price itself stays a document fact). Mirrors
    _loan_closing_date (LP-389-A): a loan-enumerated rule cannot read a per-document tag, so PC-2 reads THIS
    loan-level promotion and compares it to the MISMO property.purchase_price. FAIL-CLOSED: no contract sales
    price in the file → unknown; documents that DISAGREE on it → unknown (ambiguous), never a picked value.
    DESCRIPTIVE — the number only; whether it matches the 1003 is PC-2's judgment."""
    if snapshot.tags.absent:
        return _UNKNOWN, "no tags materialized to read a contract sales price from"
    # Dedup by the parsed Decimal (Decimal("365000") == Decimal("365000.00")), so one price rendered two
    # ways is ONE value; >1 distinct value → the documents disagree.
    values: dict[Decimal, str] = {}
    for tags in snapshot.tags.by_subject.values():
        tag = tags.get("contract.sales_price")
        parsed = _decimal_or_none(tag)
        if parsed is not None:
            values[parsed] = str(tag.value)  # type: ignore[union-attr]  # _decimal_or_none None-guards tag
    if not values:
        return _UNKNOWN, "no contract sales price is stated in the file"
    if len(values) > 1:
        return _UNKNOWN, (
            f"the file's documents disagree on the contract sales price "
            f"({', '.join(sorted(values.values()))}) — ambiguous"
        )
    price = next(iter(values))
    return str(price), f"the loan's contract sales price {price} (from the purchase agreement)"


def _housing_taxes_monthly(
    snapshot: Snapshot, _subject_id: str, _subject_raw: object
) -> tuple[JsonValue, str]:
    """housing.taxes_monthly — the loan's monthly property taxes = the extracted ``annual_tax_amount`` on the
    file's property-tax bill ÷ 12. A DERIVED loan recipe mirroring housing.insurance_monthly (LP-374): it
    reads the property_tax_bill DOCUMENT's extracted ``annual_tax_amount`` — the SAME field the DTI reads
    directly (services/dti.py ``_extracted_monthly``). Closes the DTI's last required-input orphan (LP-367 —
    the vocabulary-orphan guard's ``_REQUIRED_DTI_TAGS``); it does NOT feed the DTI (which reads the
    extraction), it closes the orphan and serves the tag's own (inert) consumers DT-1/DT-4.

    AGREES-OR-ABSTAINS (never LOOSER than the DTI): the DTI takes the SINGLE NEWEST bill
    (``created_at`` desc, limit 1); the snapshot exposes no ``created_at`` on a document entry, so we cannot
    replicate its recency pick. We DEDUP by amount instead: bills that AGREE on the annual tax → that amount
    (a re-uploaded bill, or the DTI's value when the newest agrees); bills that DISAGREE (or one states no
    amount) → unknown — cannot tell which is current/subject. RESIDUAL LIMITATION, SHARED WITH THE DTI: with
    no subject-property match, two DIFFERENT properties billed the SAME annual tax both pass through as that
    amount (as the DTI would — it does not subject-match either); a subject-address match is a later
    refinement, not a new mechanism to add here. FAIL-CLOSED (absent≠0 — the fact-tag vocab note): unknown when no property-tax
    bill; the (only) bill states no or a non-positive annual tax; or multiple bills state CONFLICTING amounts.
    Reads ONLY ``property_tax_bill``."""
    if snapshot.documents.absent:
        return _UNKNOWN, "no documents in the file — no property-tax bill to read"
    annuals: set[Decimal] = set()
    bill_count = 0
    unparseable = missing_amount = False
    for entry in snapshot.documents.entries:
        if entry.document_type != "property_tax_bill":
            continue
        bill_count += 1
        field = entry.fields.get("annual_tax_amount")
        if not isinstance(field, Field) or not field.is_present:
            missing_amount = True
            continue
        try:
            annuals.add(Decimal(str(field.value)))
        except (InvalidOperation, ValueError):
            unparseable = True
    if bill_count == 0:
        return _UNKNOWN, "no property-tax bill in the file — property taxes are unknown, not 0"
    if unparseable:
        return _UNKNOWN, "a property-tax bill states an unparseable annual tax amount"
    if len(annuals) > 1:
        return (
            _UNKNOWN,
            f"{bill_count} property-tax bills state conflicting annual tax amounts "
            f"({', '.join(str(a) for a in sorted(annuals))}) — cannot tell which is the subject property's",
        )
    if not annuals:
        return _UNKNOWN, "a property-tax bill is present but states no annual tax amount"
    # Exactly one distinct amount, but a SECOND bill stated none → cannot tell which is current/subject →
    # abstain (mirrors housing.insurance_monthly's missing-premium-with-a-second-doc case).
    if missing_amount:
        return (
            _UNKNOWN,
            f"{bill_count} property-tax bills are present but at least one states no annual tax amount — "
            "cannot tell which is the subject property's",
        )
    annual = next(iter(annuals))
    if annual <= 0:
        return _UNKNOWN, f"the property-tax bill states a non-positive annual tax amount ({annual})"
    monthly = annual / Decimal(12)
    return str(monthly), f"monthly property taxes {monthly} (annual tax {annual} ÷ 12)"


# HOA dues frequency → the number of MONTHS it covers (the divisor to a monthly figure). Kept byte-identical
# to the DTI's _extracted_hoa_monthly map (dti.py). This recipe has NO default — an unmapped frequency FAILS
# CLOSED to unknown (LP-407-2 D3 / ADR-328). An assumed periodicity is a silent 12x miscalculation, so the tag
# abstains rather than assume. NOTE: the DTI ORIGINALLY defaulted an unmapped frequency to monthly (the LP-407-2
# finding); LP-413 fixed that — the DTI now fails closed (gates) on the same input, so the two AGREE (a
# drift-guard test keeps the maps equal). The tag is still stricter-or-equal to the DTI by construction.
_HOA_FREQUENCY_MONTHS = {
    "monthly": 1,
    "quarterly": 3,
    "semiannual": 6,
    "semi-annual": 6,
    "annual": 12,
    "annually": 12,
}


def _housing_hoa_monthly(
    snapshot: Snapshot, _subject_id: str, _subject_raw: object
) -> tuple[JsonValue, str]:
    """housing.hoa_monthly — the loan's monthly HOA dues = the extracted ``dues_amount`` on the file's HOA
    statement, normalized to monthly by the stated ``dues_frequency``. A DERIVED loan recipe mirroring
    housing.insurance_monthly's document→loan read + fail-closed shape, with the same frequency conversion
    the DTI's ``_extracted_hoa_monthly`` uses. On an unstated/unrecognized frequency this tag FAILS CLOSED to
    unknown (an ASSUMED periodicity is a silent 12x miscalculation — LP-407-2 D3). The DTI ORIGINALLY defaulted
    that case to monthly (the LP-407-2 finding); LP-413 fixed it so the DTI now gates too — the two AGREE, the
    tag being stricter-or-equal to the DTI by construction (ADR-328/329).

    FAIL-CLOSED (absent≠0): unknown when no HOA statement (a NO-HOA property's not_applicable is DT-2's
    applicability call — a NUMBER tag cannot carry a not_applicable enum, LP-407-2 D5); the statement states
    no or a non-positive dues amount; the dues frequency is unstated or unrecognized; or multiple statements
    state CONFLICTING monthly dues. Reads ONLY ``hoa_statement``."""
    if snapshot.documents.absent:
        return _UNKNOWN, "no documents in the file — no HOA statement to read"
    monthlies: set[Decimal] = set()
    stmt_count = 0
    problem: str | None = (
        None  # the FIRST problem encountered (kept via `problem or …`), a stable reason
    )
    for entry in snapshot.documents.entries:
        if entry.document_type != "hoa_statement":
            continue
        stmt_count += 1
        dues_field = entry.fields.get("dues_amount")
        if not isinstance(dues_field, Field) or not dues_field.is_present:
            problem = problem or "an HOA statement states no dues amount"
            continue
        try:
            dues = Decimal(str(dues_field.value))
        except (InvalidOperation, ValueError):
            problem = problem or "an HOA statement states an unparseable dues amount"
            continue
        if dues <= 0:
            problem = problem or f"an HOA statement states a non-positive dues amount ({dues})"
            continue
        freq_field = entry.fields.get("dues_frequency")
        freq = (
            str(freq_field.value).strip().lower()
            if isinstance(freq_field, Field) and freq_field.is_present
            else ""
        )
        months = _HOA_FREQUENCY_MONTHS.get(freq)
        if months is None:
            problem = problem or (
                f"an HOA statement's dues frequency is unstated or unrecognized ({freq or 'absent'!r}) — "
                "cannot convert to monthly without assuming a periodicity"
            )
            continue
        monthlies.add(dues / Decimal(months))
    if stmt_count == 0:
        return _UNKNOWN, "no HOA statement in the file — HOA dues are unknown, not 0"
    if problem is not None:
        return _UNKNOWN, problem
    if len(monthlies) > 1:
        return (
            _UNKNOWN,
            f"{stmt_count} HOA statements state conflicting monthly dues "
            f"({', '.join(str(m) for m in sorted(monthlies))}) — cannot tell which applies",
        )
    monthly = next(iter(monthlies))
    return str(
        monthly
    ), f"monthly HOA dues {monthly} (from the HOA statement's stated dues and frequency)"


def _borrower_termination(snapshot: Snapshot, borrower_id: str) -> tuple[str, date | None]:
    """PER BORROWER (LP-430): the borrower's employment-termination documentation status, from
    income.employment_end (parsed off the VOE) + income.pay_date over the borrower's ATTRIBUTED
    documents (belongs_to — a borrower's own documents never speak for another's).

    Returns ``(status, most_recent_past_end_date)``:
      * ``("needs_pay_stub", end)`` — a PAST end date with NO pay stub dated after it (IN-15 fires).
      * ``("cleared", end)``        — a past end date + a pay stub dated AFTER it (IN-15 satisfied).
      * ``("not_terminated", None)``— no readable PAST end date (no VOE / current / a FUTURE end date
                                      only) → IN-15 not_applicable.
      * ``("unknown", None)``       — the documents/tags section cannot be read (fail-closed).

    Priya's ruling (B14 → LP-430): ANY end date in the PAST is a termination (no grace period); ONE
    subsequent pay stub — from ANY employer (a new job clears it more convincingly than the same one),
    dated AFTER the end date — clears it. Deterministic (two date facts): no AI, no threshold. An
    UNREADABLE end date on a present VOE is an ABSENT income.employment_end tag (parsed dates are
    date-or-absent), indistinguishable from no-VOE without the AI voe_present tag — so it lands in
    not_terminated (the never-accuse choice), a documented limitation of the no-AI design (LP-430 D4)."""
    if snapshot.documents.absent or snapshot.tags.absent:
        return _UNKNOWN, None
    file_date = snapshot.created_at.date()
    end_dates: list[date] = []
    pay_dates: list[date] = []
    for entry in _borrower_attributed_documents(snapshot, borrower_id):
        tags = snapshot.tags.by_subject.get(entry.content_id, {})
        end_tag = tags.get("income.employment_end")
        if end_tag is not None and str(end_tag.value) != _UNKNOWN:
            parsed = coerce_date(str(end_tag.value))
            if parsed is not None:
                end_dates.append(parsed)
        pay_tag = tags.get("income.pay_date")
        if pay_tag is not None and str(pay_tag.value) != _UNKNOWN:
            parsed = coerce_date(str(pay_tag.value))
            if parsed is not None:
                pay_dates.append(parsed)
    past_ends = [d for d in end_dates if d < file_date]
    if not past_ends:
        return "not_terminated", None
    end = max(
        past_ends
    )  # the MOST RECENT termination — the date a clearing pay stub must post-date
    if any(p > end for p in pay_dates):
        return "cleared", end
    return "needs_pay_stub", end


def _income_terminated_employment(
    snapshot: Snapshot, subject_id: str, subject_raw: object
) -> tuple[JsonValue, str]:
    """income.terminated_employment — LP-430: does the borrower have a terminated (past end date)
    employment a subsequent pay stub has NOT cleared? Priya's B14 separate documentation check. The
    reason ASKS FOR THE DOCUMENT (a missing pay stub is a file gap), never asserts unemployment."""
    if not isinstance(subject_raw, BorrowerSubject):
        return (
            _UNKNOWN,
            "terminated-employment documentation is a per-borrower recipe (needs a borrower subject)",
        )
    status, end = _borrower_termination(snapshot, subject_id)
    reasons = {
        "needs_pay_stub": (
            f"this borrower: employment shown as ended {end} with no pay stub dated after it — "
            "a pay stub dated after that is needed to confirm current employment"
        ),
        "cleared": (
            f"this borrower: employment ended {end}, but a pay stub dated after it confirms "
            "current employment"
        ),
        "not_terminated": (
            "this borrower: no employment end date in the past — not a terminated job"
        ),
        "unknown": "this borrower: employment-termination documentation cannot be read",
    }
    return status, reasons[status]


def _income_terminated_employment_end_date(
    snapshot: Snapshot, subject_id: str, subject_raw: object
) -> tuple[JsonValue, str]:
    """income.terminated_employment_end_date — LP-430: the most recent PAST employment end date, for
    IN-15's reason interpolation. A real date when terminated_employment is cleared/needs_pay_stub;
    "unknown" otherwise (no past end date to name)."""
    if not isinstance(subject_raw, BorrowerSubject):
        return _UNKNOWN, "a per-borrower recipe (needs a borrower subject)"
    _status, end = _borrower_termination(snapshot, subject_id)
    if end is None:
        return _UNKNOWN, "this borrower: no past employment end date to name"
    return (
        end.isoformat(),
        f"this borrower: most recent past employment end date is {end.isoformat()}",
    )


def _income_history_documentation(
    snapshot: Snapshot, subject_id: str, subject_raw: object
) -> tuple[JsonValue, str]:
    """income.history_documentation — LP-433: what documents evidence the borrower's income history? Priya's
    B12 ruling — a 2-year history cannot rest on pay stubs alone; a W-2 or 1099 is required (the sibling of
    IN-15's B14 check). A DETERMINISTIC document-type PRESENCE read (the IN-8/IN-9 discipline — the type label,
    not extracted fields, so the unvalidated 1099 extractor does not narrow the ruling) over the borrower's
    OWN attributed documents (belongs_to — a borrower's documents never speak for another's, LP-385). No AI, no
    threshold. Option 1 (LP-432/LP-433 D1): fire on pay-stub-only, flagged for Priya (a VOE-documented borrower
    with no W-2/1099 also fires — the over-fire the bar records)."""
    if not isinstance(subject_raw, BorrowerSubject):
        return (
            _UNKNOWN,
            "income-history documentation is a per-borrower recipe (needs a borrower subject)",
        )
    if snapshot.documents.absent:
        return _UNKNOWN, "this borrower: no documents to read an income-history basis from"
    types = {entry.document_type for entry in _borrower_attributed_documents(snapshot, subject_id)}
    if types & {"w2", "1099"}:
        return "w2_or_1099", (
            "this borrower: a W-2 or 1099 is attributed — the two-year income history can be "
            "established"
        )
    if "pay_stub" in types:
        return "pay_stub_only", (
            "this borrower: income is evidenced only by pay stubs (no W-2 or 1099 attributed)"
        )
    return "no_pay_stubs", (
        "this borrower: no pay stubs attributed, so there is no pay-stub-only history"
    )


# --------------------------------------------------------------------------- #
# LP-496a — program eligibility (PE-1, PE-3).
# --------------------------------------------------------------------------- #
# PE-1's reference values. FHFA, "Conforming Loan Limit Values for 2026", page dated 2025-11-25
# (tier P, fetched 2026-08-13). Pinned to PE-1.yaml's reference_values by test.
#
# THE LIMIT IS A LOOKUP, NOT A CONSTANT — it varies by COUNTY, by UNIT COUNT and by YEAR, and the
# snapshot carries none of the three well enough to key one. What IS knowable without a county is the
# pair of BOUNDS the county-specific limit must lie between: no county's one-unit limit is below the
# baseline, and none exceeds the high-cost ceiling. So the comparison is decidable at the two ends and
# GENUINELY UNDECIDABLE in the band between them, where the answer depends on which county the property
# sits in. The band ABSTAINS. It must never clear: clearing it would pass a high-cost-county jumbo,
# which is the exact failure "the jumbo catch" exists to prevent.
_CONFORMING_BASELINE_1_UNIT = Decimal("832750")
_CONFORMING_CEILING_1_UNIT = Decimal("1249125")
# Alaska, Hawaii, Guam and the U.S. Virgin Islands take the ceiling AS their baseline, and 150% of it
# as their own ceiling. A statutory carve-out, not a high-cost designation.
_CONFORMING_SPECIAL_AREA_STATES = frozenset({"AK", "HI", "GU", "VI"})
_CONFORMING_SPECIAL_BASELINE_1_UNIT = Decimal("1249125")
_CONFORMING_SPECIAL_CEILING_1_UNIT = Decimal("1873675")

# PE-3's reference values. HUD Handbook 4000.1, Effective 09/14/2015 | Last Revised 08/14/2019
# (tier P, read directly from HUD's hosted PDF 2026-08-13).
_FHA_MRI_RATE = Decimal("0.035")  # "at least 3.5 percent of the Adjusted Value"
_FHA_MRI_RATE_LOW_SCORE = Decimal("0.10")  # 500-579 -> max LTV 90%, i.e. a 10% investment
_FHA_MDCS_FULL_FINANCING = 580  # "at or above 580 -> eligible for maximum financing"
_FHA_MDCS_FLOOR = 500  # "not eligible ... if the MDCS is less than 500"


def _program_type(snapshot: Snapshot) -> str | None:
    """The loan's program, lowercased — or None when the file does not state one."""
    values = {v.lower() for v in _parsed_strings(snapshot, "program.type")}
    if len(values) != 1:
        return None  # absent, or two programs on one file — either way, not a program to judge
    return next(iter(values))


def _loan_amount(snapshot: Snapshot) -> tuple[Decimal | None, str | None]:
    """The MISMO base loan amount as a Decimal, or (None, reason)."""
    raw = _parsed_strings(snapshot, "loan.amount")
    if not raw:
        return None, "the file does not state the loan amount"
    try:
        return Decimal(raw[0].replace(",", "").replace("$", "").strip()), None
    except (InvalidOperation, ValueError):
        return None, f"the loan amount reads {raw[0]!r}, which is not a number"


def _program_conforming_eligibility(
    snapshot: Snapshot, _subject_id: str, _subject_raw: object
) -> tuple[JsonValue, str]:
    """program.conforming_eligibility — is this conventional loan within the conforming limit? (PE-1)

    THE HIGH-COST BAND ABSTAINS, AND THAT IS THE WHOLE DESIGN. The applicable limit depends on the
    property's COUNTY, which does not reach the snapshot: MISMO parses <CountyName> (parser.py) into
    mismo/schema.py, but the Property model has no county column, so it is dropped before projection.
    Comparing against the baseline alone would clear every high-cost-county loan between the baseline
    and the ceiling — files that ARE conforming in San Francisco and ARE jumbo in most of the country.
    Below the baseline every county agrees it conforms; above the ceiling every county agrees it does
    not. In between, only the county decides, so the tag says so instead of guessing.
    """
    program = _program_type(snapshot)
    if program is None:
        return _UNKNOWN, (
            "the file does not state a single loan program, so the conforming limit that applies "
            "cannot be selected"
        )
    if program != "conventional":
        return "n/a", (
            f"the loan program is {program} — the FHFA conforming loan limit applies to conventional "
            "loans"
        )

    amount, problem = _loan_amount(snapshot)
    if amount is None:
        return _UNKNOWN, f"{problem} — the conforming limit cannot be checked without it"

    units_raw = _mismo_str(snapshot, "property.financed_unit_count")
    # LP-498 review — AN ABSENT UNIT COUNT ABSTAINS, and it silently did not. `units` stayed None when
    # the fact was missing, and the `units is not None and units > 1` guard below therefore did not
    # fire, so the loan fell through to the ONE-UNIT limits. LP-496a measured this fact reaching the
    # snapshot on 10 of 19 files, so about half took that path: a 3-unit purchase at $1,400,000 with no
    # stated unit count fired "jumbo, not deliverable", when the 2026 three-unit high-cost ceiling is
    # far above it. The comment below explains carefully why a KNOWN multi-unit abstains — the same
    # uncertainty applies when the count is unknown, and AS-4's sibling recipe already abstains here.
    if units_raw is None:
        return _UNKNOWN, (
            "the file does not state the financed unit count, and the conforming limit depends on it — "
            "the one-unit values are the only ones verified against FHFA's published release, so "
            "abstaining rather than assuming one unit, which would report a 2-4 unit file against the "
            "wrong limit"
        )
    try:
        units = int(Decimal(units_raw))
    except (InvalidOperation, ValueError):
        return _UNKNOWN, (
            f"the financed unit count reads {units_raw!r}, which is not a number — the conforming "
            "limit depends on the unit count"
        )
    # The unit count changes the limit. The 2-4 unit values were NOT verified against a primary source
    # (FHFA's release states one-unit figures only; the multi-unit table ships inside a downloadable
    # county file), so a multi-unit loan abstains rather than being judged against an unverified number.
    if units > 1:
        return _UNKNOWN, (
            f"the property is financed as {units} units, and the 2-4 unit conforming limits are not "
            "carried — only the one-unit values are verified against FHFA's published release"
        )

    # LP-498 review — the same defaulting on the STATE. `(... or "").upper()` made an absent state code
    # a non-special area, so an Alaska / Hawaii / Guam / USVI file with no stated state was judged
    # against the national limits and could fire falsely — those areas carry a HIGHER baseline and
    # ceiling, so the error direction is a spurious "exceeds limit".
    state_raw = _mismo_str(snapshot, "property.state")
    if state_raw is None:
        return _UNKNOWN, (
            "the file does not state the property's state, and Alaska, Hawaii, Guam and the U.S. "
            "Virgin Islands carry higher conforming limits than the rest of the country — abstaining "
            "rather than applying the national limits to a property that may not be subject to them"
        )
    state = state_raw.upper()
    special = state in _CONFORMING_SPECIAL_AREA_STATES
    baseline = _CONFORMING_SPECIAL_BASELINE_1_UNIT if special else _CONFORMING_BASELINE_1_UNIT
    ceiling = _CONFORMING_CEILING_1_UNIT if not special else _CONFORMING_SPECIAL_CEILING_1_UNIT
    area = f" for {state}" if special else ""

    if amount > ceiling:
        return "exceeds_limit", (
            f"the loan amount of ${amount:,.2f} exceeds ${ceiling:,.2f}, the highest 2026 one-unit "
            f"conforming limit any county reaches{area} — it is above the limit in every county, so no "
            "county lookup is needed to say so"
        )
    if amount <= baseline:
        return "within_limit", (
            f"the loan amount of ${amount:,.2f} is at or below the ${baseline:,.2f} 2026 one-unit "
            f"baseline conforming limit{area} — it is within the limit in every county"
        )
    return _UNKNOWN, (
        f"the loan amount of ${amount:,.2f} falls between the ${baseline:,.2f} baseline and the "
        f"${ceiling:,.2f} high-cost ceiling{area}, where the applicable limit depends on the property's "
        "county — and the county does not reach the snapshot. Abstaining rather than clearing a loan "
        "that may be over its county's limit"
    )


def _fha_min_investment_met(
    snapshot: Snapshot, _subject_id: str, _subject_raw: object
) -> tuple[JsonValue, str]:
    """program.fha_min_investment_met — MRI of 3.5% of the Adjusted Value? (PE-3)

    THE BASIS IS ADJUSTED VALUE, NOT PURCHASE PRICE. 4000.1: "For purchase transactions, the Adjusted
    Value is the lesser of: purchase price less any inducements to purchase; or the Property Value."
    On a low appraisal the two differ, and using price would clear a file that fails.

    TWO HONEST LIMITS, both stated on the finding rather than papered over:
      1. INDUCEMENTS ARE NOT REPRESENTABLE. Nothing in the snapshot carries seller inducements (PC-8
         surfaces personal property but computes no deduction, LP-493). Omitting the deduction can only
         RAISE the Adjusted Value, which RAISES the required investment — so the rule can never clear a
         file it should catch on this axis; it can only over-ask. That asymmetry is why it ships.
      2. THE TIER IS NOT ASSUMED. The MRI is 3.5% at MDCS >= 580 and 10% at 500-579, and below 500 the
         borrower is not eligible at all. The Minimum Decision Credit Score reaches the snapshot on
         almost no file, and assuming 580+ would apply the cheapest tier to a borrower who may not
         qualify for it. No score -> abstain.
    """
    program = _program_type(snapshot)
    if program is None:
        return _UNKNOWN, (
            "the file does not state a single loan program, so it is not known whether FHA's minimum "
            "required investment applies"
        )
    if program != "fha":
        return _UNKNOWN, (
            f"the loan program is {program} — FHA's minimum required investment applies to FHA loans"
        )

    price_raw = _mismo_str(snapshot, "property.purchase_price")
    # LP-498 review — THE VALUE IS THE APPRAISER'S, NOT THE APPLICATION'S. This read
    # `property.valuation_amount or property.estimated_value` — both MISMO STATED figures, with
    # `estimated_value` being the borrower's own estimate off the 1003 — and never consulted
    # `property.appraised_value`, the tag scoped to the appraisal document. That is the exact fallback
    # `_conservative_appraised_value`'s docstring records as the bug that made PR-2 answer "the
    # appraised value supports the purchase price" on a file with no appraisal.
    #
    # It matters here because HUD's Adjusted Value is the lesser of price and APPRAISED value, so the
    # stated figure defeats the rule on precisely the file it exists to catch: price 400,000 with a
    # 1003 estimate of 400,000 and an appraisal at 360,000 computes an MRI of 14,000 against a 52,000
    # investment (satisfied), where the real numbers are 12,600 against 12,000 (fired). PE-3's own
    # how_to_fix tells the processor to "obtain the appraisal (for the property value)" — which could
    # not change the verdict while the appraisal was not read.
    #
    # No appraisal states a value -> ABSTAIN. The Adjusted Value is not computable without it, and a
    # stated-value substitute is the false-green above.
    appraised = _appraised_value_from_appraisal(snapshot)
    if price_raw is None or appraised is None:
        missing = (
            "purchase price" if price_raw is None else "an appraisal stating the appraised value"
        )
        return _UNKNOWN, (
            f"the file does not carry {missing}, and the Adjusted Value is the lesser of the purchase "
            "price and the APPRAISED value — it cannot be computed from one"
        )
    try:
        price = Decimal(price_raw.replace(",", "").replace("$", "").strip())
    except (InvalidOperation, ValueError):
        return (
            _UNKNOWN,
            "the purchase price is not a number, so the Adjusted Value cannot be computed",
        )
    if price <= 0:
        return _UNKNOWN, (
            "the purchase price is zero or negative, so the Adjusted Value cannot be computed"
        )

    adjusted_value = min(price, appraised)

    score, score_reason = _fha_minimum_decision_credit_score(snapshot)
    if score is None:
        return _UNKNOWN, (
            f"{score_reason} — FHA's minimum required investment is 3.5% of the Adjusted Value at a "
            "Minimum Decision Credit Score of 580 or above and 10% between 500 and 579, so the "
            "requirement cannot be set without the score"
        )
    if score < _FHA_MDCS_FLOOR:
        return "no", (
            f"the Minimum Decision Credit Score of {score} is below {_FHA_MDCS_FLOOR} — the borrower is "
            "not eligible for FHA-insured financing at any investment level (HUD 4000.1)"
        )
    rate = _FHA_MRI_RATE if score >= _FHA_MDCS_FULL_FINANCING else _FHA_MRI_RATE_LOW_SCORE
    required = (adjusted_value * rate).quantize(Decimal("0.01"))

    amount, problem = _loan_amount(snapshot)
    if amount is None:
        return _UNKNOWN, (
            f"{problem} — the borrower's investment is the Adjusted Value less the loan amount, so it "
            "cannot be computed without it"
        )
    investment = adjusted_value - amount
    basis = (
        "the purchase price"
        if price <= appraised
        else "the appraised value (below the purchase price)"
    )
    pct = f"{rate * 100:.1f}".rstrip("0").rstrip(".")
    if investment >= required:
        return "yes", (
            f"the borrower's investment of ${investment:,.2f} meets the ${required:,.2f} required — "
            f"{pct}% of an Adjusted Value of ${adjusted_value:,.2f}, taken from {basis}, at a Minimum "
            f"Decision Credit Score of {score}"
        )
    return "no", (
        f"the borrower's investment of ${investment:,.2f} falls short of the ${required:,.2f} required "
        f"— {pct}% of an Adjusted Value of ${adjusted_value:,.2f}, taken from {basis}, at a Minimum "
        f"Decision Credit Score of {score}. Note the Adjusted Value is computed WITHOUT deducting "
        "inducements to purchase, which the file does not carry; a seller credit would lower it and "
        "lower the requirement with it"
    )


def _fha_minimum_decision_credit_score(snapshot: Snapshot) -> tuple[int | None, str]:
    """The MDCS: the MIDDLE of the three repository scores, and the LOWEST across borrowers.

    4000.1: "the Mortgagee must select the lowest MDCS of the Borrower(s) with credit score(s)". Per
    borrower the decision score is the middle of three (or the lower of two); across borrowers the
    lowest of those wins. Abstains on no score at all rather than assuming a tier.

    LP-498 review — THE GRANULARITY IS PER DOCUMENT, NOT PER BORROWER, and the gap is now guarded
    rather than only described. The loop keys on documents, and the credit-report extractor carries one
    score triple per document, so "the lowest across borrowers" holds only when every borrower has a
    score-bearing report. A two-borrower file with a single joint report yields ONE triple: if it is
    the primary's 700 while the co-borrower sits at 550, PE-3 would apply the 3.5% tier to a file that
    requires 10% — the assumption this function's own contract says it will never make. So when the
    file has more borrowers than score-bearing credit reports, it abstains.
    """
    per_document: list[int] = []
    for entry in () if snapshot.documents.absent else snapshot.documents.entries:
        scores: list[int] = []
        for key in ("score_equifax", "score_experian", "score_transunion"):
            field = entry.fields.get(key)
            # A plain Field, never a PiiField — the guard is semantic as well as type-level: a score
            # arriving masked carries no comparable number, and reading one would produce a tier from
            # a redaction. An unusable score is skipped, and if every score is skipped the caller
            # abstains rather than assuming a tier.
            if not isinstance(field, Field) or not field.is_present:
                continue
            try:
                scores.append(int(Decimal(str(field.value).strip())))
            except (InvalidOperation, ValueError):
                continue
        if not scores:
            continue
        scores.sort()
        # three -> the middle; two -> the lower; one -> itself.
        per_document.append(scores[1] if len(scores) >= 3 else scores[0])
    if not per_document:
        return None, "no credit report on the file states a repository credit score"
    # The borrower set is the distinct belongs_to refs across the documents — the same derivation the
    # rule engine's per_borrower enumerator uses, so the two cannot disagree about how many borrowers
    # the file has.
    borrowers = {
        str(ref.borrower_id)
        for entry in (() if snapshot.documents.absent else snapshot.documents.entries)
        if entry.belongs_to
        for ref in entry.belongs_to
    }
    if len(borrowers) > len(per_document):
        return None, (
            f"the file has {len(borrowers)} borrowers but only {len(per_document)} credit "
            f"{'report states' if len(per_document) == 1 else 'reports state'} a repository score — "
            "the decision score is the LOWEST across borrowers, and a borrower with no score on file "
            "could be below the one found, so the tier cannot be selected"
        )
    return min(per_document), ""


_RECIPES: dict[str, Recipe] = {
    "app_required_fields_present": _app_required_fields_present,
    "program_conforming_eligibility": _program_conforming_eligibility,  # LP-496a — PE-1
    "fha_min_investment_met": _fha_min_investment_met,  # LP-496a — PE-3
    "property_type": _property_type,  # LP-509-B1 — stated, else the MISMO project indicators
    # LP-323-IN-B — the income family's loan-level arithmetic (per-borrower granularity is deferred:
    # the derived producer is loan-only, so these aggregate the file like the DTI calc does — see the
    # LP-323-IN-B doc). Registry entries only; produce_derived_tags is untouched (the wave criterion).
    "income_documented_shortfall": _income_documented_shortfall,
    "income_ytd_annualized_shortfall": _income_ytd_annualized_shortfall,
    # LP-389-A — ID-5's per-borrower inputs: the borrower's attributed-ID expiration + the loan's one
    # closing date (both promotions of document facts, reusing LP-385's belongs_to attribution).
    "borrower_id_expiration": _borrower_id_expiration,
    "loan_closing_date": _loan_closing_date,
    # LP-417 — the loan's homeowners-insurance effective date (promoted from the document-subject
    # ins.effective_date), for IH-3 (effective <= closing). Mirrors loan_closing_date + the multi-binder abstain.
    "loan_effective_date": _loan_effective_date,
    "ins_policy_expired": _ins_policy_expired,  # LP-509-D1 — IH-9
    # LP-447 — the homeowners binder's DWELLING loss-settlement basis, normalised to replacement_cost /
    # actual_cash_value / unknown, for IH-1 (insurance adequacy, ADR-340). Per-document; fails closed on an
    # unrecognised value; reads ONLY the typed field, never forms_and_endorsements (the anti-conflation).
    "dwelling_settlement_basis": _dwelling_settlement_basis,
    "property_value_basis": _property_value_basis,  # LP-488 — MI-1
    "loan_ltv_percent": _loan_ltv_percent,
    # LP-597 — MI-1 must not clear an MI requirement off the borrower's own estimate of value.
    "loan_ltv_basis_is_appraised": _loan_ltv_basis_is_appraised,  # LP-488 — MI-1
    "fha_ufmip_percent": _fha_ufmip_percent,  # LP-488 — MI-4
    "condo_questionnaire_present": _condo_questionnaire_present,  # LP-488 — CO-1
    "title_vested_owner_matches": _title_vested_owner_matches,  # LP-491 — TI-1
    "title_chain_transfer_count": _title_chain_transfer_count,  # LP-491 — TI-6
    "title_chain_has_gap": _title_chain_has_gap,  # LP-491 — TI-6
    "title_chain_shortest_interval": _title_chain_shortest_interval,  # LP-491 — TI-6
    "property_value_vs_price_gap": _property_value_vs_price_gap,  # LP-492 — PR-2
    "property_condition_rating": _property_condition_rating,  # LP-492 — PR-5
    "property_appraisal_address_match": _property_appraisal_address_match,  # LP-492 — PR-7
    "aus_recommendation": _aus_recommendation,  # LP-488 — AU-3
    "derogatory_months_elapsed": _derogatory_months_elapsed,  # LP-490 — CR-6
    "collection_aggregate_balance": _collection_aggregate_balance,
    # LP-490 review — CR-10's missing inputs: the per-collection figure its DU matrix asks about, and the
    # applicability gate its own trigger prose already described.
    "credit_largest_single_collection_balance": _collection_largest_single_balance,
    "credit_has_collections": _has_collections,  # LP-490 — CR-10
    "mortgagee_clause_correct": _mortgagee_clause_correct,  # LP-487 — IH-2
    "condo_master_policy": _condo_master_policy,  # LP-487 — IH-7
    # LP-494 review — the 60-day delinquency rate the B4-2.2-02 citation actually names.
    "condo_delinquent_60day_pct": _condo_delinquent_60day_pct,
    "condo_fidelity_coverage": _condo_fidelity_coverage,  # LP-494 — CO-3
    "condo_reserve_adequacy": _condo_reserve_adequacy,  # LP-494 — CO-4
    "condo_project_eligibility": _condo_project_eligibility,  # LP-494 — CO-5
    # LP-495a — ⚠️ ONE MATCHER, TWO RULES (ADR-375). Both recipes call `_reo_match_statement`; RE-1 reads
    # the disclosure question, DT-6 the payment question, so the two rules cannot disagree about which
    # stated liability a statement matched. Neither asserts retention and neither can fire.
    "reo_statement_disclosure": _reo_statement_disclosure,  # LP-495a — RE-1
    "reo_statement_payment_coverage": _reo_statement_payment_coverage,  # LP-495a — DT-6
    # LP-495a — LO-2's completeness read + the applicability predicate its 8-type scope needs (the
    # applicability DSL has only eq/ne).
    "loe_is_explanation_letter": _loe_is_explanation_letter,  # LP-495a — LO-2 scope
    "loe_completeness": _loe_completeness,  # LP-495a — LO-2
    # LP-453 — DETERMINISTIC numeric observations over the credit report's tradelines list (loan-level). Pure
    # aggregates only (count + monthly-payment total) — the open-ended bureau vocabulary makes classification a
    # Priya/AI question (ADR). Fail closed: no tradelines → absent, never a fabricated 0.
    "credit_undisclosed_tradeline": _credit_undisclosed_tradeline,
    "credit_tradeline_count": _credit_tradeline_count,
    "credit_tradeline_monthly_payment_total": _credit_tradeline_monthly_payment_total,
    # LP-407-4 — does the purchase contract's subject-property address match the loan file's (MISMO)? For PC-3.
    # DESCRIPTIVE enum (yes/no/unknown); PC-3 routes "no" to needs_review (ADR-325). Reuses the consistency
    # normalizers; reads the MISMO SUBJECT address (never a mailing address / a retained-property tax bill).
    "property_address_match": _property_address_match,
    # LP-366-A — the loan's total stated qualifying income, read by AS-1 via a `loan_tag` operand
    # (instead of the gated DTI calc). Fail-closed to unknown, never 0.
    "qualifying_income_monthly": _qualifying_income_monthly,
    "income_max_employment_gap": _income_max_employment_gap,
    "income_days_since_recent_pay": _income_days_since_recent_pay,
    # LP-371 — the loan's stated occupancy, mapped from MISMO to the tag's enum (OC-2's load-bearing tag).
    "occupancy_stated": _occupancy_stated,
    # LP-374 — the loan's monthly homeowners (hazard) insurance from the binder's annual_premium ÷ 12
    # (the DTI's last vocabulary orphan). Fail-closed to unknown, never 0.
    "housing_insurance_monthly": _housing_insurance_monthly,
    # LP-323-AS-B — the assets family (registry entries only).
    "reserves_required_months": _reserves_required_months,
    # LP-597 — the other-financed-properties overlay (B3-4.1-01), unblocked by LP-596.
    "reserves_has_other_financed_properties": _reserves_has_other_financed_properties,
    "reserves_other_financed_count": _reserves_other_financed_count,
    "reserves_other_financed_aggregate_upb": _reserves_other_financed_aggregate_upb,
    "reserves_other_financed_required_amount": _reserves_other_financed_required_amount,
    "stmt_repeated_money_in_max_total": _stmt_repeated_money_in_max_total,  # LP-519
    "stmt_nsf_count": _stmt_nsf_count,
    "stmt_min_account_months": _stmt_min_account_months,
    "cash_to_close_shortfall": _cash_to_close_shortfall,
    # LP-410 — the derived-producer wave (unblocks PC-7 / AS-8 / IN-6; tags describe, rules judge).
    "liability_dispute_status": _liability_dispute_status,
    "liability_creditor_name": liability_creditor_name,  # LP-556  # LP-486 / ADR-376
    # LP-573 — DT-8's two inputs. Both DECLINE on a credit-report tradeline: the type question is
    # ADR-353's open-vocabulary classification, and a tradeline carries no payoff marking at all.
    # LP-575 — DT-6's scope, off the SAME matcher as its payment comparison (ADR-375).
    "reo_statement_liability_paid_off": _reo_statement_liability_paid_off,
    # LP-576 — DT-6's Apply target and value, both off the SAME matcher as its comparison.
    "reo_statement_matched_holder": _reo_statement_matched_holder,
    "reo_statement_billed_payment": _reo_statement_billed_payment,
    "liability_stated_is_mortgage": _liability_stated_is_mortgage,
    "liability_payoff_marked": _liability_payoff_marked,
    "liability_payoff_contradicted": _liability_payoff_contradicted,
    "contract_days_until_closing": _contract_days_until_closing,
    # LP-485 — the date-compare family (CL-1 / CR-13 / PR-6). Descriptive numbers only.
    "rate_lock_days_to_closing": _rate_lock_days_to_closing,
    "credit_report_age_months": _credit_report_age_months,
    "appraisal_age_months": _appraisal_age_months,
    "stmt_continuity": _stmt_continuity,
    # LP-546 — recurrence is a COUNT over the file's transactions, not a per-transaction judgment.
    "txn_is_recurring": txn_is_recurring,
    "txn_stated_liability_match": txn_stated_liability_match,
    "income_employer_coverage": _income_employer_coverage,
    # LP-418 — a DETERMINISTIC per-borrower self-employment signal (promotes the measured income.type), for
    # IN-12. No new AI, no calibration round (the win). "no" lets IN-12 reach not_applicable. LP-422 extended
    # it: Schedule C presence (LP-421) is a second, stronger deterministic source income.type cannot carry.
    "income_is_self_employed": _income_is_self_employed,
    # LP-430 — the terminated-employment documentation check (Priya's B14 separate standard).
    "income_terminated_employment": _income_terminated_employment,
    "income_terminated_employment_end_date": _income_terminated_employment_end_date,
    # LP-433 — the pay-stub-only documentation check (Priya's B12 separate standard).
    "income_history_documentation": _income_history_documentation,
    # LP-422 — the rental analog for IN-13: Schedule E presence OR income.type == "rental" -> a per-borrower
    # rental fact (the ADR-332 escape hatch — a fact substitutes for a judgment). Mirrors is_self_employed's
    # dual-signal shape (Schedule + income.type). Presence, not amount.
    "income_has_rental_income": _income_has_rental_income,
    # LP-407-2 — the cheap Bucket 2.5 sub-wave: the loan-level promotion PC-2 needs + the DT-2/DT-4
    # monthly-conversion producers (all mirror existing recipes; tags describe, rules judge). DT-5 is NOT
    # here — it is a vacuous self-compare with no independent operand today (LP-407-2 D1).
    "loan_sales_price": _loan_sales_price,
    "housing_taxes_monthly": _housing_taxes_monthly,
    "housing_hoa_monthly": _housing_hoa_monthly,
}

KNOWN_RECIPES = frozenset(_RECIPES)


def produce_derived_tags(decl: TagDeclaration, snapshot: Snapshot) -> dict[str, dict[str, Tag]]:
    """Produce a derived tag for EACH of its declared subjects, keyed ``{subject_id: {tag_id: Tag}}``.

    LP-332: generalized from loan-only to the declared subject (mirroring how parsed/ai enumerate the
    subject registry). A ``loan`` declaration yields one subject (unchanged); a ``borrower`` declaration
    yields one per borrower, each keyed under its borrower_id. The recipe receives ``(snapshot,
    subject_id, subject_raw)`` and abstains PER SUBJECT — one subject's ``"unknown"`` never touches
    another (per-subject fail-closed, LP-327's discipline)."""
    recipe = _RECIPES.get(decl.data)
    if recipe is None:
        raise KeyError(f"unknown derived recipe {decl.data!r} (known: {sorted(_RECIPES)})")
    out: dict[str, dict[str, Tag]] = {}
    for subject_id, subject_raw in subject_type(decl.subject).enumerate(snapshot):
        value, reasoning = recipe(snapshot, subject_id, subject_raw)
        if value is None:
            # A recipe returns ``None`` to DECLINE producing a tag for an out-of-scope subject (LP-447) —
            # e.g. a per-document recipe scoped to one document_type. Skip it, so a document-subject derived
            # tag lands only on the documents it is about, not an unread ``unknown`` on every document.
            continue
        out[subject_id] = {
            decl.tag_id: Tag(
                value=value,
                confidence=None,
                reasoning=reasoning,
                source_facts=(subject_id,),
                produced_by=TagProducedBy.DERIVED,
                tag_role=TagRole.STRUCTURAL_FACT,
                stage=TagStage.A,
            )
        }
    return out


__all__ = ["KNOWN_RECIPES", "Recipe", "produce_derived_tags"]
