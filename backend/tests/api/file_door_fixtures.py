"""One factory per door fixture kind (`file_doors.Fixture`), for `test_file_doors.py`.

Each builds, on one company with "restrict loan files to their team" ON, one loan file whose team is
exactly one processor (`member`), plus the child row its kind names, and returns the path
substitutions. The company also has an admin, a processor who is on no team (`outsider`), a
processor marked `sees_all_loans`, and a second processor nobody has placed (`processor_2`), for
the team door's body.

Rows are made directly where that is one line, and through the API as the admin where the API is the
honest way to make them (a stated item, an upload link): the admin sees every file either way.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import time, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from app.core.jwt import create_access_token
from app.models import Company, LoanFile, User, UserRole
from app.models.base import utcnow
from app.models.communication import (
    Communication,
    CommunicationChannel,
    CommunicationDirection,
    CommunicationStatus,
    FollowUpStatus,
)
from app.models.condition_draft import ConditionDraft, DraftRecipient
from app.models.condition_evidence import ConditionEvidence
from app.models.condition_item import ConditionItem
from app.models.condition_package import ConditionPackage, PackageStatus
from app.models.condition_round import ConditionRoundStatus
from app.models.document import Document, DocumentStatus
from app.models.dti_custom_line import DtiCustomLine
from app.models.finding import Finding, FindingCategory, FindingOrigin, FindingStatus
from app.models.inbound_message import InboundMessage, InboundRoutingState
from app.models.loan_file_participant import LoanFileParticipant
from app.models.loan_team import LoanTeamMember, TeamRole
from app.models.needs_item import NeedsItemStatus
from app.models.saved_view import SavedView
from app.models.snapshot_finding import SnapshotFinding
from app.services.loan_files import create_loan_file
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.api.file_doors import Fixture
from tests.integration.factories import (
    make_borrower,
    make_document,
    make_lender,
    make_needs_item,
    make_property,
)
from tests.models.conftest_helpers import make_condition, make_round
from tests.user_factory import make_user

PDF = (Path(__file__).resolve().parents[1] / "fixtures" / "attachments" / "clean.pdf").read_bytes()


@dataclass
class Shop:
    """The company, its people, the file, and what to put in the door's path."""

    company: Company
    admin: User
    member: User
    outsider: User
    sees_all: User
    processor_2: User
    loan_file: LoanFile
    subs: dict[str, str] = field(default_factory=dict)


