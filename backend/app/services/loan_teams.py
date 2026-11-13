"""Who works a loan file (LP-MB-Admin-05, ADR-445).

A file's team is at most one loan officer (a user) and any number of processors. The functions here
take an :class:`~app.api.dependencies.Actor` and a file that already came through the tenant gate.

WHO MAY CHANGE IT: an Admin on any file; a loan officer on a file where they are the loan officer
(``core.permissions.may_change_team``). A processor may not.

WHO MAY BE ON IT: an active user of the file's company holding the slot's role (LOAN_OFFICER for the
loan officer, PROCESSOR for a processor). An Admin with neither is not added: they see every file.

THE INTERNAL LOAN OFFICER IS COPIED INTO THE TEXT FIELDS. `loan_officer_name` / `loan_officer_email`
are read in many places (the inbound trust list, condition drafts, the overview, intake), so assigning
a user writes their name and email there and re-seeds the participants; while a user is assigned the
text cannot be edited (``LoanOfficerIsInternal``). Clearing the user blanks the text only if it still
holds that user's values: a hand-edited contact stays.

Every change writes one ``LOAN_TEAM_CHANGED`` entry on the file's timeline.
"""

from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotEligible, UserRuleError
from app.core.permissions import Permission, PermissionDeniedError, may_change_team
from app.models.activity_log import ActivityType
from app.models.base import utcnow
from app.models.loan_file import LoanFile
from app.models.loan_team import LoanTeamMember, TeamRole
from app.models.user import User, UserRole
from app.services.activity_log import log_activity
from app.services.authorization import ensure
from app.services.company_audit import AuditAction, log_company_action
from app.services.inbound_participants import seed_participants

if TYPE_CHECKING:
    from app.api.dependencies import Actor

#: The role a person must hold to take each slot.
SLOT_ROLE = {TeamRole.LOAN_OFFICER: UserRole.LOAN_OFFICER, TeamRole.PROCESSOR: UserRole.PROCESSOR}
SLOT_WORDS = {
    TeamRole.LOAN_OFFICER: "loan officer",
    TeamRole.PROCESSOR: "processor",
    TeamRole.ASSISTANT: "assistant",
}


class TeamChangedMeanwhile(UserRuleError):
    """Two changes to the same slot at once; the other one won."""

    message = "Someone else just changed this team. Reload and try again."


# --------------------------------------------------------------------------- #
# Reading
# --------------------------------------------------------------------------- #


async def live_members(db: AsyncSession, loan_file_id: UUID) -> list[LoanTeamMember]:
    """The file's team as it is now, read from the table (not the possibly stale relationship)."""
    rows = await db.scalars(
        select(LoanTeamMember)
        .where(LoanTeamMember.loan_file_id == loan_file_id, LoanTeamMember.deleted_at.is_(None))
        .order_by(LoanTeamMember.created_at)
        .execution_options(populate_existing=True)
    )
    return list(rows)


async def _loan_officer(db: AsyncSession, loan_file_id: UUID) -> LoanTeamMember | None:
    for member in await live_members(db, loan_file_id):
        if member.team_role is TeamRole.LOAN_OFFICER:
            return member
    return None


async def has_internal_loan_officer(db: AsyncSession, loan_file_id: UUID) -> bool:
    """Whether the file's loan officer is a user (so its text fields follow that account)."""
    return await _loan_officer(db, loan_file_id) is not None


async def can_change(db: AsyncSession, actor: "Actor", loan_file: LoanFile) -> bool:
    lo = await _loan_officer(db, loan_file.id)
    return may_change_team(
        actor.roles, is_files_loan_officer=lo is not None and lo.user_id == actor.user.id
    )


async def can_change_team(db: AsyncSession, actor: "Actor", loan_file: LoanFile) -> None:
    """Refuse unless the actor may change this file's team (Admin anywhere, the LO on their file)."""
    if not await can_change(db, actor, loan_file):
        raise PermissionDeniedError(Permission.LOAN_TEAM_CHANGE)


# --------------------------------------------------------------------------- #
# Writing
# --------------------------------------------------------------------------- #


