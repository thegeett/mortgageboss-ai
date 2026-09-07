"""The accumulating document-request draft (LP-809).

ONE EMAIL, NOT FOUR. A processor requests documents on Tuesday, three more findings land on
Wednesday, and the borrower should receive a single message listing everything. So a draft holds a
SET of needs, and its body is REGENERATED from that set on every add and every remove — never
appended to, because appending cannot express a removal and would leave the borrower reading a list
that contradicts itself.

Until LP-810's drafting flag flips, the regeneration is LP-817's deterministic render, which is what
that module means by "the plain template". Nothing here calls a model.

WHAT DOES NOT GO IN THE DRAFT. LP-800 assigns every document type a responsible party, and this
draft is addressed to the borrower. A need for an appraisal, a title commitment or an employer's VOE
is real work and is not theirs to do, so it is not added. It is NOT lost: the need stays on the
needs list, which is where a processor tracks it, and LP-820 owns the paths that chase the other
parties. The distinction between "dropped" and "not in this email" is the whole reason the needs
list is the record and the draft is not.
"""

from __future__ import annotations

from dataclasses import dataclass
from string import Template
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.communications.templates import (
    RenderedTemplate,
    TemplateKey,
    render,
    render_document_block,
)
from app.documents.catalog import ResponsibleParty, get_guidance
from app.models.communication import (
    Communication,
    CommunicationDirection,
    CommunicationStatus,
)
from app.models.communication_needs_item import CommunicationNeedsItem
from app.models.helpers import only_active
from app.models.loan_file import LoanFile
from app.models.needs_item import NeedsItem
from app.verification.rule_engine.reasons import document_label

#: The template a document-request draft is rendered from, and the key its uniqueness is scoped to.
DRAFT_TEMPLATE = TemplateKey.INITIAL_DOCUMENTATION_REQUEST


@dataclass(frozen=True)
class DraftUpdate:
    """What an add actually did.

    ``skipped_not_borrower`` is returned rather than swallowed. A processor who requested five
    documents and sees three in the draft is owed an answer, and the answer is not "an error" — the
    other two are somebody else's to chase. The needs list still carries them.
    """

    draft: Communication
    added: tuple[UUID, ...] = ()
    already_present: tuple[UUID, ...] = ()
    skipped_not_borrower: tuple[UUID, ...] = ()


def _is_borrower_facing(need: NeedsItem) -> bool:
    """Whether this need is something the BORROWER can be asked for.

    An untyped need — `needs_type` is None, which LP-624 makes routine for a request generated from
    a finding's own sentence — counts as borrower-facing. The alternative reading, that an unknown
    type defaults to the processor like an uncataloged document does, is wrong here for a reason
    worth stating: those needs were created BY a processor clicking "request documents", so the
    decision to ask the borrower has already been made by a person. LP-800's default protects
    against a document nobody classified; it should not veto a request somebody made.
    """
    if need.needs_type is None:
        return True
    return get_guidance(need.needs_type).responsible_party is ResponsibleParty.BORROWER


def _document_line(need: NeedsItem) -> str:
    """One need as the borrower reads it — full guidance where the catalog has it, the title where
    it does not.

    The title is the fallback rather than the slug, and rather than nothing: a need created from a
    finding's own sentence ("One more source stating the date of birth") has no catalog type at all,
    and it is exactly the ask a borrower most needs spelled out.
    """
    if need.needs_type and get_guidance(need.needs_type).borrower_label:
        return render_document_block((need.needs_type,))
    label = need.title or (document_label(need.needs_type) if need.needs_type else "")
    return f"- {label}"


def render_draft_body(loan_file: LoanFile, needs: list[NeedsItem]) -> RenderedTemplate:
    """The rendered draft for ``needs`` — subject, body, template key and version together.

    Returns the whole :class:`RenderedTemplate` rather than a subject/body pair so the version that
    actually rendered travels with the words it produced. `phase4.md` §6 wants that pairing in the
    record, and splitting them here is where they would come apart.

    Deterministic; no model involved.

    The processor's name is left as the template's own placeholder rather than resolved here. A
    draft is not addressed to anyone until it is sent, and LP-811 owns the send — resolving a signer
    now would bake in whoever happened to click "request", who is not necessarily who sends it.
    """
    document_list = "\n\n".join(_document_line(need) for need in needs)
    return render(
        DRAFT_TEMPLATE,
        {
            "borrower_first_name": "$borrower_first_name",
            "processor_name": "$processor_name",
            "loan_reference": loan_file.display_id,
            "document_list": document_list,
            "inbox_address": loan_file.get_inbox_address(),
        },
    )


