"""The evidence record and the legal hold (LP-821).

WHO MAY SEE WHAT. Reading the record is a processor's job — "what did we actually send them" is the
question a file's own screen answers. Placing and lifting a HOLD is admin-gated: it suspends every
destruction path on a file and, once destruction exists, the difference between a retention policy
and a spoliation finding runs through it.

NOTHING HERE EDITS OR DELETES AN EVIDENCE ROW, and there is no route that could. §6's "must not be
soft-deletable" is a property of the surface as well as the table.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.api.dependencies import CurrentUser, ScopedLoanFile, require_role
from app.core.database import DbSession
from app.models.communication_evidence import CommunicationEvidence
from app.models.user import UserRole
from app.services.evidence import (
    LegalHoldError,
    evidence_for,
    lift_hold,
    place_hold,
)

router = APIRouter(prefix="/loan-files/{file_identifier}", tags=["evidence"])

_ADMIN = Depends(require_role(UserRole.ADMIN))


class EvidencePublic(BaseModel):
    """One recorded event.

    THE BODIES ARE NOT RETURNED. An evidence row holds what was sent and what was composed, and both
    are borrower-facing prose; the screen's question is "what happened, under which template, and was
    it edited" — which `was_edited` answers without reproducing either. Reading the actual words is a
    legal request, not a page load, and it should leave a trace this endpoint does not create.
    """

    id: UUID
    event: str
    recorded_at: datetime
    approver_user_id: UUID | None
    template_key: str | None
    template_version: str | None
    guardrail_fired: str | None
    failure_reason: str | None
    model_id: str | None
    prompt_version: str | None
    auth_verdicts: dict[str, Any]
    attachment_count: int
    #: True when the processor changed the drafted words before sending.
    was_edited: bool
    #: False on every row written before LP-821 — the composed version is gone, not merely absent.
    has_composed_draft: bool

    @classmethod
    def of(cls, row: CommunicationEvidence) -> "EvidencePublic":
        return cls(
            id=row.id,
            event=row.event.value,
            recorded_at=row.recorded_at,
            approver_user_id=row.approver_user_id,
            template_key=row.template_key,
            template_version=row.template_version,
            guardrail_fired=row.guardrail_fired,
            failure_reason=row.failure_reason,
            model_id=row.model_id,
            prompt_version=row.prompt_version,
            auth_verdicts={k: str(v) for k, v in (row.auth_verdicts or {}).items()},
            attachment_count=len(row.attachment_manifest or []),
            was_edited=(row.body_composed is not None and row.body_as_sent != row.body_composed),
            has_composed_draft=row.body_composed is not None,
        )


class HoldRequest(BaseModel):
    """Why the file is being held.

    REQUIRED. FRCP 37(e) asks what a party knew and when, and a hold with no stated reason answers
    only the second half.
    """

    reason: str = Field(min_length=1, max_length=500)


class HoldPublic(BaseModel):
    legal_hold: bool
    legal_hold_at: datetime | None
    legal_hold_reason: str | None


@router.get("/evidence", response_model=list[EvidencePublic])
async def read_evidence(
    loan_file: ScopedLoanFile, db: DbSession, current_user: CurrentUser
) -> list[EvidencePublic]:
    """Every recorded event on this file, oldest first."""
    return [EvidencePublic.of(row) for row in await evidence_for(db, loan_file=loan_file)]


@router.get("/legal-hold", response_model=HoldPublic)
async def read_hold(
    loan_file: ScopedLoanFile, db: DbSession, current_user: CurrentUser
) -> HoldPublic:
    """Whether this file is held. NOT admin-gated — a processor about to act on a file needs to know
    it is under hold, and hiding that from them is how somebody deletes something."""
    return HoldPublic(
        legal_hold=loan_file.legal_hold,
        legal_hold_at=loan_file.legal_hold_at,
        legal_hold_reason=loan_file.legal_hold_reason,
    )


@router.post("/legal-hold", response_model=HoldPublic)
async def hold(
    payload: HoldRequest,
    loan_file: ScopedLoanFile,
    db: DbSession,
    current_user: CurrentUser,
    _: None = _ADMIN,
) -> HoldPublic:
    """Suspend every destruction path for this file."""
    try:
        await place_hold(
            db, loan_file=loan_file, reason=payload.reason, actor_user_id=current_user.id
        )
    except LegalHoldError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await db.commit()
    return HoldPublic(
        legal_hold=loan_file.legal_hold,
        legal_hold_at=loan_file.legal_hold_at,
        legal_hold_reason=loan_file.legal_hold_reason,
    )


@router.delete("/legal-hold", response_model=HoldPublic)
async def release(
    loan_file: ScopedLoanFile,
    db: DbSession,
    current_user: CurrentUser,
    _: None = _ADMIN,
) -> HoldPublic:
    """Release the file.

    NO REASON REQUIRED, deliberately, and the asymmetry with placing is the point: requiring a
    justification to LIFT would make lifting harder than placing, which is the wrong way round for a
    control whose failure mode is holding everything forever. The activity log records who and when.
    """
    await lift_hold(db, loan_file=loan_file, actor_user_id=current_user.id)
    await db.commit()
    return HoldPublic(legal_hold=False, legal_hold_at=None, legal_hold_reason=None)
