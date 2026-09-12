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

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.email_draft import (
    DraftComposition,
    DraftFacts,
    compose,
    rejection_reason,
)
from app.communications.templates import (
    Framing,
    RenderedTemplate,
    TemplateKey,
    plain_framing,
    render,
    render_document_block,
    secure_upload_block,
)
from app.core.config import settings
from app.core.logging import get_logger
from app.documents.catalog import ResponsibleParty, get_guidance
from app.models.borrower import Borrower
from app.models.communication import (
    Communication,
    CommunicationDirection,
    CommunicationStatus,
)
from app.models.communication_needs_item import CommunicationNeedsItem
from app.models.email_draft_prose import EmailDraftProse
from app.models.helpers import only_active
from app.models.loan_file import LoanFile
from app.models.needs_item import NeedsItem, NeedsItemDisposition, NeedsItemOrigin
from app.models.upload_link import UploadLink, hash_token
from app.models.user import User
from app.services.needs_items import create_needs_item
from app.services.party_requests import (
    PARTY_ROLE,
    party_addresses,
    party_for,
    template_key_for,
)
from app.services.upload_links import mint_upload_link, revoke_link
from app.verification.rule_engine.reasons import document_label

logger = get_logger(__name__)

#: The template a document-request draft is rendered from, and the key its uniqueness is scoped to.
DRAFT_TEMPLATE = TemplateKey.INITIAL_DOCUMENTATION_REQUEST


@dataclass(frozen=True)
class PartyDraft:
    """One party's share of a request (LP-841)."""

    party: ResponsibleParty
    #: None when this party is the PROCESSOR — nobody to email — or when the request added nothing
    #: new and no draft was already open for them.
    draft: Communication | None
    added: tuple[UUID, ...] = ()
    already_present: tuple[UUID, ...] = ()


@dataclass(frozen=True)
class DraftUpdate:
    """What an add actually did, per party.

    ONE REQUEST CAN TOUCH SEVERAL DRAFTS, which is why this is a collection. CR-6 wants a credit
    report and a closing disclosure — both the lender's; IN-8 mixes a pay stub with a VOE, which is
    the borrower's and the employer's. A single `draft` field could only ever describe one of them,
    and what it described before this ticket was the borrower's, with the rest discarded.

    `skipped_not_borrower` IS GONE, and its absence is the ticket. Nothing is skipped any more —
    every need reaches whoever holds it, so "we did not email the borrower about this" stopped being
    the interesting fact and "here is the draft to the lender" took its place.
    """

    parties: tuple[PartyDraft, ...] = ()

    @property
    def borrower(self) -> PartyDraft | None:
        """This request's effect on the BORROWER's draft, if it had one.

        A convenience for the callers that legitimately care about one party — the badge, the
        preview — and never a way to pretend the others did not happen.
        """
        return next((p for p in self.parties if p.party is ResponsibleParty.BORROWER), None)

    @property
    def draft(self) -> Communication | None:
        """The borrower's draft, for callers that predate the split."""
        borrower = self.borrower
        return borrower.draft if borrower else None

    @property
    def added(self) -> tuple[UUID, ...]:
        """Everything this request put into a draft, across every party."""
        return tuple(need_id for party in self.parties for need_id in party.added)

    @property
    def already_present(self) -> tuple[UUID, ...]:
        return tuple(need_id for party in self.parties for need_id in party.already_present)


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
        line = render_document_block((need.needs_type,))
    else:
        label = need.title or (document_label(need.needs_type) if need.needs_type else "")
        line = f"- {label}"

    # LP-839 — THE PROCESSOR'S NOTE, WHICH REACHED NOBODY.
    #
    # The request form asks "Anything to add to the request?", stores the answer in
    # `NeedsItem.description`, and nothing read it: this function rendered the catalog's guidance or
    # the title and stopped. A processor typing "the March one specifically, not February" was
    # writing to a column.
    #
    # ATTACHED TO ITS OWN DOCUMENT rather than appended to the email, because that is what makes it
    # survive: the body is rewritten from the needs on every add and remove, so a note living
    # anywhere but the need it belongs to would be wiped by the next request — LP-834's problem, with
    # a cheaper answer available because a note already has a row to live on.
    # LP-842 — WHAT IT HAS TO ESTABLISH, which the catalog cannot say. The catalog knows where to
    # get a homeowner's policy; only the rule that fired knows this file needs one showing the
    # dwelling settled on a replacement-cost basis. Without it the recipient sends another
    # declarations page that does not say so — because the first one did not either, which IS the
    # finding — and the file is a round trip older and no closer.
    #
    # ABOVE the processor's note, because they are answering different questions and the order is
    # the order they are read in: what this document must show, then anything the processor wants to
    # add about this particular one.
    ask = (need.outbound_ask or "").strip()
    if ask:
        line = f"{line}\n  {ask}"
    note = (need.description or "").strip()
    if note:
        line = f"{line}\n  {note}"
    return line


def _borrower_label(need: NeedsItem) -> str:
    """What this need is CALLED to a borrower — never its slug, never the raw title if a label exists."""
    if need.needs_type and (label := get_guidance(need.needs_type).borrower_label):
        return label
    return need.title or (document_label(need.needs_type) if need.needs_type else "")


def _identification_block(loan_file: LoanFile, *, borrower_name: str, property_address: str) -> str:
    """How a third party finds this loan in THEIR system (LP-843).

    `display_id` is OURS. A lender, a title company and an employer each file by something else —
    the borrower's name, the property address, their own loan number — and an email that offers only
    "LF-XMB2" names nothing they can search. The reference is still included, because it is what they
    quote back to us.

    OMITS WHAT THE FILE DOES NOT HAVE rather than printing an empty label. "Property:" with nothing
    after it tells a reader the address is missing from our system, which is true and useless; the
    line simply does not appear. A purchase file often has no address for weeks (`Property.address_line`
    is nullable precisely for that), so this is the ordinary case rather than the degraded one.

    NO LOAN NUMBER. A lender's own loan number is not a field this system holds, and inventing a
    label for it would put an empty promise in every email.
    """
    lines = []
    if borrower_name:
        lines.append(f"Borrower: {borrower_name}")
    if property_address:
        lines.append(f"Property: {property_address}")
    lines.append(f"Our reference: {loan_file.display_id}")
    return "\n".join(lines)


