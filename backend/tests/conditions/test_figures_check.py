"""LP-924's "Done when": accepting the July and August statements for 7086 shows the new verified total
against the $38,210.40 required, and a synthetic DTI change from 44% to 46% is flagged "re-run DU" while
46% to 48% is not (the guide's own examples, Fannie Mae B3-2-10).

The file's DTI calculator is arranged to give the letter's ratios (32.51% housing, 40.36% DTI on
$5,741.32), as the harness does: P&I computed, taxes pinned so the housing total is $1,866.50, insurance
$120.00, and one $450.70 debt. Every figure the check shows is then the calculator's own.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from app.models.activity_log import ActivityLog
from app.models.borrower import Borrower
from app.models.condition import Condition
from app.models.loan_file import LoanFile
from app.models.property import OccupancyType, Property
from app.models.stated_financials import StatedAsset, StatedIncomeItem, StatedLiability
from app.schemas.dti import DtiOverrideInput
from app.services import condition_evidence, figures_check
from app.services.condition_evidence import check_document
from app.services.dti import (
    HOUSING_HOA,
    HOUSING_INSURANCE,
    HOUSING_MORTGAGE_INSURANCE,
    HOUSING_TAXES,
    build_dti_calculation,
    monthly_principal_interest,
    set_dti_override,
)
from app.services.figures_check import FiguresChanged, du_rerun_reasons
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.conditions.statement_fixture import add_declarations, add_statement, july_and_august
from tests.conditions.test_condition_evidence import TODAY, _asked, _evidence

INCOME = Decimal("5741.32")
HOUSING_TOTAL = Decimal("1866.50")
OTHER_DEBTS = Decimal("450.70")
#: S3-09 prints "Jul to Aug" with an en dash.
DASH = "\u2013"


def test_the_guides_own_examples() -> None:
    reasons, _ = du_rerun_reasons(old_dti=Decimal("44"), new_dti=Decimal("46"))
    assert reasons == ["the DTI rises above 45% (44% → 46%)"]
    assert du_rerun_reasons(old_dti=Decimal("46"), new_dti=Decimal("48")) == ([], [])


def test_three_points_is_a_rerun_even_under_45() -> None:
    reasons, _ = du_rerun_reasons(old_dti=Decimal("38.00"), new_dti=Decimal("41.00"))
    assert reasons == ["the DTI rises 3.00 points"]
    assert du_rerun_reasons(old_dti=Decimal("38.00"), new_dti=Decimal("40.99"))[0] == []


def test_income_and_reserves_tolerances() -> None:
    reasons, _ = du_rerun_reasons(
        old_dti=Decimal("40"),
        new_dti=Decimal("40"),
        income_used=Decimal("5741.32"),
        income_verified=Decimal("5700.00"),
        reserves_required=Decimal("10000"),
        reserves_verified=Decimal("8999.99"),
    )
    assert len(reasons) == 2
    # Short of what DU required but not below 90% of it: no re-run.
    assert (
        du_rerun_reasons(
            old_dti=Decimal("40"),
            new_dti=Decimal("40"),
            reserves_required=Decimal("10000"),
            reserves_verified=Decimal("9000.00"),
        )[0]
        == []
    )


def test_a_ratio_it_cannot_compute_is_said_not_passed() -> None:
    assert du_rerun_reasons(old_dti=None, new_dti=Decimal("40")) == (
        [],
        ["the DTI (one of the ratios could not be computed)"],
    )


async def _like_the_letter(db: AsyncSession, loan_file: LoanFile, actor: Any) -> None:
    loan_file.loan_amount = Decimal("242199.00")
    loan_file.note_rate_percent = Decimal("6.3740")
    loan_file.amortization_months = 360
    prop = (
        await db.execute(select(Property).where(Property.loan_file_id == loan_file.id))
    ).scalar_one()
    prop.occupancy_type = OccupancyType.PRIMARY_RESIDENCE
    borrower = (
        await db.execute(select(Borrower).where(Borrower.loan_file_id == loan_file.id))
    ).scalar_one()
    db.add(StatedIncomeItem(borrower_id=borrower.id, monthly_amount=INCOME, income_type="Base"))
    db.add(
        StatedLiability(
            loan_file_id=loan_file.id,
            liability_type="Installment",
            monthly_payment=OTHER_DEBTS,
            holder_name="Example Auto Finance",
        )
    )
    db.add(
        StatedAsset(
            loan_file_id=loan_file.id,
            asset_type="CheckingAccount",
            value=Decimal("11062.18"),
            holder_name="Alex Rivera",
        )
    )
    await db.flush()
    pi = monthly_principal_interest(
        loan_file.loan_amount, loan_file.note_rate_percent, loan_file.amortization_months
    )
    assert pi is not None
    taxes = HOUSING_TOTAL - pi - Decimal("120.00")
    for key, amount in (
        (HOUSING_TAXES, taxes),
        (HOUSING_INSURANCE, Decimal("120.00")),
        (HOUSING_MORTGAGE_INSURANCE, Decimal("0.00")),
        (HOUSING_HOA, Decimal("0.00")),
    ):
        await set_dti_override(
            db,
            loan_file=loan_file,
            field_key=key,
            data=DtiOverrideInput(amount=amount.quantize(Decimal("0.01"))),
            actor_user_id=actor,
        )


async def _s3_09(db: AsyncSession) -> tuple[LoanFile, dict[str, Condition], Any]:
    """09/08: 7086's statements accepted (the deposit explained), the new declarations in the file."""
    loan_file, conditions, actor = await _asked(db)
    await _like_the_letter(db, loan_file, actor)
    before = await build_dti_calculation(db, loan_file=loan_file)
    assert (before.front_end_dti, before.back_end_dti) == (Decimal("32.51"), Decimal("40.36"))
    both = await add_statement(db, loan_file, july_and_august())
    await check_document(db, document_id=both.id, today=TODAY)
    (row,) = [e for e in await _evidence(db, conditions["7086"]) if e.findings]
    await condition_evidence.answer_finding(
        db,
        condition=conditions["7086"],
        evidence_id=row.id,
        index=0,
        answer="explained",
        reason="Gift from a relative; gift letter and transfer in the file",
        actor_user_id=actor,
    )
    await add_declarations(db, loan_file)
    return loan_file, conditions, actor