def finalise_draft_body(body: str, *, borrower_first_name: str, processor_name: str) -> str:
    """Resolve a stored draft body's deferred placeholders — THE ONLY SUPPORTED WAY TO DO IT.

    `render_draft_body` deliberately leaves ``$borrower_first_name`` and ``$processor_name`` in the
    stored body, so the send decides who signs. That makes the stored body a MIXTURE of template
    placeholders and arbitrary human text, and the second pass has to survive the human half.

    WHY ``safe_substitute`` HERE, WHEN LP-817's ``render`` REFUSES IT. There the inputs are a
    template file and a context a caller controls, so a missing variable is a bug and failing loudly
    is right. Here the input contains a NEED TITLE, and a processor writes those: "Proof of $10,000
    gift deposit" is an ordinary thing to ask a borrower for. ``$10`` is not a valid placeholder, so
    ``substitute`` raises ``ValueError: Invalid placeholder in string`` and the send dies on a
    perfectly reasonable request. Measured on exactly that title before this function existed.

    ``safe_substitute`` leaves what it cannot resolve alone, which is the correct behaviour for text
    a person wrote: a literal dollar amount stays a literal dollar amount and reaches the borrower
    as typed. The two real placeholders still resolve, and a test pins both halves.
    """
    return Template(body).safe_substitute(
        borrower_first_name=borrower_first_name, processor_name=processor_name
    )


async def get_open_draft(db: AsyncSession, *, loan_file_id: UUID) -> Communication | None:
    """The file's open document-request draft, with its needs loaded, or None."""
    return (
        await db.execute(
            only_active(
                select(Communication).where(
                    Communication.loan_file_id == loan_file_id,
                    Communication.status == CommunicationStatus.DRAFT,
                    Communication.template_key == DRAFT_TEMPLATE.value,
                ),
                Communication,
            )
        )
    ).scalar_one_or_none()


async def _needs_in_draft(db: AsyncSession, *, draft: Communication) -> list[NeedsItem]:
    """The draft's needs, oldest membership first — the order the borrower reads them in.

    By when each was ADDED rather than by title or priority: a processor who requested three things
    on Tuesday and one on Wednesday should see the new one at the bottom, not the list reshuffled.
    """
    rows = (
        await db.execute(
            select(NeedsItem)
            .join(
                CommunicationNeedsItem,
                CommunicationNeedsItem.needs_item_id == NeedsItem.id,
            )
            .where(CommunicationNeedsItem.communication_id == draft.id)
            .order_by(CommunicationNeedsItem.created_at, NeedsItem.id)
        )
    ).scalars()
    return list(rows)


async def _regenerate(db: AsyncSession, *, draft: Communication, loan_file: LoanFile) -> None:
    """Rewrite the draft's subject and body from its current membership."""
    needs = await _needs_in_draft(db, draft=draft)
    rendered = render_draft_body(loan_file, needs)
    draft.subject = rendered.subject
    draft.body = rendered.body
    # The version is stamped from what ACTUALLY rendered, not from the registry read separately.
    # Read separately, a template bumped between the render and the stamp would file the new words
    # under the old version — the one thing ADR-401's hash pin exists to make impossible.
    draft.template_version = rendered.version
    await db.flush()


async def add_needs_to_draft(
    db: AsyncSession,
    *,
    loan_file: LoanFile,
    needs: list[NeedsItem],
    actor_user_id: UUID,
) -> DraftUpdate:
    """Add ``needs`` to the file's open draft, creating it if there is none. ``flush`` only.

    Idempotent per need: adding one twice leaves one row and one line in the email. The composite
    primary key makes that structural, but it is checked here too so a second click is an ordinary
    no-op rather than an IntegrityError a caller has to catch.
    """
    borrower_facing = [need for need in needs if _is_borrower_facing(need)]
    skipped = tuple(need.id for need in needs if not _is_borrower_facing(need))

    draft = await get_open_draft(db, loan_file_id=loan_file.id)
    if draft is None:
        draft = Communication(
            loan_file_id=loan_file.id,
            direction=CommunicationDirection.OUTBOUND,
            status=CommunicationStatus.DRAFT,
            template_key=DRAFT_TEMPLATE.value,
            # Stamped by `_regenerate` below, from the render itself.
            template_version=None,
            initiated_by_user_id=actor_user_id,
        )
        db.add(draft)
        await db.flush()

    existing = set(
        (
            await db.execute(
                select(CommunicationNeedsItem.needs_item_id).where(
                    CommunicationNeedsItem.communication_id == draft.id
                )
            )
        )
        .scalars()
        .all()
    )
    added: list[UUID] = []
    already: list[UUID] = []
    for need in borrower_facing:
        if need.id in existing:
            already.append(need.id)
            continue
        db.add(CommunicationNeedsItem(communication_id=draft.id, needs_item_id=need.id))
        existing.add(need.id)
        added.append(need.id)
    await db.flush()

    await _regenerate(db, draft=draft, loan_file=loan_file)
    return DraftUpdate(
        draft=draft,
        added=tuple(added),
        already_present=tuple(already),
        skipped_not_borrower=skipped,
    )


async def remove_need_from_draft(
    db: AsyncSession, *, loan_file: LoanFile, needs_item_id: UUID
) -> Communication | None:
    """Drop a need from the open draft and regenerate. Returns the draft, or None if there is none.

    An emptied draft is KEPT rather than deleted. A processor who removes the last line is editing,
    not abandoning — deleting the row would discard whatever else they had changed, and an empty
    draft is visibly empty, which a missing one is not.
    """
    draft = await get_open_draft(db, loan_file_id=loan_file.id)
    if draft is None:
        return None
    row = await db.get(CommunicationNeedsItem, (draft.id, needs_item_id))
    if row is None:
        return draft
    await db.delete(row)
    await db.flush()
    await _regenerate(db, draft=draft, loan_file=loan_file)
    return draft