def bearer(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


async def _person(db: AsyncSession, company: Company, first: str, role: UserRole) -> User:
    user = make_user(
        company_id=company.id,
        email=f"{first.lower()}-{uuid4().hex[:6]}@acme.example.com",
        hashed_password="x",  # pragma: allowlist secret
        first_name=first,
        last_name="Door",
        roles=[role],
    )
    db.add(user)
    await db.flush()
    return user


async def _shop(db: AsyncSession) -> Shop:
    company = Company(
        name="Door Shop",
        slug=f"doors-{uuid4().hex[:8]}",
        settings={"restrict_loans_to_team": True},
    )
    db.add(company)
    await db.flush()
    admin = await _person(db, company, "Ada", UserRole.ADMIN)
    company.owner_user_id = admin.id
    member = await _person(db, company, "Mia", UserRole.PROCESSOR)
    outsider = await _person(db, company, "Ned", UserRole.PROCESSOR)
    sees_all = await _person(db, company, "Sal", UserRole.PROCESSOR)
    sees_all.sees_all_loans = True
    processor_2 = await _person(db, company, "Pia", UserRole.PROCESSOR)
    lender = await make_lender(db, company=company, name=f"Door Bank {uuid4().hex[:6]}")
    loan_file = await create_loan_file(db, company_id=company.id, lender_id=lender.id)
    db.add(
        LoanTeamMember(loan_file_id=loan_file.id, user_id=member.id, team_role=TeamRole.PROCESSOR)
    )
    borrower = await make_borrower(db, loan_file=loan_file, ssn=None)
    borrower.email = "borrower@example.com"
    await db.flush()
    shop = Shop(company, admin, member, outsider, sees_all, processor_2, loan_file)
    shop.subs = {
        "file_identifier": loan_file.display_id,
        "identifier": loan_file.display_id,
        "loan_file_id": loan_file.display_id,
        "borrower_id": str(borrower.id),
        "lender_id": str(lender.id),
        "processor_2": str(processor_2.id),
    }
    return shop


Factory = Callable[[AsyncSession, AsyncClient, Shop], Awaitable[None]]


async def _file(db: AsyncSession, client: AsyncClient, shop: Shop) -> None:
    return None


async def _document(db: AsyncSession, client: AsyncClient, shop: Shop) -> None:
    document = await make_document(
        db,
        loan_file=shop.loan_file,
        company=shop.company,
        content=PDF,
        document_type="bank_statement",
        status=DocumentStatus.COMPLETED,
    )
    shop.subs["document_id"] = str(document.id)


async def _versioned_document(db: AsyncSession, client: AsyncClient, shop: Shop) -> None:
    """A document in a version group: the documents drawer asks for versions only then."""
    await _document(db, client, shop)
    document = await db.get(Document, UUID(shop.subs["document_id"]))
    assert document is not None
    document.version_group_id = document.id
    await db.flush()


async def _round(db: AsyncSession, client: AsyncClient, shop: Shop) -> None:
    round_ = await make_round(
        db, company=shop.company, loan_file=shop.loan_file, status=ConditionRoundStatus.DRAFT
    )
    shop.subs["round_id"] = str(round_.id)


async def _condition(db: AsyncSession, client: AsyncClient, shop: Shop) -> None:
    round_ = await make_round(
        db,
        company=shop.company,
        loan_file=shop.loan_file,
        status=ConditionRoundStatus.IMPORTED,
        round_number=1,
    )
    condition = await make_condition(
        db, company=shop.company, loan_file=shop.loan_file, round_=round_
    )
    # The reading the import gives every condition (LP-919), without the AI.
    condition.reading = {
        "source": "library",
        "type_id": None,
        "summary": "Provide the invoice for the credit report.",
        "items": [],
    }
    await db.flush()
    shop.subs["round_id"] = str(round_.id)
    shop.subs["condition_id"] = str(condition.id)


async def _condition_item(db: AsyncSession, client: AsyncClient, shop: Shop) -> None:
    await _condition(db, client, shop)
    await _document(db, client, shop)
    response = await client.post(
        f"/api/v1/conditions/{shop.subs['condition_id']}/items",
        json={"name": "Gift letter", "performers": ["borrower"]},
        headers=bearer(shop.admin),
    )
    assert response.status_code < 300, response.text
    item_id = await db.scalar(
        select(ConditionItem.id).where(
            ConditionItem.condition_id == UUID(shop.subs["condition_id"])
        )
    )
    assert item_id is not None
    shop.subs["item_id"] = str(item_id)


async def _evidence(db: AsyncSession, client: AsyncClient, shop: Shop) -> None:
    await _condition_item(db, client, shop)
    response = await client.post(
        f"/api/v1/conditions/{shop.subs['condition_id']}/items/{shop.subs['item_id']}/links",
        json={"document_id": shop.subs["document_id"]},
        headers=bearer(shop.admin),
    )
    assert response.status_code < 300, response.text
    evidence_id = await db.scalar(
        select(ConditionEvidence.id).where(ConditionEvidence.item_id == UUID(shop.subs["item_id"]))
    )
    assert evidence_id is not None
    shop.subs["evidence_id"] = str(evidence_id)


async def _outbound(db: AsyncSession, shop: Shop, status: CommunicationStatus) -> Communication:
    communication = Communication(
        loan_file_id=shop.loan_file.id,
        direction=CommunicationDirection.OUTBOUND,
        channel=CommunicationChannel.EMAIL,
        status=status,
        recipient="borrower@example.com",
        subject="Documents",
        body="Please send them.",
        initiated_by_user_id=shop.member.id,
        external_message_id=f"<{uuid4()}@example.com>",
        sent_at=utcnow() if status is CommunicationStatus.SENT else None,
        send_requested_at=utcnow() if status is CommunicationStatus.SENT else None,
    )
    db.add(communication)
    await db.flush()
    return communication


async def _outbound_draft(db: AsyncSession, client: AsyncClient, shop: Shop) -> None:
    """An unsent document request to the borrower."""
    draft = await _outbound(db, shop, CommunicationStatus.DRAFT)
    draft.party = "borrower"
    await db.flush()
    shop.subs["draft_id"] = str(draft.id)


async def _message(db: AsyncSession, client: AsyncClient, shop: Shop) -> None:
    """A sent request with its follow-up on, as Send leaves one."""
    message = await _outbound(db, shop, CommunicationStatus.SENT)
    message.follow_up_status = FollowUpStatus.ON
    message.follow_up_time = time(9, 0)
    message.follow_up_tz = "America/New_York"
    message.follow_up_clock_at = utcnow()
    await db.flush()
    shop.subs["communication_id"] = str(message.id)


async def _condition_draft(db: AsyncSession, client: AsyncClient, shop: Shop) -> None:
    await _condition(db, client, shop)
    communication = await _outbound(db, shop, CommunicationStatus.DRAFT)
    draft = ConditionDraft(
        company_id=shop.company.id,
        loan_file_id=shop.loan_file.id,
        communication_id=communication.id,
        round_id=UUID(shop.subs["round_id"]),
        recipient=DraftRecipient.BORROWER,
    )
    db.add(draft)
    await db.flush()
    shop.subs["draft_id"] = str(draft.id)


async def _package(db: AsyncSession, client: AsyncClient, shop: Shop) -> None:
    await _condition(db, client, shop)
    package = ConditionPackage(
        company_id=shop.company.id,
        loan_file_id=shop.loan_file.id,
        round_id=UUID(shop.subs["round_id"]),
        status=PackageStatus.BUILT,
        rows=[
            {
                "condition_id": shop.subs["condition_id"],
                "code": "7086",
                "file_name": None,
                "document_ids": [],
                "pages": 0,
                "note": "Invoice attached.",
                "note_source": "code",
                "fields": {},
                "included": True,
                "_facts": {},
            }
        ],
    )
    db.add(package)
    await db.flush()


async def _needs_item(db: AsyncSession, client: AsyncClient, shop: Shop) -> None:
    item = await make_needs_item(db, loan_file=shop.loan_file)
    shop.subs["needs_item_id"] = str(item.id)


async def _received_need(db: AsyncSession, client: AsyncClient, shop: Shop) -> None:
    """A need a document was matched to, waiting for her to confirm coverage (LP-108)."""
    item = await make_needs_item(db, loan_file=shop.loan_file)
    item.status = NeedsItemStatus.RECEIVED
    await db.flush()
    shop.subs["needs_item_id"] = str(item.id)


async def _property(db: AsyncSession, client: AsyncClient, shop: Shop) -> None:
    await make_property(db, loan_file=shop.loan_file)


async def _finding(db: AsyncSession, client: AsyncClient, shop: Shop) -> None:
    finding = Finding(
        loan_file_id=shop.loan_file.id,
        rule_id="cross_source.liability_discrepancy",
        origin=FindingOrigin.AI_CROSS_SOURCE,
        confidence=0.9,
        status=FindingStatus.YELLOW,
        category=FindingCategory.CREDIT,
        message="An undisclosed obligation appears in the documents.",
        details={"type": "liability_discrepancy", "document_value": "800/mo"},
    )
    db.add(finding)
    await db.flush()
    shop.subs["finding_id"] = str(finding.id)


async def _snapshot_finding(db: AsyncSession, client: AsyncClient, shop: Shop) -> None:
    finding = SnapshotFinding(
        loan_file_id=shop.loan_file.id,
        finding_key=uuid4().hex,
        snapshot_fingerprint=uuid4().hex,
        kind="valuation_mismatch",
        title="Values disagree",
        detail="The appraisal and the contract differ.",
        sources=[],
    )
    db.add(finding)
    await db.flush()
    shop.subs["finding_id"] = str(finding.id)


async def _via_api(client: AsyncClient, shop: Shop, path: str, body: dict[str, object]) -> str:
    response = await client.post(
        f"/api/v1/loan-files/{shop.loan_file.display_id}/{path}",
        json=body,
        headers=bearer(shop.admin),
    )
    assert response.status_code < 300, response.text
    return str(response.json()["id"])


async def _upload_link(db: AsyncSession, client: AsyncClient, shop: Shop) -> None:
    shop.subs["link_id"] = await _via_api(client, shop, "upload-links", {})


async def _participant(db: AsyncSession, client: AsyncClient, shop: Shop) -> None:
    response = await client.post(
        f"/api/v1/loan-files/{shop.loan_file.display_id}/party-requests/addresses",
        json={"role": "agent", "email": "agent@example.com"},
        headers=bearer(shop.admin),
    )
    assert response.status_code < 300, response.text
    participant_id = await db.scalar(
        select(LoanFileParticipant.id).where(
            LoanFileParticipant.loan_file_id == shop.loan_file.id,
            LoanFileParticipant.email == "agent@example.com",
        )
    )
    assert participant_id is not None
    shop.subs["participant_id"] = str(participant_id)


async def _dti_line(db: AsyncSession, client: AsyncClient, shop: Shop) -> None:
    line = DtiCustomLine(
        loan_file_id=shop.loan_file.id, section="debt", label="Car loan", value=300
    )
    db.add(line)
    await db.flush()
    shop.subs["line_id"] = str(line.id)


async def _stated_liability(db: AsyncSession, client: AsyncClient, shop: Shop) -> None:
    shop.subs["item_id"] = await _via_api(client, shop, "stated-liabilities", {})


async def _stated_asset(db: AsyncSession, client: AsyncClient, shop: Shop) -> None:
    shop.subs["item_id"] = await _via_api(client, shop, "stated-assets", {})


async def _stated_income(db: AsyncSession, client: AsyncClient, shop: Shop) -> None:
    shop.subs["item_id"] = await _via_api(
        client, shop, f"borrowers/{shop.subs['borrower_id']}/stated-income", {}
    )


async def _stated_employer(db: AsyncSession, client: AsyncClient, shop: Shop) -> None:
    shop.subs["item_id"] = await _via_api(
        client, shop, f"borrowers/{shop.subs['borrower_id']}/stated-employers", {}
    )


async def _team_member(db: AsyncSession, client: AsyncClient, shop: Shop) -> None:
    member_id = await db.scalar(
        select(LoanTeamMember.id).where(
            LoanTeamMember.loan_file_id == shop.loan_file.id,
            LoanTeamMember.user_id == shop.member.id,
        )
    )
    shop.subs["member_id"] = str(member_id)


async def _inbound(db: AsyncSession, shop: Shop, *, routed: bool) -> InboundMessage:
    message = InboundMessage(
        company_id=shop.company.id,
        loan_file_id=shop.loan_file.id if routed else None,
        ingest_key=uuid4().hex,
        message_id=f"<{uuid4()}@example.com>",
        from_address="borrower@example.com",
        subject="Statements",
        routing_state=InboundRoutingState.ROUTED if routed else InboundRoutingState.UNROUTED,
    )
    db.add(message)
    await db.flush()
    return message


async def _unrouted_message(db: AsyncSession, client: AsyncClient, shop: Shop) -> None:
    shop.subs["message_id"] = str((await _inbound(db, shop, routed=False)).id)


async def _routed_message(db: AsyncSession, client: AsyncClient, shop: Shop) -> None:
    shop.subs["message_id"] = str((await _inbound(db, shop, routed=True)).id)


async def _attachment(db: AsyncSession, client: AsyncClient, shop: Shop) -> None:
    from tests.services.test_inbound_triage_lp806 import _routed_attachment

    attachment = await _routed_attachment(
        db, loan_file=shop.loan_file, message_id=f"{uuid4().hex}@example.com"
    )
    shop.subs["attachment_id"] = str(attachment.id)


async def _reminder(db: AsyncSession, client: AsyncClient, shop: Shop) -> None:
    """A need asked for a month ago and not answered: a nudge (`reminders.PENDING_AFTER`)."""
    item = await make_needs_item(db, loan_file=shop.loan_file)
    item.status = NeedsItemStatus.REQUESTED
    item.requested_at = utcnow() - timedelta(days=30)
    await db.flush()


async def _saved_view(db: AsyncSession, client: AsyncClient, shop: Shop) -> None:
    db.add(
        SavedView(
            company_id=shop.company.id,
            owner_user_id=shop.admin.id,
            name="All files",
            filters={},
            is_shared=True,
        )
    )
    await db.flush()


FACTORIES: dict[Fixture, Factory] = {
    "file": _file,
    "borrower": _file,  # every shop's file has a borrower
    "document": _document,
    "versioned_document": _versioned_document,
    "condition": _condition,
    "condition_item": _condition_item,
    "evidence": _evidence,
    "round": _round,
    "condition_draft": _condition_draft,
    "package": _package,
    "outbound_draft": _outbound_draft,
    "message": _message,
    "needs_item": _needs_item,
    "received_need": _received_need,
    "property": _property,
    "finding": _finding,
    "snapshot_finding": _snapshot_finding,
    "upload_link": _upload_link,
    "attachment": _attachment,
    "participant": _participant,
    "dti_line": _dti_line,
    "stated_liability": _stated_liability,
    "stated_asset": _stated_asset,
    "stated_income": _stated_income,
    "stated_employer": _stated_employer,
    "team_member": _team_member,
    "unrouted_message": _unrouted_message,
    "routed_message": _routed_message,
    "reminder": _reminder,
    "saved_view": _saved_view,
}


async def build(db: AsyncSession, client: AsyncClient, kind: Fixture) -> Shop:
    """A shop, and the child row ``kind`` names on its file."""
    shop = await _shop(db)
    await FACTORIES[kind](db, client, shop)
    return shop
