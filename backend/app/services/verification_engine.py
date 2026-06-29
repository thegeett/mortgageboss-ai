"""Verification-engine service (LP-74) — the per-file run, end to end.

This is the DB-facing half of the engine. It ties the pure pieces together for
one loan file:

1. **Build facts** — read the file's typed values (stated financials, current
   extractions) into a :class:`~app.verification.facts.FileFacts` snapshot.
2. **Resolve rules** — compose the effective rule set for the file's *program*
   and *lender* (base regulatory + investor[program], patched by the lender
   overlay) via the :class:`~app.verification.registry.RuleRegistry`.
3. **Evaluate** — :func:`~app.verification.engine.evaluate` judges each rule
   deterministically against the facts.
4. **Emit** — map each evaluated result onto the shared
   :class:`~app.models.finding.Finding` model, marked
   ``origin=DETERMINISTIC_RULE``, attached to a :class:`Verification` run.

The run is **per file** and **tenant-scoped** (the file is reached only within
its company; a guard asserts the file belongs to ``company_id``). The engine is
*one* finding generator — it writes into the same model the AI cross-source layer
(LP-78) will feed; nothing here makes the findings path engine-exclusive.

The fact computations below are intentionally minimal *sample* calculations
(enough to exercise the engine). The transparent DTI / LTV calculators are
LP-76/77, and the real typed-field promotion happens as the real rules land
(LP-82..85). PII is never logged — only metadata / counts.

Logging note: structlog is used elsewhere; this service stays quiet beyond the
run record to avoid any PII in logs.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import utcnow
from app.models.borrower import Borrower
from app.models.document import Document
from app.models.extraction import Extraction
from app.models.finding import Finding, FindingOrigin, FindingStatus
from app.models.helpers import only_active
from app.models.loan_file import LoanFile
from app.models.property import Property, PropertyType
from app.models.stated_financials import StatedAsset, StatedIncomeItem, StatedLiability
from app.models.verification import Verification, VerificationStatus, VerificationTrigger
from app.services.verifications import create_verification_run
from app.verification.confidence import DETERMINISTIC_CONFIDENCE
from app.verification.engine import EngineFinding, evaluate
from app.verification.facts import Fact, FileFacts
from app.verification.registry import RuleRegistry, default_registry
from app.verification.rules.schema import RuleSeverity

# Document type that carries pay-stub extractions (flexible string, ADR-062).
_PAY_STUB_TYPE = "pay_stub"

_SEVERITY_TO_STATUS = {
    RuleSeverity.RED: FindingStatus.RED,
    RuleSeverity.YELLOW: FindingStatus.YELLOW,
}


async def run_verification(
    db: AsyncSession,
    *,
    loan_file: LoanFile,
    company_id: UUID,
    trigger: VerificationTrigger = VerificationTrigger.MANUAL,
    as_of: date | None = None,
    registry: RuleRegistry | None = None,
) -> Verification:
    """Run the deterministic engine over one loan file and persist its findings.

    Resolves the effective rule set for the file's program + lender, evaluates it
    against the file's typed facts, and writes one :class:`Finding` per *evaluated*
    rule (green on pass, red/yellow on fail) into the shared model, attached to a
    new :class:`Verification` run whose summary counts it sets. Tenant-scoped: the
    file must belong to ``company_id``. ``flush`` (not ``commit``) — the caller
    owns the transaction.
    """
    if loan_file.company_id != company_id:
        raise ValueError("loan file does not belong to the requesting company")

    reg = registry if registry is not None else default_registry()
    as_of_date = as_of if as_of is not None else date.today()

    run = await create_verification_run(db, loan_file_id=loan_file.id, trigger=trigger)

    facts = await build_file_facts(db, loan_file=loan_file, as_of=as_of_date)
    lender_slug = await _lender_slug(db, loan_file)
    rules = reg.resolve(program=loan_file.loan_program, lender_slug=lender_slug)
    results = evaluate(facts, rules)

    red = yellow = green = 0
    for result in results:
        if not result.evaluated:
            # No typed value to judge — not a pass/fail finding (the datum is not
            # on the file yet). The engine never invents a verdict.
            continue
        finding = _to_finding(result, loan_file_id=loan_file.id, verification_id=run.id)
        db.add(finding)
        if finding.status is FindingStatus.RED:
            red += 1
        elif finding.status is FindingStatus.YELLOW:
            yellow += 1
        else:
            green += 1

    run.status = VerificationStatus.COMPLETED
    run.completed_at = utcnow()
    run.red_count = red
    run.yellow_count = yellow
    run.green_count = green
    await db.flush()
    return run


def _to_finding(result: EngineFinding, *, loan_file_id: UUID, verification_id: UUID) -> Finding:
    """Map an :class:`EngineFinding` onto the shared Finding model (uniform shape).

    Emits in the uniform shape both other generators also produce (LP-75):
    ``rule_id`` / origin, observed value, severity-derived status, the condition,
    a structured source citation, **confidence**, **source location** (page +
    snippet), and a plain-language reasoning line. Deterministic findings are
    **certain** — confidence is :data:`DETERMINISTIC_CONFIDENCE` (the math is
    exact, not probabilistic). Resolution defaults to OPEN (the model default).
    """
    rule = result.rule
    status = FindingStatus.GREEN if result.passed else _SEVERITY_TO_STATUS[rule.severity]
    observed_str = _stringify(result.observed)
    threshold_str = _stringify(rule.condition.value)
    verdict = "pass" if result.passed else "fail"
    reasoning = (
        f"{observed_str} {rule.condition.op.value} {threshold_str} "
        f"({rule.condition.unit or 'value'}) → {verdict}"
    )
    message = f"{rule.description} (observed {observed_str}, {verdict})"

    details: dict[str, object] = {
        "observed": observed_str,
        "condition": {
            "op": rule.condition.op.value,
            "value": threshold_str,
            "unit": rule.condition.unit,
        },
        "reads": list(rule.reads),
        "layer": rule.layer.value,
        "source": rule.source.model_dump(),
        # Provenance: which lender overlay (if any) patched the threshold.
        "overlay_applied": rule.overlay_applied,
        "source_location": result.source_location,
        "reasoning": reasoning,
    }

    source_page, source_snippet = _source_location_fields(result.source_location)

    return Finding(
        loan_file_id=loan_file_id,
        verification_id=verification_id,
        rule_id=rule.rule_id,
        origin=FindingOrigin.DETERMINISTIC_RULE,
        confidence=DETERMINISTIC_CONFIDENCE,
        status=status,
        category=rule.category,
        message=message,
        details=details,
        source_page=source_page,
        source_snippet=source_snippet,
    )


def _source_location_fields(
    source_location: dict[str, object] | None,
) -> tuple[int | None, str | None]:
    """Pull the page + verbatim snippet (if any) off a fact's source location."""
    if not source_location:
        return None, None
    raw_page = source_location.get("page")
    page = raw_page if isinstance(raw_page, int) else None
    raw_snippet = source_location.get("snippet")
    snippet = raw_snippet if isinstance(raw_snippet, str) else None
    return page, snippet


