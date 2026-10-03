"""Her links between a condition item and a document (LP-953, the staging trial's item 7).

THE DOORS. A document reaches an item's evidence through exactly these, and every rule below holds at each:
1. **Arrival** — `condition_evidence.check_document`, after the needs pass: the one matching rule
   (`condition_matching.document_answers`), skipping what she unlinked.
2. **Plan time** — `condition_plan._find_document` ("Already in the file", found): the same rule.
3. **Link** — `link_document`: she picks a document of this file (and a page).
4. **Change** — `link_document(replace_document_id=…)`: unlink the old, link the new, in one transaction.
5. **Unlink** — `unlink_document`.
6. **Upload here** — the documents upload route with `condition_item_id`: the upload is linked as she
   uploads it, and checked when it has been read.
7. **"Already in the file" chosen by hand** — refused unless the item already has a linked document
   (`condition_plan`): choosing it means linking one.
Another file's document, or another file's item, is not found (404) at 3, 4, 5 and 6.

WHAT IS TRUE. The evidence row is the link: it carries the checks and findings `_settle` reads. The item's
`document_id` / `document_page` is a POINTER that follows the row (set on link, cleared on unlink).

HER CHOICE IS A STORED FACT, never inferred from an absent link (the `owner_override` pattern):
- a link she makes is an evidence row with `origin = manual`, so its checks run and show like any other;
- an unlink DELETES the evidence row (no query over evidence has to remember to skip it, so nothing hidden
  can hold the condition) and writes `condition_item_unlinks`, which is what stops doors 1 and 2 putting it
  back. Linking the same document again by hand deletes that row.

A MISMATCHED LINK IS ALLOWED AND SAID. A document whose type the item does not ask for fails a "Right
document type" check naming both types, so the item is not done and the condition cannot reach Ready by
itself. She can "Accept anyway", with her reason: that is her decision, recorded, and the package then
carries the document like any accepted evidence.

NO NPI IN LOGS: ids, codes and counts.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.condition import Condition, ConditionPrepStatus
from app.models.condition_draft import ConditionDraft
from app.models.condition_event import ConditionEvent, ConditionEventKind
from app.models.condition_evidence import (
    ConditionEvidence,
    ConditionItemUnlink,
    EvidenceOrigin,
)
from app.models.condition_item import ConditionItem
from app.models.condition_vocabulary import ConditionItemStatus, PlanOption
from app.models.document import Document, DocumentStatus
from app.models.helpers import only_active

logger = structlog.get_logger(__name__)

NOT_ON_FILE = "That document is not on this file."
CLOSED = "This condition is closed: a link would change nothing."
ALREADY_LINKED = "That document is already linked to this item."
NOT_LINKED = "That document is not linked to this item."


class LinkRefused(Exception):
    """A link this item may not have. `not_found` answers 404, anything else 409."""

    def __init__(self, reason: str, *, not_found: bool = False) -> None:
        super().__init__(reason)
        self.reason = reason
        self.not_found = not_found


def _event(
    condition: Condition,
    kind: ConditionEventKind,
    detail: dict[str, Any],
    *,
    actor_user_id: UUID | None,
) -> ConditionEvent:
    return ConditionEvent(
        company_id=condition.company_id,
        loan_file_id=condition.loan_file_id,
        condition_id=condition.id,
        kind=kind,
        actor_user_id=actor_user_id,
        detail=detail,
    )


async def _file_document(db: AsyncSession, *, condition: Condition, document_id: UUID) -> Document:
    document: Document | None = await db.scalar(
        only_active(
            # THE EXTRACTIONS ARE LOADED WITH IT: the checks read them, and a lazy load in async code
            # raises (found by the first test run).
            select(Document)
            .options(selectinload(Document.extractions))
            .where(Document.id == document_id, Document.loan_file_id == condition.loan_file_id),
            Document,
        )
    )
    if document is None:
        raise LinkRefused(NOT_ON_FILE, not_found=True)
    return document


async def _row(
    db: AsyncSession, *, item: ConditionItem, document_id: UUID
) -> ConditionEvidence | None:
    found: ConditionEvidence | None = await db.scalar(
        select(ConditionEvidence).where(
            ConditionEvidence.item_id == item.id, ConditionEvidence.document_id == document_id
        )
    )
    return found


def _read(document: Document) -> bool:
    """Whether the document has been read far enough to check: classified and extracted."""
    return document.status is DocumentStatus.COMPLETED and bool(document.document_type)


async def link_document(
    db: AsyncSession,
    *,
    condition: Condition,
    item: ConditionItem,
    document_id: UUID,
    page: int | None,
    actor_user_id: UUID | None,
    replace_document_id: UUID | None = None,
) -> ConditionEvidence:
    """Doors 3, 4 and 6: she says this document answers this item. Flushes; the caller commits."""
    from app.services.condition_evidence import AWAITING_READ, check_link, open_condition, settle

    if item.condition_id != condition.id or item.deleted_at is not None:
        raise LinkRefused("That item is not on this condition.", not_found=True)
    if not open_condition(condition):
        raise LinkRefused(CLOSED)
    document = await _file_document(db, condition=condition, document_id=document_id)
    if replace_document_id is not None and replace_document_id != document_id:
        await unlink_document(
            db,
            condition=condition,
            item=item,
            document_id=replace_document_id,
            actor_user_id=actor_user_id,
        )
    if await _row(db, item=item, document_id=document.id) is not None:
        raise LinkRefused(ALREADY_LINKED)

    # HER LINK REPLACES HER EARLIER "NO" for this pair: the stored fact goes, so a later automatic match
    # is allowed again (nothing to reconstruct).
    await db.execute(
        delete(ConditionItemUnlink).where(
            ConditionItemUnlink.item_id == item.id, ConditionItemUnlink.document_id == document.id
        )
    )
    row = ConditionEvidence(
        company_id=condition.company_id,
        loan_file_id=condition.loan_file_id,
        condition_id=condition.id,
        item_id=item.id,
        document_id=document.id,
        origin=EvidenceOrigin.MANUAL,
        linked_by_user_id=actor_user_id,
        page=page,
        checks=[dict(AWAITING_READ)],
        findings=[],
    )
    db.add(row)
    item.document_id = document.id
    item.document_page = page
    if item.status in (ConditionItemStatus.OPEN, ConditionItemStatus.REQUESTED):
        item.status = ConditionItemStatus.RECEIVED
    await db.flush()
    if _read(document):
        await check_link(db, evidence=row, item=item, condition=condition, document=document)
    db.add(
        _event(
            condition,
            ConditionEventKind.CONDITION_EVIDENCE_LINKED,
            {
                "item_key": item.key,
                "document_id": str(document.id),
                "page": page,
                "replaced": replace_document_id is not None,
            },
            actor_user_id=actor_user_id,
        )
    )
    await db.flush()
    await settle(db, condition=condition, actor_user_id=actor_user_id)
    await db.flush()
    logger.info(
        "condition_document_linked",
        condition_id=str(condition.id),
        item_id=str(item.id),
        document_id=str(document.id),
    )
    return row


async def _asked(db: AsyncSession, item: ConditionItem) -> bool:
    """Whether the item's ask went out (its draft is no longer a draft)."""
    from app.services.condition_drafts import _is_unsent

    if item.draft_id is None:
        return False
    draft = await db.get(ConditionDraft, item.draft_id)
    return draft is not None and not await _is_unsent(db, draft)