async def _eligible(db: AsyncSession, loan_file: LoanFile, user_id: UUID, slot: TeamRole) -> User:
    """The user, if they may take ``slot`` on this file; else ``NotEligible`` saying why."""
    user = await db.scalar(
        select(User).where(
            User.id == user_id,
            User.company_id == loan_file.company_id,
            User.deleted_at.is_(None),
        )
    )
    if user is None or not user.is_active:
        raise NotEligible("Only an active person in your company can be on a file's team")
    needed = SLOT_ROLE[slot]
    if needed not in user.role_set:
        word = "Loan officer" if needed is UserRole.LOAN_OFFICER else "Processor"
        raise NotEligible(f"{user.full_name} needs the {word} role to be a {SLOT_WORDS[slot]}")
    return user


async def _name(db: AsyncSession, user_id: UUID | None) -> str | None:
    if user_id is None:
        return None
    user = await db.get(User, user_id)
    return user.full_name if user else None


async def _timeline(
    db: AsyncSession,
    actor_user: User | None,
    loan_file: LoanFile,
    *,
    slot: TeamRole,
    from_user_id: UUID | None,
    to_user_id: UUID | None,
    summary: str,
) -> None:
    await log_activity(
        db,
        loan_file_id=loan_file.id,
        activity_type=ActivityType.LOAN_TEAM_CHANGED,
        summary=summary,
        actor_user_id=actor_user.id if actor_user else None,
        detail={
            "slot": slot.value,
            "from_user_id": str(from_user_id) if from_user_id else None,
            "to_user_id": str(to_user_id) if to_user_id else None,
            "from_name": await _name(db, from_user_id),
            "to_name": await _name(db, to_user_id),
        },
    )


async def _insert(db: AsyncSession, member: LoanTeamMember) -> None:
    """Insert a member in a SAVEPOINT: a concurrent change that took the slot first loses cleanly."""
    try:
        async with db.begin_nested():
            db.add(member)
            await db.flush()
    except IntegrityError as exc:
        raise TeamChangedMeanwhile() from exc


async def _write_through(
    db: AsyncSession, loan_file: LoanFile, old: User | None, new: User | None
) -> None:
    """Keep the loan-officer text fields on the internal loan officer, then re-seed participants."""
    if new is not None:
        loan_file.loan_officer_name = new.full_name
        loan_file.loan_officer_email = new.email
    elif old is not None:
        # Cleared: blank the text only where it is still that person's, so a hand edit stays.
        if loan_file.loan_officer_name == old.full_name:
            loan_file.loan_officer_name = None
        if loan_file.loan_officer_email == old.email:
            loan_file.loan_officer_email = None
    await db.flush()
    await seed_participants(db, loan_file=loan_file)


async def _place_loan_officer(
    db: AsyncSession,
    actor_user: User | None,
    loan_file: LoanFile,
    user_id: UUID | None,
    *,
    added_by: UUID | None,
) -> bool:
    """Set the loan officer (or none). Returns False when nothing changed."""
    current = await _loan_officer(db, loan_file.id)
    if (current.user_id if current else None) == user_id:
        return False
    new_user = await _eligible(db, loan_file, user_id, TeamRole.LOAN_OFFICER) if user_id else None
    old_user = await db.get(User, current.user_id) if current else None
    if current is not None:
        current.deleted_at = utcnow()
        await db.flush()
    if new_user is not None:
        await _insert(
            db,
            LoanTeamMember(
                loan_file_id=loan_file.id,
                user_id=new_user.id,
                team_role=TeamRole.LOAN_OFFICER,
                added_by_user_id=added_by,
            ),
        )
    await _write_through(db, loan_file, old_user, new_user)
    who = actor_user.full_name if actor_user else "MortgageBoss"
    if new_user and old_user:
        summary = (
            f"{who} changed the loan officer from {old_user.full_name} to {new_user.full_name}"
        )
    elif new_user:
        summary = f"{who} made {new_user.full_name} the loan officer"
    else:
        summary = f"{who} removed {old_user.full_name if old_user else 'the loan officer'} as loan officer"
    await _timeline(
        db,
        actor_user,
        loan_file,
        slot=TeamRole.LOAN_OFFICER,
        from_user_id=old_user.id if old_user else None,
        to_user_id=new_user.id if new_user else None,
        summary=summary,
    )
    return True