def template_for(party: ResponsibleParty) -> TemplateKey:
    """Which template renders a draft to this party (LP-843).

    TWO NON-BORROWER VOICES, not six. Lender, title, accountant, agent and insurer are all third
    parties being asked for a document they already hold, and the same professional words serve all
    of them — what differs is the document list. The employer is its own, because a VOE is a form to
    complete rather than a document to retrieve, and an incomplete one costs another round trip.

    THIS IS NOT THE BUCKET. `Communication.party` decides which tab a draft appears under, and five
    parties sharing one template still get five tabs. The two were the same field until this ticket,
    which is exactly why every party draft was rendered from the borrower's template.
    """
    if party is ResponsibleParty.BORROWER:
        return DRAFT_TEMPLATE
    if party is ResponsibleParty.EMPLOYER:
        return TemplateKey.DOCUMENT_REQUEST_EMPLOYER
    return TemplateKey.DOCUMENT_REQUEST_THIRD_PARTY


def render_draft_body(
    loan_file: LoanFile,
    needs: list[NeedsItem],
    *,
    party: ResponsibleParty = ResponsibleParty.BORROWER,
    borrower_name: str = "",
    property_address: str = "",
    framing: Framing | None = None,
    upload_link_url: str | None = None,
) -> RenderedTemplate:
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
    key = template_for(party)
    if key is not DRAFT_TEMPLATE:
        # LP-843 — NO `$inbox_address` AND NO BORROWER FRAMING. The third-party and employer
        # templates declare neither, so supplying them would fail the declared-variables check
        # rather than leak quietly, which is the right way round.
        return render(
            key,
            {
                "processor_name": "$processor_name",
                "loan_reference": loan_file.display_id,
                "borrower_name": borrower_name or "the borrower",
                "loan_identification": _identification_block(
                    loan_file,
                    borrower_name=borrower_name,
                    property_address=property_address,
                ),
                "document_list": document_list,
                "secure_upload_block": secure_upload_block(upload_link_url),
            },
        )
    # LP-810 — the composed framing where there is one, the file's own plain sentences otherwise.
    # `plain_framing()` carries v1's exact wording, so a reader with the flag off sees what v1 sent.
    words = framing or plain_framing()
    return render(
        DRAFT_TEMPLATE,
        {
            "borrower_first_name": "$borrower_first_name",
            "processor_name": "$processor_name",
            "loan_reference": loan_file.display_id,
            "document_list": document_list,
            "inbox_address": loan_file.get_inbox_address(),
            "opening": words.opening,
            "bridge": words.bridge,
            "closing": words.closing,
            # LP-834 — the caution plus a live link where the draft has one, and LP-824's offer to
            # send one where it does not. Passed in rather than looked up: the plaintext token is
            # not in the database to look up.
            "secure_upload_block": secure_upload_block(upload_link_url),
        },
    )


#: What the greeting says when the file has no borrower name to put in it.
#:
#: A FALLBACK, NOT A DEFAULT. `$borrower_first_name` reaching a borrower is the defect this whole
#: ticket is about, and "Hello there," is ordinary English where "Hello ," is not. It should be rare:
#: a file with no borrower has nobody to email, and a borrower with no first name cannot be created
#: (the column is NOT NULL). The case that reaches this is a draft on a file whose borrowers were
#: all soft-deleted.
BORROWER_NAME_FALLBACK = "there"


async def primary_borrower(db: AsyncSession, *, loan_file_id: UUID) -> Borrower | None:
    """The borrower a draft is addressed to.

    `is_primary` FIRST, THEN POSITION. The model says exactly one borrower is flagged primary and
    `services/borrowers.py` maintains that, but a file whose primary was soft-deleted has none — and
    the answer there should be the next borrower on the file, not nobody. `schemas/loan_file.py`'s
    `_primary_borrower_name` returns None in that case, which is right for a display name and wrong
    for choosing who to write to.

    ORDERED, NOT `.first()` OVER AN UNORDERED SET. Two borrowers must give the same answer on two
    requests, because the answer decides which mailbox a document request goes to.
    """
    return (
        (
            await db.execute(
                only_active(
                    select(Borrower).where(Borrower.loan_file_id == loan_file_id),
                    Borrower,
                ).order_by(
                    Borrower.is_primary.desc(),
                    Borrower.borrower_position,
                    Borrower.id,
                )
            )
        )
        .scalars()
        .first()
    )


async def greeting_name_for(db: AsyncSession, *, draft: Communication, loan_file: LoanFile) -> str:
    """Whose first name goes in this draft's greeting — decided from the DRAFT, not from the file.

    LP-823 REVIEW — `$borrower_first_name` IS NOT ALWAYS THE BORROWER. `render_draft_body` is shared:
    `party_requests.build_party_draft` renders the same template for the title company, the agent,
    the lender, the CPA, the insurer and the employer, each under its own `template_key`. Resolving
    the placeholder from `primary_borrower` unconditionally put the BORROWER's first name in a
    message addressed to a third party — measured end to end, a title request to `t@title.example`
    went out reading "Hello Akash,".

    That is strictly worse than the placeholder it replaced. `$borrower_first_name` reaching a
    reader is visibly broken and gets noticed; a real person's name in the wrong message is not.
    LP-820's own docstring says the greeting "is generic in the template rather than addressed to a
    borrower" — true only while nothing resolved it, which is the assumption LP-823 removed.

    So: the borrower's name for the BORROWER's draft, and the generic fallback for every other one.
    A party greeting that names the party is a better email and belongs to LP-820 — it owns the
    template's voice, and the rest of that body still says "your loan file" to a title company.
    """
    if draft.template_key != DRAFT_TEMPLATE.value:
        return BORROWER_NAME_FALLBACK
    borrower = await primary_borrower(db, loan_file_id=loan_file.id)
    return borrower.first_name if borrower else BORROWER_NAME_FALLBACK