async def test_the_figures_check_is_s3_09(db_session: AsyncSession) -> None:
    loan_file, _, _ = await _s3_09(db_session)
    check = await figures_check.figures_check(db_session, loan_file=loan_file)
    rows = [(c.label, c.in_file, c.from_evidence, c.source) for c in check.changes]
    assert rows == [
        (
            "Verified assets",
            Decimal("11062.18"),
            Decimal("41914.42"),
            f"7086 · Capital One ··9912 Jul{DASH}Aug",
        ),
        (
            "Monthly homeowners insurance",
            Decimal("120.00"),
            Decimal("155.00"),
            "6178 · new declarations page",
        ),
        ("Housing ratio", Decimal("32.51"), Decimal("33.12"), "computed"),
        ("Debt-to-income (DTI)", Decimal("40.36"), Decimal("40.97"), "computed · +0.61 points"),
    ]
    assert len(check.applicable) == 2
    assert check.covers == (Decimal("41914.42"), Decimal("38210.40"))
    assert check.du_rerun is False and check.du_reasons == []


async def test_nothing_changes_until_she_applies(db_session: AsyncSession) -> None:
    loan_file, _, actor = await _s3_09(db_session)
    await figures_check.figures_check(db_session, loan_file=loan_file)
    calc = await build_dti_calculation(db_session, loan_file=loan_file)
    assert calc.back_end_dti == Decimal("40.36")
    asset = (
        await db_session.execute(
            select(StatedAsset).where(StatedAsset.loan_file_id == loan_file.id)
        )
    ).scalar_one()
    assert asset.value == Decimal("11062.18")

    check = await figures_check.figures_check(db_session, loan_file=loan_file)
    shown = [{"key": c.key, "from_evidence": str(c.from_evidence)} for c in check.changes]
    after = await figures_check.apply(
        db_session, loan_file=loan_file, expected=shown, actor_user_id=actor
    )
    assert after.changes == []  # nothing left to propose
    assert asset.value == Decimal("41914.42")
    calc = await build_dti_calculation(db_session, loan_file=loan_file)
    assert (calc.front_end_dti, calc.back_end_dti) == (Decimal("33.12"), Decimal("40.97"))
    summaries = set(
        (
            await db_session.execute(
                select(ActivityLog.summary).where(ActivityLog.loan_file_id == loan_file.id)
            )
        ).scalars()
    )
    assert "Applied 2 changes from accepted evidence (7086, 6178)" in summaries
    assert "Edited a stated asset" in summaries


async def test_it_applies_only_what_she_saw(db_session: AsyncSession) -> None:
    loan_file, _, actor = await _s3_09(db_session)
    with pytest.raises(FiguresChanged, match="look again"):
        await figures_check.apply(
            db_session,
            loan_file=loan_file,
            expected=[{"key": "verified_assets", "from_evidence": "41914.42"}],
            actor_user_id=actor,
        )


async def test_evidence_not_yet_accepted_proposes_nothing(db_session: AsyncSession) -> None:
    """Before the deposit is answered 7086's statements item is not done, so its balance is not yet
    a verified figure — and with no declarations, nothing moves."""
    loan_file, _, actor = await _asked(db_session)
    await _like_the_letter(db_session, loan_file, actor)
    both = await add_statement(db_session, loan_file, july_and_august())
    await check_document(db_session, document_id=both.id, today=date(2026, 9, 2))
    check = await figures_check.figures_check(db_session, loan_file=loan_file)
    assert check.changes == []


@pytest.fixture
def _drop_db_override() -> Any:
    from app.core.database import get_db
    from app.main import app

    yield
    app.dependency_overrides.pop(get_db, None)


@pytest.mark.usefixtures("_drop_db_override")
async def test_the_routes(db_session: AsyncSession) -> None:
    from tests.conditions.test_condition_reading import _client_for

    loan_file, _, _ = await _s3_09(db_session)
    client, headers = await _client_for(db_session, loan_file)
    base = f"/api/v1/loan-files/{loan_file.id}/figures-check"
    async with client:
        body = (await client.get(base, headers=headers)).json()
        assert body["apply_count"] == 2
        assert body["covers"] == {"verified": "41914.42", "required": "38210.40"}
        assert body["du_rerun"] is False and body["citation"] == "Fannie Mae B3-2-10"
        stale = await client.post(
            f"{base}/apply",
            json={"changes": [{"key": "verified_assets", "from_evidence": "1.00"}]},
            headers=headers,
        )
        assert stale.status_code == 409
        applied = await client.post(
            f"{base}/apply",
            json={
                "changes": [
                    {"key": c["key"], "from_evidence": c["from_evidence"]} for c in body["changes"]
                ]
            },
            headers=headers,
        )
        assert applied.status_code == 200, applied.text
        assert applied.json()["changes"] == []
