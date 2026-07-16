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
from app.verification.snapshot.model import Snapshot
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
    for entry in snapshot.documents.entries:
        if entry.belongs_to is None or not any(
            str(ref.borrower_id) == borrower_id for ref in entry.belongs_to
        ):
            continue
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
# Agency-standard reserve requirements by occupancy (1-unit), Fannie Selling Guide B3-4.1-01. The full
# matrix (2-4 units, LTV tiers, multiple financed properties, FHA/VA overlays) is Priya's — an occupancy
# not in this map ABSTAINS (couldnt_check), never a guessed requirement. priya_validated:false on IN-4.
_RESERVE_MONTHS_BY_OCCUPANCY = {"investment": "6", "second_home": "2", "primary_residence": "0"}


def _mismo_str(snapshot: Snapshot, key: str) -> str | None:
    if snapshot.mismo.absent:
        return None
    field = snapshot.mismo.facts.get(key)
    if not isinstance(field, Field) or not field.is_present:
        return None
    return str(field.value).strip() or None


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
    per-transaction ``txn.is_nsf_or_overdraft`` tag. An absent tag is not counted (absent≠no)."""
    if snapshot.tags.absent:
        return _UNKNOWN, "no tags materialized — cannot count NSF/overdraft items"
    count = 0
    for tags in snapshot.tags.by_subject.values():
        tag = tags.get("txn.is_nsf_or_overdraft")
        if tag is not None and str(tag.value) == "yes":
            count += 1
    return str(count), f"{count} NSF/overdraft transaction(s) across the file's statements"


def _stmt_min_account_months(
    snapshot: Snapshot, _subject_id: str, _subject_raw: object
) -> tuple[JsonValue, str]:
    """stmt.min_account_months — the FEWEST distinct statement months any ONE account has (AS-10 recency).
    Groups statements per account via resolve_accounts (LP-336) and takes the MIN across accounts, so a
    single short account is never MASKED by a well-documented one (fire-if-any). Abstains when no
    resolvable account or no period dates. Deterministic (parsed period fields + the parsed identity)."""
    from app.verification.rule_engine.enumerators import (
        resolve_accounts,
    )  # lazy: avoid an import cycle

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
        per_account.append(len(months))
    if not any(per_account):
        return _UNKNOWN, "no statement period dates — cannot count months"
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


_RECIPES: dict[str, Recipe] = {
    "app_required_fields_present": _app_required_fields_present,
    # LP-323-IN-B — the income family's loan-level arithmetic (per-borrower granularity is deferred:
    # the derived producer is loan-only, so these aggregate the file like the DTI calc does — see the
    # LP-323-IN-B doc). Registry entries only; produce_derived_tags is untouched (the wave criterion).
    "income_documented_shortfall": _income_documented_shortfall,
    "income_ytd_annualized_shortfall": _income_ytd_annualized_shortfall,
    "income_max_employment_gap": _income_max_employment_gap,
    "income_days_since_recent_pay": _income_days_since_recent_pay,
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