def _stringify(value: Decimal | int | None) -> str:
    return "" if value is None else str(value)


# --- Fact building (the typed-field snapshot; sample calcs — LP-76/77) -------


async def build_file_facts(db: AsyncSession, *, loan_file: LoanFile, as_of: date) -> FileFacts:
    """Read one file's typed values into a :class:`FileFacts` snapshot.

    Computes the few facts the LP-74 sample rules read. These are deliberately
    minimal *sample* calculations — the transparent DTI / LTV calculators are
    LP-76/77, and more typed fields get promoted as the real rules land
    (LP-82..85). A fact is omitted (rather than guessed) when its inputs are
    absent; the engine then records that rule as not-evaluated.
    """
    values: dict[str, Fact] = {}

    monthly_debt = await _sum_monthly_liabilities(db, loan_file.id)
    monthly_income = await _sum_monthly_income(db, loan_file.id)
    assets = await _stated_asset_values(db, loan_file.id)

    # dti.back_end_pct — total monthly debt / gross monthly income (sample calc).
    if monthly_income and monthly_income > 0:
        back_end = (monthly_debt / monthly_income * Decimal(100)).quantize(Decimal("0.01"))
        values["dti.back_end_pct"] = Fact(
            value=back_end,
            source={"type": "computed", "note": "sample DTI calc; calculators are LP-76/77"},
        )

    # assets.largest_deposit_amount — largest single stated asset value.
    if assets:
        values["assets.largest_deposit_amount"] = Fact(
            value=max(assets),
            source={"type": "stated", "note": "largest stated asset value"},
        )

    # reserves.months — total stated assets / monthly debt (sample proxy).
    if assets and monthly_debt > 0:
        months = (sum(assets, Decimal(0)) / monthly_debt).quantize(Decimal("0.1"))
        values["reserves.months"] = Fact(
            value=months,
            source={"type": "computed", "note": "sample reserves calc; calculators are LP-76/77"},
        )

    # documents.paystub.most_recent_age_days — age of the newest current pay stub.
    paystub_fact = await _most_recent_paystub_age(db, loan_file.id, as_of=as_of)
    if paystub_fact is not None:
        values["documents.paystub.most_recent_age_days"] = paystub_fact

    # --- Typed-core promotions for the LP-82 Conventional income/asset rules ----
    # Presence-driven facts derived from the stated structured data: set only when
    # present (> 0), so a "documentation required" rule fires when the thing exists
    # and is simply not-evaluated when it doesn't (the engine's graceful absence).
    gift_total = await _sum_assets_by_type(db, loan_file.id, _GIFT_KEYWORDS)
    if gift_total > 0:
        values["assets.gift.total_amount"] = Fact(
            value=gift_total,
            source={"type": "stated", "note": "sum of gift-type stated assets (LP-82 promotion)"},
        )

    retirement_total = await _sum_assets_by_type(db, loan_file.id, _RETIREMENT_KEYWORDS)
    if retirement_total > 0:
        values["assets.retirement.total_amount"] = Fact(
            value=retirement_total,
            source={"type": "stated", "note": "sum of retirement-type stated assets (LP-82)"},
        )

    se_income = await _sum_self_employment_income(db, loan_file.id)
    if se_income > 0:
        values["income.self_employment.monthly_amount"] = Fact(
            value=se_income,
            source={"type": "stated", "note": "sum of self-employment stated income (LP-82)"},
        )

    # --- Property facts for the LP-83 property/doc rules (+ the condo gate) ------
    property_obj = await _subject_property(db, loan_file.id)
    if property_obj is not None:
        values["property.present"] = Fact(
            value=Decimal(1), source={"type": "stated", "note": "subject property on file (LP-83)"}
        )
        is_condo = property_obj.property_type is PropertyType.CONDO
        values["property.is_condo"] = Fact(
            value=Decimal(1) if is_condo else Decimal(0),
            source={"type": "stated", "note": "property_type == condo (LP-83 gate)"},
        )

    return FileFacts(values=values)