async def draft_for_reading(
    db: AsyncSession, *, draft: Communication, loan_file: LoanFile, reader: User
) -> tuple[str, str | None]:
    """The draft's body with its placeholders resolved, and the borrower's email.

    WHY THIS EXISTS. `render_draft_body` stores `$borrower_first_name` and `$processor_name`
    deliberately, so the send decides who signs. `finalise_draft_body` resolves them — and until
    this function, NOTHING CALLED IT. Not the send, not the endpoint, not the panel. Since the
    message leaves through "Copy message" or "Open in mail client", both of which take what the
    screen shows, every document request went to the borrower reading `Hello $borrower_first_name,`.

    THE READER IS THE PROSPECTIVE SIGNER, and that is the whole reconciliation. Whoever sends should
    sign, which is why the stored body keeps the placeholder; whoever is LOOKING at it should see a
    name, because a processor cannot tell a placeholder that will be filled from one that will not.
    Resolving here rather than in `render_draft_body` keeps both true: the stored draft is still
    unaddressed, and a colleague who opens the same draft sees their own name.
    """
    body = finalise_draft_body(
        draft.body or "",
        borrower_first_name=await greeting_name_for(db, draft=draft, loan_file=loan_file),
        processor_name=reader.full_name,
    )
    borrower = await primary_borrower(db, loan_file_id=loan_file.id)
    return body, (borrower.email if borrower else None)


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


#: The party whose documents nobody can be emailed about (LP-841).
#:
#: LP-800 gives 24 of 166 types to the PROCESSOR — the condo questionnaire, the HOA certification, a
#: verbal VOE, the 1003. "We order it ourselves" is not a message to anybody, so these never become a
#: draft. They are real work and stay on the needs list, which is where a processor tracks them.
NO_RECIPIENT = ResponsibleParty.PROCESSOR


def draft_template_key(party: ResponsibleParty) -> str:
    """The template key stored on a draft to this party — WHAT RENDERED IT (LP-843).

    LP-841 stored `document_request_<party>` here so the communication page could bucket by it. That
    made the key mean two things, and LP-843 separated them: the bucket is `Communication.party` now,
    and this is the template again.

    IT HAD TO CHANGE, and the reason is ADR-401 rather than tidiness. A lender draft stored
    `template_key="document_request_lender"` with `template_version="v1"` — and no such template has
    ever existed, so the pair named nothing. The pin's entire purpose is that a stored key and
    version resolve to the exact words that were sent; a row that resolves to nothing cannot be
    audited and cannot be told apart from one that resolves to something.

    The borrower still keeps `initial_documentation_request`, which is the genuine historical pin:
    that key is on every message this product has ever sent.
    """
    return template_for(party).value


def party_for_draft_template(template_key: str | None) -> ResponsibleParty | None:
    """The inverse of :func:`draft_template_key` — which party's bucket a message belongs in.

    THE BUCKETS ARE A SERVER CONCERN, for the reason the timeline filter already is: a tab computed
    from a template key on the client is a second definition of "the lender's messages" that nothing
    forces to agree with the one the draft was filed under. When they drift, a draft exists and its
    tab is empty.

    Returns None for a template this function does not recognise — a notification, a status update,
    anything that is not a document request. Those belong in no party bucket, and guessing one would
    put a message in front of somebody it was never about.
    """
    if template_key is None:
        return None
    if template_key == DRAFT_TEMPLATE.value:
        return ResponsibleParty.BORROWER
    # LP-843 — THE HISTORICAL KEYS ONLY. `document_request_<party>` is what LP-841 stored, and a
    # draft written before that ticket's column existed still carries one; that is the whole reason
    # this function survives.
    #
    # IT CANNOT ANSWER FOR A DRAFT WRITTEN SINCE. Five parties share `document_request_third_party`,
    # so a lender draft and a title draft are now indistinguishable by key — which is exactly why the
    # audience is stored. Returning None here is not a gap, it is the honest answer: a caller that
    # needs the party reads `Communication.party`, and one that falls back to this for a modern row
    # is asking a question the key genuinely no longer carries.
    for party in ResponsibleParty:
        if template_key == template_key_for(party):
            return party
    return None


def _legacy_draft_keys(party: ResponsibleParty) -> tuple[str, ...]:
    """The `template_key` values an LP-841-era draft to this party could carry.

    LP-843 REVIEW — THE COMPATIBILITY ARM WAS MATCHING THE NEW KEY. It compared `template_key` against
    `draft_template_key(party)`, which is this ticket's value — so for a lender it looked for
    `document_request_third_party` among rows that carry `document_request_lender`. Measured across all
    eight parties: only `employer` matched, and only because its new key happens to equal its old one.
    Six of eight covered nothing.

    That is the one case the arm exists for: a draft created by the OLD code AFTER the migration ran,
    which has `party IS NULL` and an LP-841 key. Invisible to `open_drafts`, so the next request mints
    a second draft and the processor's open one forks — the failure this arm was written to prevent.
    Rows that predate the migration are fine either way; the backfill sets `party` and arm one finds
    them.

    `template_key_for` is LP-841's own function, so the set is derived from the thing that wrote the
    rows rather than restated. The borrower carries both: `initial_documentation_request` is the
    genuine historical pin on every message this product has sent, and LP-841's own per-party name is
    what its backfill CASE maps alongside it.
    """
    from app.services.party_requests import template_key_for

    keys = {template_key_for(party)}
    if party is ResponsibleParty.BORROWER:
        keys.add(draft_template_key(party))
    return tuple(sorted(keys))


