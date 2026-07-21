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
    """income.max_employment_gap_days — the largest gap (days) between consecutive employment records.

    Sorts the (end → next start) intervals across all employment records. Abstains when fewer than two
    records with the needed dates exist (a single job cannot have a gap)."""
    starts = sorted(_income_dates(snapshot, "income.employment_start"))
    ends = sorted(_income_dates(snapshot, "income.employment_end"))
    if len(starts) < 2 or not ends:
        return _UNKNOWN, "fewer than two dated employment records — no gap to measure"
    # Each end pairs with the NEXT start (the earliest start after it), NOT every later start — else the
    # max would span intervening jobs (end of job A → start of job C) and overstate a gap that job B
    # actually fills. The largest of those consecutive gaps is the employment gap.
    gaps: list[int] = []
    for end in ends:
        later_starts = [s for s in starts if s > end]
        if later_starts:
            gaps.append((min(later_starts) - end).days)
    if not gaps:
        return _UNKNOWN, "no employment record starts after a prior one ends — cannot measure a gap"
    max_gap = max(gaps)
    return str(max_gap), f"largest gap between consecutive employment records is {max_gap} day(s)"


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
    was never materialized (absent≠no); returning 0 would false-green AS-7 (every file reads NSF-clean)."""
    if snapshot.tags.absent:
        return _UNKNOWN, "no tags materialized — cannot count NSF/overdraft items"
    count = 0
    any_seen = False
    for tags in snapshot.tags.by_subject.values():
        tag = tags.get("txn.is_nsf_or_overdraft")
        if tag is None:
            continue
        any_seen = True
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
    values: set[str] = set()
    for entry in _borrower_attributed_documents(snapshot, subject_id):
        if entry.document_type not in _GOVERNMENT_ID_DOC_TYPES:
            continue  # only a government photo ID carries the expiration ID-5 checks
        tag = snapshot.tags.by_subject.get(entry.content_id, {}).get("id.id_expiration")
        if tag is None or str(tag.value) == _UNKNOWN:
            continue
        values.add(str(tag.value))
    if not values:
        return _UNKNOWN, f"borrower {subject_id}: no driver's licence found for this borrower"
    if len(values) > 1:
        return _UNKNOWN, (
            f"borrower {subject_id}: the borrower's ID documents disagree on the expiration date "
            f"({', '.join(sorted(values))}) — ambiguous"
        )
    expiration = next(iter(values))
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
    values: set[str] = set()
    for tags in snapshot.tags.by_subject.values():
        tag = tags.get("contract.closing_date")
        if tag is None or str(tag.value) == _UNKNOWN:
            continue
        values.add(str(tag.value))
    if not values:
        return _UNKNOWN, "no closing date is stated in the file"
    if len(values) > 1:
        return _UNKNOWN, (
            f"the file's documents disagree on the closing date ({', '.join(sorted(values))}) — ambiguous"
        )
    closing = next(iter(values))
    return closing, f"the loan's closing date {closing} (from the contract document)"


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