async def set_loan_officer(
    db: AsyncSession, actor: "Actor", loan_file: LoanFile, user_id: UUID | None
) -> None:
    """Make ``user_id`` the file's loan officer, replacing any other; ``None`` removes it."""
    await can_change_team(db, actor, loan_file)
    await _place_loan_officer(db, actor.user, loan_file, user_id, added_by=actor.user.id)


async def add_processor(
    db: AsyncSession, actor: "Actor", loan_file: LoanFile, user_id: UUID
) -> None:
    """Add a processor. Already on the team as one: nothing happens."""
    await can_change_team(db, actor, loan_file)
    user = await _eligible(db, loan_file, user_id, TeamRole.PROCESSOR)
    if any(
        m.user_id == user.id and m.team_role is TeamRole.PROCESSOR
        for m in await live_members(db, loan_file.id)
    ):
        return
    await _insert(
        db,
        LoanTeamMember(
            loan_file_id=loan_file.id,
            user_id=user.id,
            team_role=TeamRole.PROCESSOR,
            added_by_user_id=actor.user.id,
        ),
    )
    await _timeline(
        db,
        actor.user,
        loan_file,
        slot=TeamRole.PROCESSOR,
        from_user_id=None,
        to_user_id=user.id,
        summary=f"{actor.user.full_name} added {user.full_name} as processor",
    )


async def remove_member(
    db: AsyncSession, actor: "Actor", loan_file: LoanFile, member_id: UUID
) -> bool:
    """Take a member off the team. False if there is no such live member on this file."""
    await can_change_team(db, actor, loan_file)
    member = next((m for m in await live_members(db, loan_file.id) if m.id == member_id), None)
    if member is None:
        return False
    if member.team_role is TeamRole.LOAN_OFFICER:
        # Removing the loan officer is clearing the slot, with the same text-field rule.
        await _place_loan_officer(db, actor.user, loan_file, None, added_by=actor.user.id)
        return True
    member.deleted_at = utcnow()
    await db.flush()
    await _timeline(
        db,
        actor.user,
        loan_file,
        slot=member.team_role,
        from_user_id=member.user_id,
        to_user_id=None,
        summary=f"{actor.user.full_name} removed {await _name(db, member.user_id)} as "
        f"{SLOT_WORDS[member.team_role]}",
    )
    return True


async def on_loan_file_created(db: AsyncSession, actor: "Actor", loan_file: LoanFile) -> None:
    """The creator joins the team: as loan officer if they hold LOAN_OFFICER, else as processor if
    they hold PROCESSOR, else (an Admin with neither) nobody."""
    roles = actor.user.role_set
    if UserRole.LOAN_OFFICER in roles:
        await _place_loan_officer(db, actor.user, loan_file, actor.user.id, added_by=None)
    elif UserRole.PROCESSOR in roles:
        await _insert(
            db,
            LoanTeamMember(
                loan_file_id=loan_file.id,
                user_id=actor.user.id,
                team_role=TeamRole.PROCESSOR,
                added_by_user_id=None,
            ),
        )
        await _timeline(
            db,
            actor.user,
            loan_file,
            slot=TeamRole.PROCESSOR,
            from_user_id=None,
            to_user_id=actor.user.id,
            summary=f"{actor.user.full_name} joined the team as processor",
        )


# --------------------------------------------------------------------------- #
# Handing someone's files to another person
# --------------------------------------------------------------------------- #