def _open_drafts_stmt(loan_file_id: UUID, party: ResponsibleParty):  # type: ignore[no-untyped-def]
    """This party's unsent drafts on the file, newest first."""
    return only_active(
        select(Communication).where(
            Communication.loan_file_id == loan_file_id,
            Communication.status == CommunicationStatus.DRAFT,
            # LP-843 — MATCHES ON THE AUDIENCE, or on the key for a draft written before the
            # column existed. Filtering on the key alone would strand every draft open across the
            # deploy in a bucket nothing looks in; filtering on the column alone would find none of
            # them. The backfill sets `party` for existing rows, so the second arm covers only a
            # draft created between the migration and the deploy of this code.
            or_(
                Communication.party == party.value,
                and_(
                    Communication.party.is_(None),
                    Communication.template_key.in_(_legacy_draft_keys(party)),
                ),
            ),
        ),
        Communication,
    ).order_by(Communication.created_at.desc(), Communication.id.desc())


async def open_drafts(
    db: AsyncSession,
    *,
    loan_file_id: UUID,
    party: ResponsibleParty = ResponsibleParty.BORROWER,
) -> list[Communication]:
    """Every unsent document-request draft on the file, newest first (LP-832).

    ORDERED, AND THE TIEBREAK MATTERS. Two drafts created in the same transaction share a
    `created_at` to microsecond precision often enough to see, and "the newest" has to be one row
    rather than whichever the planner returns.
    """
    return list((await db.execute(_open_drafts_stmt(loan_file_id, party))).scalars().all())


async def get_open_draft(
    db: AsyncSession,
    *,
    loan_file_id: UUID,
    party: ResponsibleParty = ResponsibleParty.BORROWER,
) -> Communication | None:
    """The file's NEWEST unsent document-request draft, or None.

    LP-832 — THIS USED TO BE `scalar_one_or_none()`, AND THAT DID NOT MEAN "the one draft". It meant
    *raise* if there were two, which the `uq_communications_open_draft` partial unique index made
    unreachable — so four callers were written against a guarantee the database was holding, not one
    they checked.

    That index is gone: a request now creates a NEW draft each time, carrying everything requested
    since the last send. So this returns the newest rather than asserting there is only one, and
    every caller that wanted "the draft a processor is working on" still gets it.

    A caller that wants ALL of them — the drafts list, the count in the header — uses
    :func:`open_drafts`. Nothing should reach for this one to count with.
    """
    return (await db.execute(_open_drafts_stmt(loan_file_id, party).limit(1))).scalars().first()


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


async def _cached_prose(db: AsyncSession, key: str) -> str | None:
    """A previously composed framing for these exact facts, or None."""
    body = await db.scalar(select(EmailDraftProse.body).where(EmailDraftProse.fact_hash == key))
    return str(body) if body is not None else None


async def _store_prose(db: AsyncSession, *, key: str, body: str) -> None:
    """Cache a composition. Callers store only what `rejection_reason` has already passed."""
    if await db.get(EmailDraftProse, key) is None:
        db.add(EmailDraftProse(fact_hash=key, body=body, template_key=DRAFT_TEMPLATE.value))
        await db.flush()


def _draft_facts(loan_file: LoanFile, needs: list[NeedsItem]) -> DraftFacts:
    """The narrow bundle the model may draw on — LP-810's central constraint.

    The borrower's first name is not resolved here and is left as the template's own placeholder, so
    the facts (and therefore the cache key) do not vary per borrower for an otherwise identical
    request. That is deliberate: it makes the cache actually hit, and the model has no legitimate use
    for the name it is not already getting from the greeting line it does not write.
    """
    return DraftFacts(
        borrower_first_name="the borrower",
        loan_reference=loan_file.display_id,
        requested_labels=tuple(_borrower_label(need) for need in needs),
        # LP-839 — the processor's notes, which the borrower now reads. Included so the cache key
        # moves when one is added: without it `_cached_prose` hits and the framing stays written for
        # a request that has changed.
        requested_notes=tuple(note for need in needs if (note := (need.description or "").strip())),
    )


async def _cached_framing(
    db: AsyncSession, *, loan_file: LoanFile, needs: list[NeedsItem]
) -> Framing | None:
    """The model-written framing for this draft IF ONE IS ALREADY STORED. Never calls the model.

    None means "use the plain template", which is a complete email rather than a degraded one.

    LP-809 REVIEW — THIS RUNS INSIDE A PROCESSOR'S CLICK, WHICH IS WHY IT CANNOT COMPOSE. `_regenerate`
    is reached from `add_needs_to_draft`, and both request-docs routes call that synchronously inside
    the HTTP request. A `compose()` here put an Anthropic round-trip in the button's response, against
    CLAUDE.md's "long work runs on Celery, not in the request" — and it missed the cache every time,
    because the key is built from `requested_labels` and every add changes them. The composition now
    happens in `tasks.email_draft.compose_draft_prose`, enqueued after the commit; this reads what
    that stored. Until it has, the draft carries the plain template, which is a whole email.
    """
    if not settings.email_draft_enabled or not needs:
        return None
    facts = _draft_facts(loan_file, needs)
    cached = await _cached_prose(db, facts.cache_key())
    if cached is None:
        return None
    # LP-601 — THE CACHE IS FILTERED THROUGH THE SAME VERDICT. `compose` runs only on a miss, so a
    # composition stored before a guard existed would be served forever and the guard would never
    # see it. Re-checking on the way OUT means a guard added later heals stored prose next run.
    stored = _framing_from_body(cached)
    if stored is not None and rejection_reason(facts, stored) is None:
        return Framing(stored.opening, stored.bridge, stored.closing)
    return None


