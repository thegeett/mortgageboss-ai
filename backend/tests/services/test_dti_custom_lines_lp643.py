"""LP-643 — processor-added DTI lines, and the ungate.

Three policy decisions are pinned here, each recommended and then confirmed by the user. They are
POLICY rather than mechanics, so the tests state the reasoning: a later reader deciding to loosen one
should have to disagree with an argument rather than delete an unexplained assertion.

  1. An added row does NOT clear a gate.
  2. An ENGINE row is excludable-with-reason, never deletable.
  3. Ungate ships, behind an itemised consent — and refuses the gates a zero cannot answer.
"""

from __future__ import annotations

from decimal import Decimal

from app.models import Company
from app.models.property import OccupancyType
from app.schemas.dti import DtiCustomLineInput
from app.services.dti import (
    add_dti_custom_line,
    apply_dti_ungate,
    build_dti_calculation,
    preview_dti_ungate,
    remove_dti_custom_line,
    set_dti_override,
)
from sqlalchemy.ext.asyncio import AsyncSession
from tests.integration import factories


async def _file(db: AsyncSession, slug: str):
    company = await factories.make_company(db, slug=slug)
    loan_file = await factories.make_loan_file(db, company=company)
    return loan_file, company


async def _actor(db: AsyncSession, company: Company):
    return (await factories.make_user(db, company=company)).id


async def test_an_added_line_is_itemised_and_sums_into_its_section(db_session) -> None:
    """Routed through `_to_items` like every other line, which is the whole reason to shape a custom
    line as an `_AutoLine`. LP-621 records what happens otherwise: a figure appended straight to the
    engine lines landed "in the headline but not the breakdown, so the itemized list stopped summing
    to the number beside it"."""
    loan_file, company = await _file(db_session, "custom-sums")
    actor = await _actor(db_session, company)

    calc = await add_dti_custom_line(
        db_session,
        loan_file=loan_file,
        data=DtiCustomLineInput(
            section="debt", label="Private loan from family", amount=Decimal("250.00")
        ),
        actor_user_id=actor,
    )

    line = next(i for i in calc.debt_items if i.label == "Private loan from family")
    assert line.amount == Decimal("250.00")
    assert line.source == "manual", "a figure with no document behind it must not read as extracted"
    assert sum(i.amount for i in calc.debt_items if not i.excluded) == calc.monthly_debts


async def test_an_added_line_does_NOT_clear_a_gate(db_session) -> None:
    """DECISION 1, AND THE REASON. A gate says a REQUIRED INPUT IS UNKNOWN. Adding an unrelated row
    does not make it known — a processor who types "Rent — $2,000" into income has not produced the
    Form 1007 that B3-3.8-02 requires, and letting the row clear the gate would route the fail-closed
    discipline around through the UI.

    Overriding the GATED LINE ITSELF remains the way to supply a figure, and that already clears the
    gate, because it answers the actual question.
    """
    loan_file, company = await _file(db_session, "no-ungate-by-row")
    actor = await _actor(db_session, company)
    prop = await factories.make_property(db_session, loan_file=loan_file)
    prop.occupancy_type = OccupancyType.PRIMARY_RESIDENCE
    await db_session.flush()

    before = await build_dti_calculation(db_session, loan_file=loan_file)
    assert before.gated, "the fixture must actually be gated or this asserts nothing"

    after = await add_dti_custom_line(
        db_session,
        loan_file=loan_file,
        data=DtiCustomLineInput(section="income", label="Side work", amount=Decimal("2000.00")),
        actor_user_id=actor,
    )

    assert after.gated, "an added row must not answer a question it does not address"
    assert after.gate_reason == before.gate_reason, "and must not change what the gate says"


async def test_removing_a_line_a_processor_added_is_a_soft_delete(db_session) -> None:
    """It leaves the trail, the same discipline as clearing an override."""
    from app.models.dti_custom_line import DtiCustomLine
    from sqlalchemy import select

    loan_file, company = await _file(db_session, "remove-own")
    actor = await _actor(db_session, company)
    await add_dti_custom_line(
        db_session,
        loan_file=loan_file,
        data=DtiCustomLineInput(section="debt", label="Storage unit", amount=Decimal("95.00")),
        actor_user_id=actor,
    )
    row = (await db_session.scalars(select(DtiCustomLine))).all()[-1]

    calc = await remove_dti_custom_line(
        db_session, loan_file=loan_file, line_id=row.id, actor_user_id=actor
    )

    assert not [i for i in calc.debt_items if i.label == "Storage unit"]
    await db_session.refresh(row)
    assert row.deleted_at is not None, "soft delete — the row is the trail"


