"""Reminder suggestions (LP-814) — what is worth a nudge, and what a processor decided about it.

TWO ROUTERS, AND THE COMPANY-WIDE ONE IS THE POINT. "Nothing has happened on this file for a week"
is by definition about a file nobody is opening, so a per-file endpoint could never surface it: the
processor would have to visit the file to be told they have not visited the file.

IT SUGGESTS AND NEVER SENDS. Spec 4.5 says so, and nothing here writes a message, queues one, or
moves a need.
"""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.api.dependencies import CurrentUser, ScopedLoanFile
from app.core.database import DbSession
from app.models.reminder_snooze import ReminderKind
from app.services.reminders import Suggestion, build_suggestions, snooze, unsnooze

router = APIRouter(prefix="/reminders", tags=["reminders"])
file_router = APIRouter(prefix="/loan-files/{file_identifier}/reminders", tags=["reminders"])


class SuggestionPublic(BaseModel):
    """One suggestion, as a card renders it."""

    loan_file_id: UUID
    display_id: str
    kind: str
    subject_id: UUID | None
    summary: str
    days: int
    since: datetime

    @classmethod
    def of(cls, suggestion: Suggestion) -> "SuggestionPublic":
        return cls(
            loan_file_id=suggestion.loan_file_id,
            display_id=suggestion.display_id,
            kind=suggestion.kind.value,
            subject_id=suggestion.subject_id,
            summary=suggestion.summary,
            days=suggestion.days,
            since=suggestion.since,
        )


class SnoozeRequest(BaseModel):
    """Put a suggestion off, or refuse it.

    `until = null` IS A DISMISSAL, not a missing field. "Come back on Thursday" and "stop telling me"
    are the same decision at different distances, which is why they share a column — and why the
    absence of a date has to mean something rather than being rejected as incomplete.
    """

    kind: ReminderKind
    subject_id: UUID | None = None
    until: datetime | None = None
    note: str | None = None


class UnsnoozeRequest(BaseModel):
    kind: ReminderKind
    subject_id: UUID | None = None


@router.get("", response_model=list[SuggestionPublic])
async def across_the_company(db: DbSession, current_user: CurrentUser) -> list[SuggestionPublic]:
    """Everything worth a nudge, across every open file this company has, oldest problem first."""
    suggestions = await build_suggestions(db, company_id=current_user.company_id)
    return [SuggestionPublic.of(suggestion) for suggestion in suggestions]


@file_router.get("", response_model=list[SuggestionPublic])
async def for_one_file(
    loan_file: ScopedLoanFile, db: DbSession, current_user: CurrentUser
) -> list[SuggestionPublic]:
    suggestions = await build_suggestions(
        db, company_id=current_user.company_id, loan_file=loan_file
    )
    return [SuggestionPublic.of(suggestion) for suggestion in suggestions]


@file_router.post("/snooze", status_code=status.HTTP_204_NO_CONTENT)
async def put_off(
    payload: SnoozeRequest,
    loan_file: ScopedLoanFile,
    db: DbSession,
    current_user: CurrentUser,
) -> None:
    """Hide a suggestion until a date, or for good.

    SCOPED THROUGH THE FILE, so a snooze cannot be written against another company's — the same
    reason every other write in this product hangs off `ScopedLoanFile` rather than taking an id.
    """
    if payload.until is not None and payload.until <= datetime.now(payload.until.tzinfo):
        # A DATE IN THE PAST IS NOT A DISMISSAL, and treating it as one would be the more permissive
        # reading of a mistake. Refused so the caller says which they meant.
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Choose a time in the future, or omit it to dismiss.",
        )
    await snooze(
        db,
        loan_file=loan_file,
        kind=payload.kind,
        subject_id=payload.subject_id,
        until=payload.until,
        note=payload.note,
    )
    await db.commit()


@file_router.post("/unsnooze", status_code=status.HTTP_204_NO_CONTENT)
async def bring_back(
    payload: UnsnoozeRequest,
    loan_file: ScopedLoanFile,
    db: DbSession,
    current_user: CurrentUser,
) -> None:
    """Undo a snooze or a dismissal. A no-op when there was none, which is not an error."""
    await unsnooze(db, loan_file=loan_file, kind=payload.kind, subject_id=payload.subject_id)
    await db.commit()