async def compose_open_draft_prose(
    db: AsyncSession, *, loan_file: LoanFile, draft: Communication | None = None
) -> bool:
    """Compose the framing for a draft and re-render it. Returns whether it changed.

    The OFF-REQUEST half of `_cached_framing` when the task calls it: a miss composes, stores, and
    re-renders the draft body from the now-warm cache; a hit re-renders nothing and returns False,
    which is what makes a duplicate enqueue harmless.

    LP-833 REVIEW — `draft` IS PASSED WHEN THE CALLER HAS ONE. `compose_request` had just created a
    draft and then asked for "this file's newest open draft", which is the same row today only
    because nothing runs between the two statements. That is a property of the current code rather
    than of this function, and it is the shape LP-832's review already found once in
    `remove_need_from_draft`: a function resolving "the draft" while its caller is holding the one it
    means. The row lock covers a concurrent request; it does not cover a future caller in the same
    transaction. Passing it removes the question instead of documenting it.

    `tasks.email_draft` keeps the lookup — it has a loan file id and no draft, which is the case the
    default is for.
    """
    if not settings.email_draft_enabled:
        return False
    if draft is None:
        draft = await get_open_draft(db, loan_file_id=loan_file.id)
    if draft is None:
        return False
    needs = await _needs_in_draft(db, draft=draft)
    if not needs:
        return False
    facts = _draft_facts(loan_file, needs)
    key = facts.cache_key()
    if await _cached_prose(db, key) is not None:
        return False
    composition = await compose(facts)
    if composition is None:
        return False
    await _store_prose(db, key=key, body=composition.message)
    await _regenerate(db, draft=draft, loan_file=loan_file)
    return True


def _framing_from_body(body: str) -> DraftComposition | None:
    """Rebuild a composition from its cached three-paragraph form, for re-checking."""
    parts = [part.strip() for part in body.split("\n\n") if part.strip()]
    if len(parts) != 3:
        return None
    return DraftComposition(parts[0], parts[1], parts[2])


def _party_of_draft(draft: Communication) -> ResponsibleParty:
    """The audience of a stored draft.

    READS THE COLUMN, falls back to the template key. `Communication.party` is LP-843's and every
    draft written since carries it; a draft composed before the migration has its party recoverable
    from the key LP-841 filed it under, which is what the backfill used. The fallback is not
    defensive padding — a draft open across the deploy is the ordinary case.
    """
    if draft.party:
        try:
            return ResponsibleParty(draft.party)
        except ValueError:
            pass
    return party_for_draft_template(draft.template_key) or ResponsibleParty.BORROWER


async def _identification(db: AsyncSession, *, loan_file: LoanFile) -> tuple[str, str]:
    """`(borrower_name, property_address)` for a third-party email's identification block.

    EMPTY STRINGS WHERE THE FILE IS SILENT, never a placeholder or an invented value. The block
    omits a line it has nothing for; see `_identification_block`.
    """
    borrower = await primary_borrower(db, loan_file_id=loan_file.id)
    name = borrower.full_name if borrower else ""

    from app.models.property import Property

    row = (
        await db.execute(
            only_active(select(Property).where(Property.loan_file_id == loan_file.id), Property)
        )
    ).scalar_one_or_none()
    parts = [
        (row.address_line if row else None),
        (row.city if row else None),
        " ".join(
            p for p in [(row.state if row else None), (row.postal_code if row else None)] if p
        ),
    ]
    address = ", ".join(p.strip() for p in parts if p and p.strip())
    return name, address


async def _regenerate(db: AsyncSession, *, draft: Communication, loan_file: LoanFile) -> None:
    """Rewrite the draft's subject and body from its current membership."""
    needs = await _needs_in_draft(db, draft=draft)
    framing = await _cached_framing(db, loan_file=loan_file, needs=needs)
    # LP-834 — REGENERATION IS LOSSLESS BECAUSE THE DRAFT REMEMBERS. The body is rewritten from the
    # template on every add and remove; a link that lived only in the prose would be wiped the first
    # time a processor requested one more document, and could not be rebuilt because the token is
    # hashed in `upload_links`.
    party = _party_of_draft(draft)
    identity = (
        await _identification(db, loan_file=loan_file)
        if party is not ResponsibleParty.BORROWER
        else ("", "")
    )
    rendered = render_draft_body(
        loan_file,
        needs,
        party=party,
        borrower_name=identity[0],
        property_address=identity[1],
        framing=framing,
        upload_link_url=draft.upload_link_url,
    )
    draft.subject = rendered.subject
    draft.body = rendered.body
    # The version is stamped from what ACTUALLY rendered, not from the registry read separately.
    # Read separately, a template bumped between the render and the stamp would file the new words
    # under the old version — the one thing ADR-401's hash pin exists to make impossible.
    draft.template_version = rendered.version
    await db.flush()