async def unlink_document(
    db: AsyncSession,
    *,
    condition: Condition,
    item: ConditionItem,
    document_id: UUID,
    actor_user_id: UUID | None,
) -> None:
    """Door 5: she says this document does not answer this item. Flushes; the caller commits.

    The evidence row is deleted, the pointer cleared, her decision stored, and the item and the condition
    recomputed: an item no longer answered goes back to open (or requested, if its ask went out), and a
    condition that was Ready to send goes back to To do, because it is no longer ready.
    """
    from app.services.condition_evidence import item_passes

    if item.condition_id != condition.id or item.deleted_at is not None:
        raise LinkRefused("That item is not on this condition.", not_found=True)
    document = await _file_document(db, condition=condition, document_id=document_id)
    row = await _row(db, item=item, document_id=document.id)
    pointer = item.document_id == document.id
    if row is None and not pointer:
        raise LinkRefused(NOT_LINKED)
    if row is not None:
        await db.delete(row)
    if pointer:
        item.document_id = None
        item.document_page = None
        if item.option is PlanOption.ALREADY_IN_FILE:
            # "Already in the file" with no document is the state LP-953 forbids; it is her task again.
            item.option = PlanOption.I_WILL_DO_IT
    exists = await db.scalar(
        select(ConditionItemUnlink.id).where(
            ConditionItemUnlink.item_id == item.id, ConditionItemUnlink.document_id == document.id
        )
    )
    if exists is None:
        db.add(
            ConditionItemUnlink(
                company_id=condition.company_id,
                loan_file_id=condition.loan_file_id,
                item_id=item.id,
                document_id=document.id,
                unlinked_by_user_id=actor_user_id,
            )
        )
    await db.flush()

    remaining = list(
        await db.scalars(select(ConditionEvidence).where(ConditionEvidence.item_id == item.id))
    )
    if item.status is not ConditionItemStatus.NOT_NEEDED:
        if remaining and item_passes(item, remaining):
            item.status = ConditionItemStatus.DONE
        elif remaining:
            item.status = ConditionItemStatus.RECEIVED
        elif item.document_id is None:
            item.status = (
                ConditionItemStatus.REQUESTED
                if await _asked(db, item)
                else ConditionItemStatus.OPEN
            )

    db.add(
        _event(
            condition,
            ConditionEventKind.CONDITION_EVIDENCE_UNLINKED,
            {"item_key": item.key, "document_id": str(document.id)},
            actor_user_id=actor_user_id,
        )
    )
    if (
        condition.prep_status is ConditionPrepStatus.READY
        and item.status is not ConditionItemStatus.DONE
    ):
        from app.services.condition_status import _event as status_event

        condition.prep_status = ConditionPrepStatus.TO_DO
        condition.prep_status_changed_at = datetime.now(UTC)
        db.add(
            status_event(
                condition,
                ConditionEventKind.CONDITION_PREP_MOVED,
                {
                    "prep_status_from": ConditionPrepStatus.READY.value,
                    "prep_status_to": ConditionPrepStatus.TO_DO.value,
                    "by": "unlink",
                },
                actor_user_id=actor_user_id,
            )
        )
    await db.flush()
    logger.info(
        "condition_document_unlinked",
        condition_id=str(condition.id),
        item_id=str(item.id),
        document_id=str(document.id),
    )


