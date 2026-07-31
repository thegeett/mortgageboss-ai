"""The generic DERIVED producer (LP-326) — compute a tag deterministically from other facts.

A ``derived`` tag's ``production_data`` is a RECIPE KEY resolved against the recipe registry (one
entry per recipe, reusable across families — never per-family branching). A recipe reads the snapshot
and returns ``(value, reasoning)`` for its subject; the producer wraps it in a ``derived`` tag citing
its subject. A recipe that cannot compute returns ``("unknown", reason)`` — honest, never fabricated.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date
from decimal import Decimal, InvalidOperation
from itertools import pairwise

from pydantic import JsonValue

from app.ai.extraction.parsing import coerce_date
from app.verification.snapshot.fields import Field
from app.verification.snapshot.model import DocumentEntry, Snapshot
from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage
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
Recipe = Callable[[Snapshot, str, object], tuple[JsonValue, str]]

_UNKNOWN = "unknown"


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
    any_present, any_unknown). Only this borrower's documents — one borrower's income never leaks.

    income.documented_monthly is a PER-PAYSTUB figure (materialized per document), so the standard two
    recent paystubs from ONE job carry the SAME monthly amount — SUMMING them would double-count and turn
    a real shortfall into an apparent raise (the exact PIN #1 false-green, re-created within a borrower).
    We therefore take the DISTINCT documented figure: exactly one distinct value → that is the documented
    monthly; MORE than one (variable pay, or a genuine multi-job borrower whose sources need per-employer
    aggregation) → any_unknown → the caller ABSTAINS (couldnt_check), never a summed over-count. Summing
    a true multi-job borrower's sources is a domain follow-on (needs per-employer grouping); until then
    the honest answer is to abstain, never to mask."""
    values: set[Decimal] = set()
    any_present = any_unknown = False
    if snapshot.tags.absent or snapshot.documents.absent:
        return Decimal(0), any_present, any_unknown
    for entry in _borrower_attributed_documents(snapshot, borrower_id):
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
            f"borrower {subject_id}: stated monthly income is absent, zero, or incomplete",
        )
    if not d_present or d_unknown:
        return (
            _UNKNOWN,
            f"borrower {subject_id}: documented monthly income is absent, incomplete, or has "
            "conflicting figures across documents",
        )
    shortfall = (stated - documented) / stated
    return (
        str(shortfall),
        f"borrower {subject_id}: documented {documented} vs stated {stated} → shortfall "
        f"{shortfall:.4f} (negative = a raise, not a shortfall)",
    )


