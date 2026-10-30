"""Helpers for LP-994's send tests: a file ready to send, and fakes for the sender and storage.

`ready_to_send` builds a company with an active mail domain, a processor, a loan file and a draft
asking for one need. The caller turns file addresses on (`file_addresses_on`) and sets
`settings.mail_transport`, as a deployment that sends would.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from email.message import EmailMessage
from uuid import uuid4

from app.models import Company, LoanProgram, User, UserRole
from app.models.communication import Communication
from app.models.loan_file import LoanFile
from app.models.needs_item import NeedsItem, NeedsItemOrigin
from app.services.email_draft import add_needs_to_draft
from app.services.loan_files import create_loan_file
from app.services.mail_sender import MailSender
from sqlalchemy.ext.asyncio import AsyncSession
from tests.mail_address import link_mail_domain


@dataclass
class Ready:
    company: Company
    user: User
    loan_file: LoanFile
    need: NeedsItem
    draft: Communication
    domain: str


async def ready_to_send(db: AsyncSession, *, with_domain: bool = True) -> Ready:
    company = Company(name="Summit Mortgage Processing", slug=f"summit-{uuid4().hex[:8]}")
    db.add(company)
    await db.flush()
    user = User(
        company_id=company.id,
        email=f"pat-{uuid4().hex[:8]}@example.test",
        hashed_password="x",  # pragma: allowlist secret
        first_name="Pat",
        last_name="Processor",
        role=UserRole.PROCESSOR,
    )
    db.add(user)
    await db.flush()
    domain = await link_mail_domain(db, company.id) if with_domain else ""
    loan_file = await create_loan_file(
        db, company_id=company.id, loan_program=LoanProgram.CONVENTIONAL
    )
    need = NeedsItem(
        loan_file_id=loan_file.id,
        title="Bank statements",
        needs_type="bank_statement",
        origin=NeedsItemOrigin.FINDING,
    )
    db.add(need)
    await db.flush()
    result = await add_needs_to_draft(db, loan_file=loan_file, needs=[need], actor_user_id=user.id)
    return Ready(company, user, loan_file, need, result.draft, domain)


@dataclass
class FakeSender(MailSender):
    """Records each message's wire bytes; returns a provider id, or raises `error`."""

    sent: list[EmailMessage] = field(default_factory=list)
    error: Exception | None = None

    def send(self, message: EmailMessage) -> str:
        self.sent.append(message)
        if self.error is not None:
            raise self.error
        return f"ses-{len(self.sent)}"


@dataclass
class FakeStorage:
    saved: dict[str, bytes] = field(default_factory=dict)
    fail: bool = False

    async def save_at(self, *, storage_path: str, content: bytes) -> str:
        if self.fail:
            raise OSError("disk full")
        self.saved[storage_path] = content
        return storage_path