async def link_candidates(
    db: AsyncSession, *, condition: Condition, item: ConditionItem
) -> list[dict[str, Any]]:
    """LP-958 — the file's documents for the Link dialog, the ones that answer this item first.

    `matches` is THE matching rule (`condition_matching.document_answers`: type, the library's words, her
    unlinks), never a second one in the client. Current versions only, newest first within each group.
    """
    from app.documents.display_names import display_name
    from app.services.condition_matching import document_answers, match_words_for, unlinked_pairs

    documents = list(
        await db.scalars(
            only_active(
                select(Document)
                .where(
                    Document.loan_file_id == condition.loan_file_id, Document.is_current.is_(True)
                )
                .order_by(Document.created_at.desc(), Document.id),
                Document,
            )
        )
    )
    linked = set(
        await db.scalars(
            select(ConditionEvidence.document_id).where(ConditionEvidence.item_id == item.id)
        )
    )
    unlinked = await unlinked_pairs(db, loan_file_id=condition.loan_file_id)
    words = match_words_for(condition.canonical_type_id, item.key)
    out: list[dict[str, Any]] = []
    for document in documents:
        out.append(
            {
                "document_id": document.id,
                "name": document.document_name or document.original_filename,
                "type_label": display_name(document.document_type)
                if document.document_type
                else "Not read yet",
                "created_at": document.created_at,
                "matches": document_answers(
                    wanted=item.documents,
                    match_words=words,
                    document=document,
                    item_id=item.id,
                    unlinked=unlinked,
                ),
                "linked": document.id in linked or item.document_id == document.id,
                "unlinked_by_her": (item.id, document.id) in unlinked,
            }
        )
    out.sort(key=lambda row: not row["matches"])  # stable: newest first within each group
    return out