async def _outstanding_needs(
    db: AsyncSession, *, loan_file_id: UUID, party: ResponsibleParty
) -> list[NeedsItem]:
    """Every need carried by an unsent draft on this file, oldest membership first (LP-832).

    "EVERYTHING REQUESTED SINCE THE LAST SEND", expressed as the thing that is actually true rather
    than as a time comparison. A send closes its draft — the row leaves `DRAFT` — so the needs it
    carried drop out of this set by the same statement that sent them. There is no clock to read and
    no window to get wrong.

    A UNION ACROSS THE OPEN DRAFTS, deliberately. While each draft is a superset of the previous one
    the newest alone would answer identically; they diverge the moment a processor deletes the newest,
    which this model invites them to do. Deleting a draft must not quietly drop its documents out of
    the next request.

    DISTINCT, ORDERED BY WHEN EACH JOINED ITS FIRST DRAFT. Two drafts carry the same need twice over
    and a borrower must read it once.
    """
    rows = (
        await db.execute(
            select(NeedsItem, func.min(CommunicationNeedsItem.created_at).label("first_added"))
            .join(
                CommunicationNeedsItem,
                CommunicationNeedsItem.needs_item_id == NeedsItem.id,
            )
            .join(
                Communication,
                Communication.id == CommunicationNeedsItem.communication_id,
            )
            .where(
                Communication.loan_file_id == loan_file_id,
                Communication.status == CommunicationStatus.DRAFT,
                Communication.template_key == draft_template_key(party),
                Communication.deleted_at.is_(None),
                NeedsItem.deleted_at.is_(None),
            )
            .group_by(NeedsItem.id)
            .order_by("first_added", NeedsItem.id)
        )
    ).all()
    return [row[0] for row in rows]


async def add_needs_to_draft(
    db: AsyncSession,
    *,
    loan_file: LoanFile,
    needs: list[NeedsItem],
    actor_user_id: UUID,
) -> DraftUpdate:
    """Create a NEW draft carrying everything outstanding, plus ``needs``. ``flush`` only.

    LP-832 — A REQUEST MAKES A DRAFT; IT DOES NOT GROW ONE. Confirmed directly with the user, because
    the sentence admitted both readings and the other one is what this function used to do:

    | request Bank statements | **Draft 1**: Bank statements |
    | request Pay stub        | **Draft 2**: Bank statements, Pay stub — Draft 1 still in the list |
    | mark Draft 2 sent       | — |
    | request W-2             | **Draft 3**: W-2 only, because the set resets at a send |

    So a draft carries everything requested SINCE THE LAST SEND, and the older ones stay for the
    processor to send, delete or ignore. Nothing supersedes automatically: a draft disappearing
    because the system decided it was stale is worse than a list that needs tidying.

    THE OUTSTANDING SET IS A UNION OVER THE OPEN DRAFTS, not a read of the newest one. Both give the
    same answer while each draft is a superset of the last — and they stop agreeing the moment a
    processor deletes the newest, which is an action this model invites. A union keeps a deleted
    draft from taking its documents out of the next one.

    NOTHING NEW MEANS NO DRAFT. A second click on the same finding adds nothing, and minting a
    duplicate draft with identical contents would put a second identical email in the list for a
    request that did not happen. `added` is empty and the newest existing draft is returned, so
    LP-826's outcome still reports honestly that the draft took nothing.

    SERIALIZED ON THE FILE ROW, which is what `uq_communications_open_draft` was really buying. That
    index is gone — it is the guarantee this ticket removes — but its stated purpose was not "one
    draft": it was that two near-simultaneous requests must not each create a draft "with no basis
    for choosing between them". Under this model two drafts are correct; two drafts each missing the
    OTHER's new document is not, and that is what a concurrent pair would produce, because both would
    compute the outstanding set from the same pre-state. A row lock on the loan file makes the second
    request see the first one's draft.
    """
    # LP-841 — EVERY NEED GOES TO WHOEVER HOLDS IT. This kept the borrower's and discarded the rest:
    # 53 of 166 document types belong to somebody else, so a request for a credit report, an
    # appraisal or a title commitment produced a needs item and no message to anybody.
    #
    # `party_for` is the routing rule and it already existed — LP-820 wrote it, and it is the same
    # rule `_is_borrower_facing` was applying to one party. Grouping by it rather than filtering on
    # it is the whole change.
    by_party: dict[ResponsibleParty, list[NeedsItem]] = {}
    for need in needs:
        by_party.setdefault(party_for(need), []).append(need)

    # THE LOCK, before anything is read. Held to the end of the transaction, so a concurrent request
    # on the same file waits here and then computes the outstanding set including this one's drafts.
    await db.execute(select(LoanFile.id).where(LoanFile.id == loan_file.id).with_for_update())

    results: list[PartyDraft] = []
    for party, party_needs in by_party.items():
        if party is NO_RECIPIENT:
            # NOBODY TO EMAIL. "We order it ourselves" is not a message, so these never become a
            # draft — they are real work and the needs list is where a processor tracks them.
            results.append(PartyDraft(party=party, draft=None, added=(), already_present=()))
            continue
        results.append(
            await _add_to_party_draft(
                db,
                loan_file=loan_file,
                party=party,
                needs=party_needs,
                actor_user_id=actor_user_id,
            )
        )
    return DraftUpdate(parties=tuple(results))


async def _party_address(
    db: AsyncSession, *, loan_file: LoanFile, party: ResponsibleParty
) -> str | None:
    """Where this party's draft is addressed, or None when nobody has said (LP-841).

    NONE IS AN ORDINARY ANSWER, NOT A REFUSAL. `build_party_draft` raised on a missing address —
    "a draft addressed to nobody is a message that will never be sent" — and the processor's answer
    is the opposite: keep it empty. LP-820 measured that 13 of 166 document types have no address
    anywhere in the schema, so refusing means those documents never produce a message at all, and
    the message is the part a processor wants. An address can be typed into the modal before
    sending; a message nobody wrote cannot be recovered.

    The borrower is resolved through their own row rather than the participants table, because that
    is where their address lives and `draft_for_reading` already suggests it.
    """
    if party is ResponsibleParty.BORROWER:
        borrower = await primary_borrower(db, loan_file_id=loan_file.id)
        return borrower.email if borrower else None
    addresses = await party_addresses(db, loan_file=loan_file)
    found = addresses.get(PARTY_ROLE[party]) if party in PARTY_ROLE else None
    return found[0] if found else None


