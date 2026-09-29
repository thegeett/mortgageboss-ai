"""A document that arrived for a condition item, and what code found when it checked it (LP-923).

One row per (item, document): one statement can answer several items (§4a change 2) and is checked once
for each. `checks` holds each check's result — `passed`, `failed` or `not_run`, with a plain reason — and
`findings` holds what the evidence step found in the document itself (a large deposit, B3-4.2-02).

`checks` and `findings` restate amounts, dates and account endings: NPI, so no readonly view carries
this table.
"""

from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import ForeignKey, Index, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin
from app.models.enums import str_enum


class EvidenceStatus(StrEnum):
    """`checked` by code; `accepted` by her, with a reason, over a failed check."""

    CHECKED = "checked"
    ACCEPTED = "accepted"


class ConditionEvidence(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "condition_evidence"
    __table_args__ = (
        UniqueConstraint("item_id", "document_id"),
        Index("ix_condition_evidence_condition_id", "condition_id"),
        Index("ix_condition_evidence_loan_file_id", "loan_file_id"),
    )

    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    loan_file_id: Mapped[UUID] = mapped_column(
        ForeignKey("loan_files.id", ondelete="CASCADE"), nullable=False
    )
    condition_id: Mapped[UUID] = mapped_column(
        ForeignKey("conditions.id", ondelete="CASCADE"), nullable=False
    )
    item_id: Mapped[UUID] = mapped_column(
        ForeignKey("condition_items.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[EvidenceStatus] = mapped_column(
        str_enum(EvidenceStatus),
        default=EvidenceStatus.CHECKED,
        server_default=EvidenceStatus.CHECKED.value,
        nullable=False,
    )
    #: `[{"check", "result": passed|failed|not_run, "reason"}]`, in the library's order.
    checks: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    #: `[{"kind": "large_deposit", "date", "amount", "description", "threshold", "income",
    #:   "assets_without", "required", "needed", "status": open|asked|explained, "reason"?}]`.
    findings: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    #: Her reason for accepting a failed check (S3-07's "Accept anyway…"). Kept in the history too.
    accepted_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    accepted_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