async def _subject_property(db: AsyncSession, loan_file_id: UUID) -> Property | None:
    stmt = only_active(select(Property).where(Property.loan_file_id == loan_file_id), Property)
    return (await db.execute(stmt)).scalars().first()


# Type keywords for the LP-82 promotions (matched case-insensitively on the stated
# asset_type / income_type). Starter heuristics over the stated data — the richer
# typed extraction is a later promotion.
_GIFT_KEYWORDS = ("gift",)
_RETIREMENT_KEYWORDS = ("retirement", "401", "ira", "pension")
_SELF_EMPLOYMENT_KEYWORDS = ("self", "business")


async def _sum_assets_by_type(
    db: AsyncSession, loan_file_id: UUID, keywords: tuple[str, ...]
) -> Decimal:
    """Sum stated assets whose ``asset_type`` matches any keyword (case-insensitive)."""
    stmt = only_active(
        select(StatedAsset).where(StatedAsset.loan_file_id == loan_file_id), StatedAsset
    )
    rows = (await db.execute(stmt)).scalars().all()
    return sum(
        (
            row.value
            for row in rows
            if row.value is not None
            and row.asset_type is not None
            and any(k in row.asset_type.lower() for k in keywords)
        ),
        Decimal(0),
    )


async def _sum_self_employment_income(db: AsyncSession, loan_file_id: UUID) -> Decimal:
    """Sum stated income whose ``income_type`` looks like self-employment / business."""
    stmt = only_active(
        select(StatedIncomeItem)
        .join(Borrower, StatedIncomeItem.borrower_id == Borrower.id)
        .where(Borrower.loan_file_id == loan_file_id),
        StatedIncomeItem,
    )
    rows = (await db.execute(stmt)).scalars().all()
    return sum(
        (
            row.monthly_amount
            for row in rows
            if row.monthly_amount is not None
            and row.income_type is not None
            and any(k in row.income_type.lower() for k in _SELF_EMPLOYMENT_KEYWORDS)
        ),
        Decimal(0),
    )