async def test_there_is_no_way_to_DELETE_an_engine_line(db_session) -> None:
    """DECISION 2. Removing a credit-report liability is an EXCLUSION — a claim that a real debt
    should not count — and the calculator already renders that as a struck-through line with its
    reason. A vanished row cannot be argued with, nothing records who decided it, and the itemisation
    stops reconciling with the source data.

    `remove_dti_custom_line` scopes to `dti_custom_lines`, so an engine key simply is not found.
    """
    from app.services.dti import UnknownDtiFieldError

    loan_file, company = await _file(db_session, "no-engine-delete")
    actor = await _actor(db_session, company)
    calc = await build_dti_calculation(db_session, loan_file=loan_file)
    engine_line = calc.housing_items[0]

    from uuid import uuid4

    import pytest

    with pytest.raises(UnknownDtiFieldError):
        await remove_dti_custom_line(
            db_session, loan_file=loan_file, line_id=uuid4(), actor_user_id=actor
        )
    assert engine_line.key in {i.key for i in calc.housing_items}


async def test_a_line_cannot_be_removed_from_another_file(db_session) -> None:
    """The scoping that keeps a line-id from being a cross-file handle."""
    import pytest
    from app.models.dti_custom_line import DtiCustomLine
    from app.services.dti import UnknownDtiFieldError
    from sqlalchemy import select

    mine, company = await _file(db_session, "scope-mine")
    theirs, _ = await _file(db_session, "scope-theirs")
    actor = await _actor(db_session, company)
    await add_dti_custom_line(
        db_session,
        loan_file=mine,
        data=DtiCustomLineInput(section="debt", label="Mine", amount=Decimal("10.00")),
        actor_user_id=actor,
    )
    row = (await db_session.scalars(select(DtiCustomLine))).all()[-1]

    with pytest.raises(UnknownDtiFieldError):
        await remove_dti_custom_line(
            db_session, loan_file=theirs, line_id=row.id, actor_user_id=actor
        )


# --------------------------------------------------------------------------- #
# The ungate
# --------------------------------------------------------------------------- #


async def test_the_preview_names_every_line_and_what_it_asserts(db_session) -> None:
    """DECISION 3, AND WHAT MAKES IT A CONSENT RATHER THAN A CLICK-THROUGH. Not "3 values will be set
    to $0" — a processor recognises *Property taxes* and cannot act on *3 values*. And not the
    mechanism but the CLAIM: "the DTI will be computed as if this file has no property taxes
    obligation" is the half they can judge as true or false."""
    loan_file, _ = await _file(db_session, "ungate-preview")

    preview = await preview_dti_ungate(db_session, loan_file=loan_file)

    labels = {line.label for line in preview.lines}
    assert "Property taxes" in labels and "Homeowners insurance" in labels
    for line in preview.lines:
        assert "$0.00" in line.assertion and "computed as if" in line.assertion


async def test_the_preview_shows_the_ratio_the_apply_would_produce(db_session) -> None:
    """THE NUMBER IS WHAT THE CONSENT IS REALLY ABOUT, so the popup has to show it — and it must be
    the number Apply delivers, not one computed a second way. The preview runs the SAME calculator
    with the SAME overrides, in memory; this asserts the two agree."""
    loan_file, company = await _file(db_session, "ungate-agrees")
    actor = await _actor(db_session, company)
    # REAL INCOME, OR THE ASSERTION IS VACUOUS. Without it both ratios are None on a bare file and
    # `None == None` passes however far the preview diverges — verified: with the preview computing
    # its hypothetical from $99,999 instead of $0, the first version of this test stayed green.
    from app.models import StatedIncomeItem

    borrower = await factories.make_borrower(db_session, loan_file=loan_file)
    db_session.add(
        StatedIncomeItem(
            borrower_id=borrower.id, monthly_amount=Decimal("10000.00"), income_type="Base"
        )
    )
    loan_file.loan_amount = Decimal("300000.00")
    loan_file.note_rate_percent = Decimal("7.000")
    loan_file.amortization_months = 360
    await db_session.flush()

    preview = await preview_dti_ungate(db_session, loan_file=loan_file)
    applied = await apply_dti_ungate(
        db_session, loan_file=loan_file, note="taxes confirmed exempt", actor_user_id=actor
    )

    assert preview.back_end_after is not None, "a None here would make the comparison meaningless"
    assert preview.back_end_after == applied.back_end_dti
    assert preview.front_end_after == applied.front_end_dti