async def _add_to_party_draft(
    db: AsyncSession,
    *,
    loan_file: LoanFile,
    party: ResponsibleParty,
    needs: list[NeedsItem],
    actor_user_id: UUID,
) -> PartyDraft:
    """One party's share of a request, in one new draft (LP-841).

    THE SAME RULE PER BUCKET, which is what the processor asked for: an open draft for this party
    means the next request creates a NEW one carrying that party's outstanding documents plus
    whatever is new; a draft that has been marked sent takes its documents out of the set, so the
    next request starts fresh.

    NO ADDRESS IS NOT A REFUSAL. `build_party_draft` raised when a party had none — "a draft
    addressed to nobody is a message that will never be sent" — and the processor's answer is the
    opposite: keep it empty, because the message is the part they want. A recipient can be typed in
    the modal; a message that was never written cannot be recovered.
    """
    outstanding = await _outstanding_needs(db, loan_file_id=loan_file.id, party=party)
    carried = {need.id for need in outstanding}
    fresh = [need for need in needs if need.id not in carried]
    already = tuple(need.id for need in needs if need.id in carried)

    if not fresh:
        # NOTHING NEW MEANS NO DRAFT. A second click on the same finding adds nothing, and minting a
        # duplicate with identical contents would put a second identical email in the list for a
        # request that did not happen.
        return PartyDraft(
            party=party,
            draft=await get_open_draft(db, loan_file_id=loan_file.id, party=party),
            added=(),
            already_present=already,
        )

    draft = Communication(
        loan_file_id=loan_file.id,
        direction=CommunicationDirection.OUTBOUND,
        status=CommunicationStatus.DRAFT,
        template_key=draft_template_key(party),
        # LP-843 — THE AUDIENCE, stored rather than inferred from the key. The two were one field
        # until this ticket, and that is why five parties could not share a template: the key had to
        # stay per-party for the tabs, so the words had to be per-party too, or borrower's.
        party=party.value,
        # Stamped by `_regenerate` below, from the render itself.
        template_version=None,
        recipient=await _party_address(db, loan_file=loan_file, party=party),
        initiated_by_user_id=actor_user_id,
    )
    db.add(draft)
    await db.flush()

    # ORDER IS THE ORDER A READER READS. What this party already had first, oldest membership first,
    # then what this request adds.
    for need in [*outstanding, *fresh]:
        db.add(CommunicationNeedsItem(communication_id=draft.id, needs_item_id=need.id))
    await db.flush()

    await _regenerate(db, draft=draft, loan_file=loan_file)
    return PartyDraft(
        party=party,
        draft=draft,
        added=tuple(need.id for need in fresh),
        already_present=already,
    )


async def _revoke_link_in_url(db: AsyncSession, *, loan_file: LoanFile, url: str) -> None:
    """Revoke the link a stored URL names, if it is still live and still this file's.

    The URL's last segment is the plaintext token and `upload_links` stores its SHA-256, so the row
    is findable by the same hash the redemption path matches on. Scoped to the file as well: a URL
    is text in a column, and a row is only this draft's to revoke if it belongs to this draft's file.
    """
    token = url.rstrip("/").rsplit("/", 1)[-1]
    if not token:
        return
    previous = (
        await db.execute(
            only_active(
                select(UploadLink).where(
                    UploadLink.token_hash == hash_token(token),
                    UploadLink.loan_file_id == loan_file.id,
                ),
                UploadLink,
            )
        )
    ).scalar_one_or_none()
    if previous is not None and previous.is_usable():
        await revoke_link(db, link=previous)


@dataclass(frozen=True)
class ComposedRequest:
    """What a compose produced (LP-833)."""

    update: DraftUpdate
    #: Whether a MODEL wrote the framing, or the deterministic template did.
    #:
    #: RETURNED SO THE SCREEN CAN SAY WHICH, and that is not decoration. `email_draft_enabled` is
    #: False by default and set in no environment, so today this is always False and a processor gets
    #: LP-817's template — a complete email, not a degraded one. A flow that claimed "AI wrote this"
    #: on a path nobody can reach would be the untrue half of its own headline.
    composed_by_model: bool


async def compose_request(
    db: AsyncSession,
    *,
    loan_file: LoanFile,
    document_types: list[str],
    actor_user_id: UUID,
) -> ComposedRequest:
    """Turn a processor's document selection into needs and a draft. ``flush`` only.

    THE ONLY WAY TO ASK FOR SOMETHING NO RULE ASKED FOR. Until this, a draft could come from a
    FINDING and nothing else: a processor who knew they needed a document the engine had not flagged
    could add a needs item by hand, and nothing drafted from it.

    THE SELECTION BECOMES REAL NEEDS ITEMS, not a list of strings on an email. That is what puts them
    on the needs list, what LP-811a's send moves to REQUESTED, and what starts LP-814's reminder
    clock — a draft listing documents that are not needs would ask a borrower for things nothing is
    tracking.

    ORIGIN IS MANUAL, because that is what it is: a processor decided. `NeedsItemOrigin.FINDING`
    would claim a rule asked for it and put a false provenance on the correction signal LP-70 reads.

    ALREADY-OUTSTANDING TYPES ARE SKIPPED rather than duplicated. Requesting a bank statement that is
    already in an unsent draft should not put it in the email twice, and `add_needs_to_draft` would
    dedupe the membership anyway — this stops the redundant needs ROW, which the dedupe does not.
    """
    # LP-841 — PER PARTY, because "already outstanding" is now a question about a particular draft.
    # A closing disclosure sitting in the lender's draft must not block a bank statement from
    # joining the borrower's, and checking one file-wide set would have coupled them.
    outstanding: dict[ResponsibleParty, set[str | None]] = {}

    async def _is_outstanding(document_type: str) -> bool:
        party = get_guidance(document_type).responsible_party
        if party not in outstanding:
            outstanding[party] = {
                need.needs_type
                for need in await _outstanding_needs(db, loan_file_id=loan_file.id, party=party)
            }
        return document_type in outstanding[party]

    created: list[NeedsItem] = []
    for document_type in document_types:
        if await _is_outstanding(document_type):
            continue
        created.append(
            await create_needs_item(
                db,
                loan_file_id=loan_file.id,
                title=document_label(document_type),
                needs_type=document_type,
                origin=NeedsItemOrigin.MANUAL,
                disposition=NeedsItemDisposition.CONFIRMED,
                reasoning="Requested by the processor from the document catalog",
            )
        )

    update = await add_needs_to_draft(
        db, loan_file=loan_file, needs=created, actor_user_id=actor_user_id
    )

    # ON THE REQUEST, NOT ENQUEUED. Everything else in this codebase puts model work on a worker, and
    # the reason is timeouts; this one is a processor waiting on purpose, which is a different case.
    # `compose` never raises — every failure mode returns None — so a model that is slow, refused or
    # switched off leaves the deterministic draft standing rather than failing the request.
    composed = False
    if update.draft is not None:
        composed = await compose_open_draft_prose(db, loan_file=loan_file, draft=update.draft)
    return ComposedRequest(update=update, composed_by_model=composed)