async def reassign_user_loans(
    db: AsyncSession, actor: "Actor", from_user_id: UUID, to_user_id: UUID
) -> int | None:
    """Move every live team place of ``from_user`` to ``to_user``, slot for slot. Returns the count,
    or ``None`` if either person is not in the actor's company.

    The target must be eligible for EVERY slot it receives (an LO slot needs LOAN_OFFICER), checked
    before anything moves. Where the target already holds that slot on a file, the place is simply
    vacated. One company audit row, and one timeline entry per file.
    """
    ensure(actor, Permission.USERS_MANAGE)
    people = {
        u.id: u
        for u in await db.scalars(
            select(User).where(
                User.id.in_([from_user_id, to_user_id]),
                User.company_id == actor.company_id,
                User.deleted_at.is_(None),
            )
        )
    }
    source, target = people.get(from_user_id), people.get(to_user_id)
    if source is None or target is None or from_user_id == to_user_id:
        return None
    places = list(
        await db.scalars(
            select(LoanTeamMember)
            .join(LoanFile, LoanFile.id == LoanTeamMember.loan_file_id)
            .where(
                LoanTeamMember.user_id == from_user_id,
                LoanTeamMember.deleted_at.is_(None),
                LoanFile.company_id == actor.company_id,
                LoanFile.deleted_at.is_(None),
            )
            .with_for_update(of=LoanTeamMember)
        )
    )
    if not target.is_active:
        raise NotEligible("Files can only be moved to an active person")
    for slot in {place.team_role for place in places}:
        needed = SLOT_ROLE.get(slot)
        if needed is not None and needed not in target.role_set:
            word = "Loan officer" if needed is UserRole.LOAN_OFFICER else "Processor"
            raise NotEligible(f"{target.full_name} needs the {word} role to take these files")

    for place in places:
        loan_file = await db.get(LoanFile, place.loan_file_id)
        assert loan_file is not None
        if place.team_role is TeamRole.LOAN_OFFICER:
            await _place_loan_officer(db, actor.user, loan_file, target.id, added_by=actor.user.id)
            continue
        place.deleted_at = utcnow()
        await db.flush()
        holds = await db.scalar(
            select(func.count())
            .select_from(LoanTeamMember)
            .where(
                LoanTeamMember.loan_file_id == loan_file.id,
                LoanTeamMember.user_id == target.id,
                LoanTeamMember.team_role == place.team_role,
                LoanTeamMember.deleted_at.is_(None),
            )
        )
        if not holds:
            await _insert(
                db,
                LoanTeamMember(
                    loan_file_id=loan_file.id,
                    user_id=target.id,
                    team_role=place.team_role,
                    added_by_user_id=actor.user.id,
                ),
            )
        await _timeline(
            db,
            actor.user,
            loan_file,
            slot=place.team_role,
            from_user_id=source.id,
            to_user_id=target.id,
            summary=f"{actor.user.full_name} moved {source.full_name}'s place as "
            f"{SLOT_WORDS[place.team_role]} to {target.full_name}",
        )

    await log_company_action(
        db,
        company_id=actor.company_id,
        actor_user_id=actor.user.id,
        action=AuditAction.LOANS_REASSIGNED,
        target_type="user",
        target_id=source.id,
        summary=f"Moved {len(places)} file places from {source.full_name} to {target.full_name}",
        detail={
            "count": len(places),
            "from_user_id": str(source.id),
            "to_user_id": str(target.id),
        },
    )
    return len(places)


async def live_place_counts(db: AsyncSession, company_id: UUID) -> dict[UUID, int]:
    """How many live files each person of the company is on (a person counted once per file)."""
    rows = await db.execute(
        select(LoanTeamMember.user_id, func.count(func.distinct(LoanTeamMember.loan_file_id)))
        .join(LoanFile, LoanFile.id == LoanTeamMember.loan_file_id)
        .where(
            LoanTeamMember.deleted_at.is_(None),
            LoanFile.company_id == company_id,
            LoanFile.deleted_at.is_(None),
        )
        .group_by(LoanTeamMember.user_id)
    )
    return dict(rows.tuples().all())


def team_view(members: list[LoanTeamMember]) -> dict[str, Any]:
    """The team as the API returns it: the loan officer (with licensing) and the processors."""

    def one(member: LoanTeamMember) -> dict[str, Any]:
        user = member.user
        return {
            "id": member.id,
            "user_id": member.user_id,
            "name": user.full_name,
            "email": user.email,
            "team_role": member.team_role,
            "nmls_id": user.nmls_id if member.team_role is TeamRole.LOAN_OFFICER else None,
            "licensed_states": (
                list(user.licensed_states) if member.team_role is TeamRole.LOAN_OFFICER else []
            ),
        }

    lo = next((m for m in members if m.team_role is TeamRole.LOAN_OFFICER), None)
    return {
        "loan_officer": one(lo) if lo else None,
        "processors": [one(m) for m in members if m.team_role is TeamRole.PROCESSOR],
    }