def _income_ytd_annualized_shortfall(
    snapshot: Snapshot, _subject_id: str, _subject_raw: object
) -> tuple[JsonValue, str]:
    """income.ytd_annualized_shortfall_pct — (documented - ytd_monthly) / documented, loan-level.

    ytd_monthly = total YTD gross / elapsed months (the MOST-RECENT pay date's month number). Fires
    when the paystub YTD does NOT support the documented monthly (a positive shortfall). Abstains when
    YTD, a pay date, or documented income is missing/incomplete."""
    ytd, ytd_present, ytd_unknown = _income_numbers(snapshot, "income.ytd_gross")
    documented, d_present, d_unknown = _income_numbers(snapshot, "income.documented_monthly")
    pay_dates = _income_dates(snapshot, "income.pay_date")
    if not ytd_present or ytd_unknown:
        return _UNKNOWN, "year-to-date gross is absent or incomplete — cannot annualize"
    if not pay_dates:
        return _UNKNOWN, "no pay date — cannot determine the elapsed period for the YTD figure"
    if not d_present or d_unknown or documented == 0:
        return _UNKNOWN, "documented monthly income is absent, incomplete, or zero — cannot compare"
    # The MOST-RECENT pay date's month number is the elapsed YTD period. Use max(pay_dates).month —
    # NOT max(d.month ...), which across a year boundary (a Dec + Jan paystub) would pick December's
    # 12 over January's most-recent 1 and understate the monthly figure into a false shortfall.
    elapsed_months = max(pay_dates).month
    ytd_monthly = ytd / Decimal(elapsed_months)
    shortfall = (documented - ytd_monthly) / documented
    return (
        str(shortfall),
        f"YTD gross {ytd} over {elapsed_months} month(s) = {ytd_monthly:.2f}/mo vs documented "
        f"{documented}/mo → shortfall {shortfall:.4f}",
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
_APP_REQUIRED_FIELDS = (
    "borrower.1.name",
    "borrower.1.ssn",
    "loan.amount",
    "property.address",
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
# Agency-standard reserve requirements by occupancy (1-unit PURCHASE), Fannie Selling Guide B3-4.1-01. The
# full matrix (2-4 units, LTV tiers, multiple financed properties, FHA/VA overlays) is Priya's — an
# occupancy not in this map ABSTAINS (couldnt_check), never a guessed requirement. priya_validated:false.
#
# KNOWN UNDER-STATEMENT (LP-323-AS-B review, Priya-pending): this keys on occupancy ONLY. The un-modeled
# axes (unit count, # of financed properties, LTV) can only RAISE the requirement, so a NON-1-unit or
# multiple-financed-property PRIMARY gets required=0 here and AS-4 can false-green a real reserve shortfall.
# Not guarded in code: the reserve-matrix "units" axis is not a clean MISMO fact today (only
# property.financed_unit_count exists, whose semantics are ambiguous for this axis), so a guard would be a
# domain guess — deferred to Priya with the rest of the matrix rather than approximated here.
_RESERVE_MONTHS_BY_OCCUPANCY = {"investment": "6", "second_home": "2", "primary_residence": "0"}


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


def _reserves_required_months(
    snapshot: Snapshot, _subject_id: str, _subject_raw: object
) -> tuple[JsonValue, str]:
    """reserves.required_months — the reserve requirement (months of PITIA) selected from the loan's
    occupancy (AS-4's threshold, the D1 derived-matrix pattern). ABSTAINS for any occupancy not in the
    encoded agency-standard cells — the full matrix is Priya's, and a guessed requirement is a silent,
    permanent error."""
    occupancy = _mismo_str(snapshot, "property.occupancy")
    if occupancy is None:
        return _UNKNOWN, "occupancy is unknown — cannot select the reserve requirement"
    months = _RESERVE_MONTHS_BY_OCCUPANCY.get(occupancy.casefold())
    if months is None:
        return (
            _UNKNOWN,
            f"no encoded reserve requirement for occupancy {occupancy!r} (Priya-pending)",
        )
    return (
        months,
        f"reserve requirement for {occupancy}: {months} months (Fannie B3-4.1-01, Priya-pending)",
    )


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
            f"borrower {subject_id}: no tags materialized to read an ID expiration from",
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
        return _UNKNOWN, f"borrower {subject_id}: no driver's licence found for this borrower"
    if len(values) > 1:
        return _UNKNOWN, (
            f"borrower {subject_id}: the borrower's ID documents disagree on the expiration date "
            f"({', '.join(sorted(values.values()))}) — ambiguous"
        )
    expiration = next(iter(values.values()))
    return (
        expiration,
        f"borrower {subject_id}: government-ID expiration {expiration} (from their attributed ID)",
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


def _decimal_or_none(tag: Tag | None) -> Decimal | None:
    """A statement balance tag's value as a Decimal, or None (absent / unknown / unparseable)."""
    if tag is None or str(tag.value) == _UNKNOWN:
        return None
    try:
        return Decimal(str(tag.value))
    except (InvalidOperation, ValueError):
        return None


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
            f"borrower {subject_id}: no documents to read a self-employment signal from",
        )
    # LP-422 — Schedule C presence is a DETERMINISTIC self-employment FACT (a filed Schedule C business).
    for entry in _borrower_attributed_documents(snapshot, subject_id):
        if entry.schedule_c:
            return "yes", (
                f"borrower {subject_id}: an attributed tax return has a Schedule C (a self-employment "
                "business) — presence, not amount (a loss still counts)"
            )
    if snapshot.tags.absent:
        return _UNKNOWN, f"borrower {subject_id}: no tags to read an income type from"
    any_type_seen = False
    for entry in _borrower_attributed_documents(snapshot, subject_id):
        tag = snapshot.tags.by_subject.get(entry.content_id, {}).get("income.type")
        if tag is None or str(tag.value) == _UNKNOWN:
            continue
        any_type_seen = True
        if str(tag.value) == "self_employment":
            return "yes", (
                f"borrower {subject_id}: an income document states self-employment income "
                "(2-year self-employment history applies)"
            )
    if not any_type_seen:
        return _UNKNOWN, (
            f"borrower {subject_id}: no attributed income document carries a readable income type"
        )
    return "no", (
        f"borrower {subject_id}: the borrower's income documents carry income types, none self-employment "
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
        return _UNKNOWN, f"borrower {subject_id}: no documents to read a rental signal from"
    # 1. Schedule E presence — the DETERMINISTIC signal (needs only the documents, not the tags layer).
    saw_tax_return = False
    for entry in _borrower_attributed_documents(snapshot, subject_id):
        if entry.document_type == "tax_return":
            saw_tax_return = True
            if entry.schedule_e is not None:
                return "yes", (
                    f"borrower {subject_id}: an attributed tax return has a Schedule E (rental income) — "
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
                    f"borrower {subject_id}: an income document is typed rental income "
                    "(rental income is stated even without a Schedule E filed)"
                )
    # 3. A definitive "no": a filed tax return with no Schedule E, or readable income types none rental.
    if saw_tax_return or any_type_seen:
        return "no", (
            f"borrower {subject_id}: no Schedule E on any attributed tax return and no income document "
            "typed rental — no rental income evidenced"
        )
    # 4. Nothing to read → fail-closed (never a fabricated "no").
    return _UNKNOWN, (
        f"borrower {subject_id}: no tax return and no readable income type attributed — "
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
            f"borrower {subject_id}: employment shown as ended {end} with no pay stub dated after it — "
            "a pay stub dated after that is needed to confirm current employment"
        ),
        "cleared": (
            f"borrower {subject_id}: employment ended {end}, but a pay stub dated after it confirms "
            "current employment"
        ),
        "not_terminated": (
            f"borrower {subject_id}: no employment end date in the past — not a terminated job"
        ),
        "unknown": f"borrower {subject_id}: employment-termination documentation cannot be read",
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
        return _UNKNOWN, f"borrower {subject_id}: no past employment end date to name"
    return (
        end.isoformat(),
        f"borrower {subject_id}: most recent past employment end date is {end.isoformat()}",
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
        return _UNKNOWN, f"borrower {subject_id}: no documents to read an income-history basis from"
    types = {entry.document_type for entry in _borrower_attributed_documents(snapshot, subject_id)}
    if types & {"w2", "1099"}:
        return "w2_or_1099", (
            f"borrower {subject_id}: a W-2 or 1099 is attributed — the two-year income history can be "
            "established"
        )
    if "pay_stub" in types:
        return "pay_stub_only", (
            f"borrower {subject_id}: income is evidenced only by pay stubs (no W-2 or 1099 attributed)"
        )
    return "no_pay_stubs", (
        f"borrower {subject_id}: no pay stubs attributed — no pay-stub-only history for this check"
    )


_RECIPES: dict[str, Recipe] = {
    "app_required_fields_present": _app_required_fields_present,
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
    "stmt_nsf_count": _stmt_nsf_count,
    "stmt_min_account_months": _stmt_min_account_months,
    "cash_to_close_shortfall": _cash_to_close_shortfall,
    # LP-410 — the derived-producer wave (unblocks PC-7 / AS-8 / IN-6; tags describe, rules judge).
    "contract_days_until_closing": _contract_days_until_closing,
    "stmt_continuity": _stmt_continuity,
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