async def attach_upload_link(
    db: AsyncSession, *, loan_file: LoanFile, draft: Communication
) -> Communication:
    """Mint a secure upload link for this draft, expiring any other live one. ``flush`` only.

    ONE LIVE LINK PER FILE, AND THAT IS THE POINT RATHER THAN A TIDINESS RULE. A link is a bearer
    credential: two live ones means two ways in, one of them in an email nobody is looking at any
    more. Keeping one is also what makes "the link in this draft" a meaningful phrase — otherwise a
    borrower holding an older message has a working link to a request that has moved on.

    THE COST IS REAL AND FALLS ON SOMEBODY WHO CANNOT SEE IT. A borrower already sent a link loses
    it, with no explanation on their end — they click and are refused. That is the correct trade
    against two live credentials, and it is why the screen has to say what this does BEFORE it is
    clicked rather than after.

    ADDING A LINK TWICE REPLACES, NEVER APPENDS. The URL lives in a column and the body is rendered
    from it, so a second call overwrites one value and re-renders one line. Two links in one email is
    the state this exists to prevent, and appending is the obvious way to reach it.

    NO RECIPIENT. `mint_upload_link`'s `recipient_email` is optional and stays unset here: the link
    is for whoever the draft is addressed to, which the processor may not have typed yet, and a link
    is not addressed in any way the redemption path checks.
    """
    # LP-834 REVIEW — THIS DRAFT'S PREVIOUS LINK, NOT EVERY LINK ON THE FILE.
    #
    # It revoked every usable link, on the reasoning that one live link per file is the invariant.
    # LP-815 does not agree and shipped first: `GET /upload-links` is documented as "every link
    # minted for this file — a processor needs to see what is live before minting more", the panel
    # lists them with a Revoke button each, and `mint` takes `recipient_email`, `purpose`,
    # `ttl_hours` and `max_uses`. Links are per-recipient and per-purpose there.
    #
    # Measured: a link minted from the panel for `cosigner@example.com`, purpose "Co-borrower's pay
    # stubs", was revoked by clicking Add secure link on the borrower's draft. A different person's
    # link, killed with nothing on any screen saying so — and the warning on the button says "any
    # link already sent to THIS BORROWER stops working", which is a narrower claim than the code was
    # making.
    #
    # What this function is actually for is its own second paragraph: adding a link twice must
    # REPLACE rather than append, so a draft never advertises two links or a dead one. That needs one
    # revocation — the link this draft is holding — and the row is findable because the URL ends in
    # the plaintext token and the table stores its hash. Anything else on the file is somebody else's
    # decision, and `upload-link-panel.tsx` is where it is made.
    if draft.upload_link_url:
        await _revoke_link_in_url(db, loan_file=loan_file, url=draft.upload_link_url)

    minted = await mint_upload_link(db, loan_file=loan_file)
    draft.upload_link_url = minted.url
    await _regenerate(db, draft=draft, loan_file=loan_file)
    # METADATA ONLY — never the URL, which is the credential itself, and never the recipient.
    logger.info("draft_upload_link_attached", loan_file_id=str(loan_file.id))
    return draft


async def remove_need_from_draft(
    db: AsyncSession,
    *,
    loan_file: LoanFile,
    needs_item_id: UUID,
    communication_id: UUID | None = None,
) -> Communication | None:
    """Drop a need from ONE draft and regenerate it. Returns that draft, or None if there is none.

    An emptied draft is KEPT rather than deleted. A processor who removes the last line is editing,
    not abandoning — deleting the row would discard whatever else they had changed, and an empty
    draft is visibly empty, which a missing one is not.

    LP-832 REVIEW — `communication_id` IS NOT OPTIONAL IN MEANING, ONLY IN SIGNATURE. This read "the
    open draft" and resolved it with `get_open_draft`, which was one row while
    `uq_communications_open_draft` existed and is now merely the NEWEST of several. So a request to
    remove a line from the draft a processor is looking at would have silently edited a different
    one — and the function has no caller today, so nothing would have caught it: LP-831 builds the
    drafts list, and this is the function it will reach for.

    The parameter defaults to None so the existing tests still describe the single-draft case
    honestly, and that fallback still means "the newest". A caller that HAS a draft in front of a
    person must pass its id.
    """
    if communication_id is not None:
        draft = await db.get(Communication, communication_id)
        if (
            draft is None
            or draft.loan_file_id != loan_file.id
            or draft.deleted_at is not None
            or draft.status is not CommunicationStatus.DRAFT
        ):
            # The same answer a missing draft gets. A draft on another file must not be
            # distinguishable from one that does not exist.
            return None
    else:
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