async def test_the_ungate_writes_ordinary_overrides_so_undo_already_exists(db_session) -> None:
    """WHY OVERRIDES AND NOT AN `ungated` FLAG. Undo is the per-line clear that already ships; the
    breakdown still reconciles with the headline; and the file records WHICH values were asserted. A
    boolean would give none of those and would reintroduce the LP-621 defect."""
    from app.services.dti import clear_dti_override

    loan_file, company = await _file(db_session, "ungate-undo")
    actor = await _actor(db_session, company)

    ungated = await apply_dti_ungate(
        db_session, loan_file=loan_file, note="confirmed", actor_user_id=actor
    )
    assert not ungated.gated, "the point of the button"
    taxes = next(i for i in ungated.housing_items if i.label == "Property taxes")
    assert taxes.overridden and taxes.amount == Decimal(0)

    restored = await clear_dti_override(
        db_session, loan_file=loan_file, field_key=taxes.key, actor_user_id=actor
    )
    assert restored.gated, "clearing the override puts the gate back — undo, with no new mechanism"


async def test_a_gate_a_zero_cannot_answer_is_reported_not_zeroed(db_session) -> None:
    """THE SHARPEST HALF OF THE DESIGN. Zeroing the subject's missing GROSS RENT asserts the property
    rents for nothing, which computes a net of minus its whole PITIA and carries the payment as an
    obligation — not "ungated", a different wrong answer, and in the opposite direction from the
    housing case.

    A processor who clicks Ungate and finds the file still gated, with nothing saying which part did
    not move, has been told less than before they clicked. So it is named in `unresolved`.
    """
    loan_file, company = await _file(db_session, "ungate-rental")
    actor = await _actor(db_session, company)
    prop = await factories.make_property(db_session, loan_file=loan_file)
    prop.occupancy_type = OccupancyType.INVESTMENT
    await db_session.flush()

    preview = await preview_dti_ungate(db_session, loan_file=loan_file)
    assert preview.unresolved, "the rental gate has no zero-shaped answer and must be named"
    assert any("rent" in reason.lower() for reason in preview.unresolved)

    applied = await apply_dti_ungate(
        db_session, loan_file=loan_file, note=None, actor_user_id=actor
    )
    assert applied.gated, "and the file stays gated, because that gate was not answered"


async def test_an_override_the_processor_already_set_survives_the_preview(db_session) -> None:
    """The hypothetical is layered ON TOP of stored overrides, not instead of them. A processor who
    corrected the tax figure yesterday must not see a preview that silently discards it."""
    loan_file, company = await _file(db_session, "ungate-layered")
    actor = await _actor(db_session, company)
    from app.schemas.dti import DtiOverrideInput
    from app.services.dti import HOUSING_INSURANCE

    await set_dti_override(
        db_session,
        loan_file=loan_file,
        field_key=HOUSING_INSURANCE,
        data=DtiOverrideInput(amount=Decimal("120.00")),
        actor_user_id=actor,
    )

    preview = await preview_dti_ungate(db_session, loan_file=loan_file)

    assert HOUSING_INSURANCE not in {line.key for line in preview.lines}, (
        "an already-corrected line is not unknown, so it is not something the ungate would zero"
    )


