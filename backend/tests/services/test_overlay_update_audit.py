"""The overlay writer's audit trail (LP-UI-026).

`update_lender_overlay` had no test at all. The defect it shipped — an admin
DELETING an override recorded as "saved the overlay with no threshold changes",
with no record the override ever existed — was found on a screenshot, fixed in
`field_changes` two layers below, and guarded there.

That leaves the wiring uncovered: a later change to how this function builds
`before` and `after` reintroduces the same visible defect with the shared helper
still correct and its test still green. This is the layer the bug was actually
seen at.
"""

from decimal import Decimal
from uuid import uuid4

import pytest
from app.models.company import Company
from app.models.lender import Lender
from app.schemas.overlay_admin import OverlayOverrideInput, OverlayUpdateRequest
from app.services.overlay_admin import (
    UnknownOverlayRuleError,
    _base_rule_index,
    _stored_audit,
    _stored_overrides,
    update_lender_overlay,
)
from sqlalchemy.ext.asyncio import AsyncSession

RULE = sorted(_base_rule_index())[0]
OTHER_RULE = sorted(_base_rule_index())[1]


async def _lender(db_session: AsyncSession, overlays: object = None) -> Lender:
    company = Company(name="Acme", slug=f"acme-{uuid4().hex[:8]}")
    db_session.add(company)
    await db_session.flush()
    lender = Lender(
        company_id=company.id,
        name="UWM",
        slug=f"uwm-{uuid4().hex[:8]}",
        supported_programs=["conventional"],
        lender_overlays=overlays or {},
    )
    db_session.add(lender)
    await db_session.flush()
    return lender


def _request(*overrides: tuple[str, str], reason: str = "because") -> OverlayUpdateRequest:
    return OverlayUpdateRequest(
        overrides=[
            OverlayOverrideInput(rule_id=rule_id, value=Decimal(value))
            for rule_id, value in overrides
        ],
        reason=reason,
    )


async def _save(db_session: AsyncSession, lender: Lender, request: OverlayUpdateRequest) -> Lender:
    saved = await update_lender_overlay(
        db_session,
        company_id=lender.company_id,
        lender_id=lender.id,
        request=request,
        actor_user_id=uuid4(),
    )
    assert saved is not None
    return saved


class TestTheAuditRecordsWhatHappened:
    async def test_a_removal_is_recorded(self, db_session: AsyncSession) -> None:
        """The defect, at the layer it was seen. Deleting an override is a change."""
        lender = await _lender(db_session)
        await _save(db_session, lender, _request((RULE, "45")))

        saved = await _save(db_session, lender, _request())

        assert _stored_overrides(saved) == []
        changes = _stored_audit(saved)[-1]["changes"]
        assert changes, "deleting an override recorded no change at all"
        assert changes[0]["field"] == RULE
        assert changes[0]["from"] == "45"
        assert changes[0]["to"] is None

    async def test_an_addition_is_recorded(self, db_session: AsyncSession) -> None:
        lender = await _lender(db_session)
        saved = await _save(db_session, lender, _request((RULE, "45")))
        change = _stored_audit(saved)[-1]["changes"][0]
        assert (change["from"], change["to"]) == (None, "45")

    async def test_an_edit_records_from_and_to(self, db_session: AsyncSession) -> None:
        lender = await _lender(db_session)
        await _save(db_session, lender, _request((RULE, "45")))
        saved = await _save(db_session, lender, _request((RULE, "50")))
        change = _stored_audit(saved)[-1]["changes"][0]
        assert (change["from"], change["to"]) == ("45", "50")

    async def test_a_removal_alongside_a_survivor_records_only_the_removal(
        self, db_session: AsyncSession
    ) -> None:
        # The survivor is unchanged, so it is not a change; the removal is.
        lender = await _lender(db_session)
        await _save(db_session, lender, _request((RULE, "45"), (OTHER_RULE, "10")))
        saved = await _save(db_session, lender, _request((OTHER_RULE, "10")))
        changes = _stored_audit(saved)[-1]["changes"]
        assert [c["field"] for c in changes] == [RULE]

    async def test_every_edit_appends_rather_than_replacing(self, db_session: AsyncSession) -> None:
        """An audit trail that overwrites is not a trail."""
        lender = await _lender(db_session)
        await _save(db_session, lender, _request((RULE, "45")))
        saved = await _save(db_session, lender, _request())
        assert len(_stored_audit(saved)) == 2


class TestTheGates:
    async def test_another_companys_lender_is_not_found(self, db_session: AsyncSession) -> None:
        lender = await _lender(db_session)
        result = await update_lender_overlay(
            db_session,
            company_id=uuid4(),
            lender_id=lender.id,
            request=_request((RULE, "45")),
            actor_user_id=uuid4(),
        )
        assert result is None

    async def test_an_unknown_rule_is_refused(self, db_session: AsyncSession) -> None:
        # Refused rather than stored: an override naming a rule that does not
        # exist can never apply, and would sit in the blob being counted.
        lender = await _lender(db_session)
        with pytest.raises(UnknownOverlayRuleError):
            await _save(db_session, lender, _request(("not.a.rule", "45")))