async def _sum_monthly_liabilities(db: AsyncSession, loan_file_id: UUID) -> Decimal:
    stmt = only_active(
        select(StatedLiability).where(StatedLiability.loan_file_id == loan_file_id),
        StatedLiability,
    )
    rows = (await db.execute(stmt)).scalars().all()
    return sum(
        (row.monthly_payment for row in rows if row.monthly_payment is not None),
        Decimal(0),
    )


async def _sum_monthly_income(db: AsyncSession, loan_file_id: UUID) -> Decimal:
    stmt = only_active(
        select(StatedIncomeItem)
        .join(Borrower, StatedIncomeItem.borrower_id == Borrower.id)
        .where(Borrower.loan_file_id == loan_file_id),
        StatedIncomeItem,
    )
    rows = (await db.execute(stmt)).scalars().all()
    return sum(
        (row.monthly_amount for row in rows if row.monthly_amount is not None),
        Decimal(0),
    )


async def _stated_asset_values(db: AsyncSession, loan_file_id: UUID) -> list[Decimal]:
    stmt = only_active(
        select(StatedAsset).where(StatedAsset.loan_file_id == loan_file_id),
        StatedAsset,
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [row.value for row in rows if row.value is not None]


async def _most_recent_paystub_age(
    db: AsyncSession, loan_file_id: UUID, *, as_of: date
) -> Fact | None:
    """Age (days) of the newest current pay-stub extraction, or ``None``."""
    stmt = only_active(
        select(Extraction, Document)
        .join(Document, Extraction.document_id == Document.id)
        .where(
            Document.loan_file_id == loan_file_id,
            Document.document_type == _PAY_STUB_TYPE,
            Extraction.is_current.is_(True),
        ),
        Document,
    )
    newest_date: date | None = None
    newest_doc_id: UUID | None = None
    newest_loc: dict[str, object] = {}
    for extraction, document in (await db.execute(stmt)).all():
        pay_date = _read_pay_date(extraction.extracted_data)
        if pay_date is None:
            continue
        if newest_date is None or pay_date > newest_date:
            newest_date = pay_date
            newest_doc_id = document.id
            newest_loc = _read_pay_date_location(extraction.extracted_data)
    if newest_date is None:
        return None
    age_days = (as_of - newest_date).days
    # Carry the page + verbatim snippet through (the trust/audit anchor, LP-75).
    source: dict[str, object] = {"document_id": str(newest_doc_id), "type": "extraction"}
    source.update(newest_loc)
    return Fact(value=age_days, source=source)


def _read_pay_date_location(extracted_data: dict[str, object]) -> dict[str, object]:
    """The ``pay_date`` field's source location (page + snippet), if present."""
    field = extracted_data.get("pay_date")
    if not isinstance(field, dict):
        return {}
    loc = field.get("source")
    if not isinstance(loc, dict):
        return {}
    out: dict[str, object] = {}
    if isinstance(loc.get("page"), int):
        out["page"] = loc["page"]
    if isinstance(loc.get("snippet"), str):
        out["snippet"] = loc["snippet"]
    return out


def _read_pay_date(extracted_data: dict[str, object]) -> date | None:
    """Read the typed ``pay_date`` value off a pay-stub extraction payload.

    The typed-core shape stores ``{"pay_date": {"value": "YYYY-MM-DD", ...}}``.
    Returns ``None`` if absent or unparseable (never raises).
    """
    field = extracted_data.get("pay_date")
    if not isinstance(field, dict):
        return None
    raw = field.get("value")
    if isinstance(raw, date):
        return raw
    if isinstance(raw, str):
        try:
            return date.fromisoformat(raw)
        except ValueError:
            return None
    return None


async def _lender_slug(db: AsyncSession, loan_file: LoanFile) -> str | None:
    """The file's lender slug (drives overlay selection), or ``None``."""
    if loan_file.lender_id is None:
        return None
    from app.models.lender import Lender

    lender = await db.get(Lender, loan_file.lender_id)
    return lender.slug if lender is not None else None