async def test_the_consent_does_not_list_an_input_as_both_fixed_and_unresolved(
    db_session: AsyncSession,
) -> None:
    """LP-643 review — a file gated BOTH ways, which is the case the preview's if/elif was reaching
    for and then handled identically in both arms.

    `gate_reason` is a JOIN of two independently-produced halves: the fail-closed housing reason and
    calculation-level reasons like the rental gate. Reporting the joined string put "Property taxes
    is unknown" in the unresolved list while the line directly above it promised to record property
    taxes as $0.00 — the same input, in one dialog, in opposite roles. A consent screen that
    contradicts itself is worse than one that says less, because the processor cannot tell which half
    to believe and this is the screen where they accept the assertion personally.

    The zeroable lines ARE the housing gate — both are `housing_items` where `unknown` — so an ungate
    resolves that half in full and what survives is everything else.
    """
    from app.models.property import OccupancyType

    loan_file, _ = await _file(db_session, "gated-both-ways")
    prop = await factories.make_property(db_session, loan_file=loan_file)
    # An investment subject with no rent schedule gates the calculation on TOP of the housing
    # unknowns every bare file has.
    prop.occupancy_type = OccupancyType.INVESTMENT
    await db_session.flush()

    current = await build_dti_calculation(db_session, loan_file=loan_file)
    assert current.housing_gate_reason and current.other_gate_reasons, (
        "the fixture must be gated BOTH ways or this asserts nothing"
    )

    preview = await preview_dti_ungate(db_session, loan_file=loan_file)
    fixed = {line.label for line in preview.lines}
    assert fixed, "the fixture must have zeroable lines or this asserts nothing"

    for label in fixed:
        for reason in preview.unresolved:
            assert label not in reason, (
                f"{label!r} is listed as a line the ungate will set to $0.00 AND named in an "
                f"unresolved reason: {reason!r}"
            )

    assert preview.unresolved, (
        "the rental gate survives an ungate and must still be reported — dropping it would trade a "
        "contradiction for a silence"
    )


async def test_the_preview_never_shows_a_confident_ratio_for_a_file_that_stays_gated(
    db_session: AsyncSession,
) -> None:
    """LP-643 UI review — the preview was the only DTI read returning RAW ratios.

    The other three endpoints apply `gate_display_ratios` at the API boundary; `GET /dti/ungate` did
    not. On a file that stays gated after an ungate the raw ratio still computes, because the unknown
    housing lines carry a fail-closed 0 — so the dialog rendered "Front-end: gated → 19.96%" directly
    above "This will still be gated afterwards". A confident number resting on a fabricated zero, on
    the one screen where a processor accepts an assertion personally: the LP-375 failure arriving
    through the preview.

    The investment subject is the fixture because its gate CANNOT be answered by a zero — zeroing the
    missing gross rent asserts the property rents for nothing — so it is guaranteed to survive the
    ungate and is exactly the case the ratio must not be shown for.
    """
    from app.models import StatedIncomeItem
    from app.models.property import OccupancyType

    loan_file, _ = await _file(db_session, "preview-stays-gated")
    borrower = await factories.make_borrower(db_session, loan_file=loan_file)
    db_session.add(
        StatedIncomeItem(
            borrower_id=borrower.id, monthly_amount=Decimal("10000.00"), income_type="Base"
        )
    )
    loan_file.loan_amount = Decimal("300000.00")
    loan_file.note_rate_percent = Decimal("7.000")
    loan_file.amortization_months = 360
    prop = await factories.make_property(db_session, loan_file=loan_file)
    prop.occupancy_type = OccupancyType.INVESTMENT
    await db_session.flush()

    preview = await preview_dti_ungate(db_session, loan_file=loan_file)

    assert preview.lines, "the fixture must have zeroable lines or this asserts nothing"
    assert preview.unresolved, "and must stay gated afterwards, or there is nothing to guard"
    assert preview.front_end_after is None and preview.back_end_after is None, (
        "the dialog would show a confident ratio for a file it also says stays gated — "
        f"front={preview.front_end_after}, back={preview.back_end_after}"
    )

    # THE OTHER DIRECTION: gating the display must not blank a ratio the ungate genuinely delivers.
    ok_file, _ = await _file(db_session, "preview-ungates-clean")
    ok_borrower = await factories.make_borrower(db_session, loan_file=ok_file)
    db_session.add(
        StatedIncomeItem(
            borrower_id=ok_borrower.id, monthly_amount=Decimal("10000.00"), income_type="Base"
        )
    )
    ok_file.loan_amount = Decimal("300000.00")
    ok_file.note_rate_percent = Decimal("7.000")
    ok_file.amortization_months = 360
    await db_session.flush()

    clean = await preview_dti_ungate(db_session, loan_file=ok_file)
    assert clean.lines and not clean.unresolved, "this file must ungate completely"
    assert clean.front_end_after is not None, (
        "a file the ungate fully resolves must show the ratio it will get — nulling every preview "
        "would trade a false number for no number"
    )
