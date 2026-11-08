"""Deciding which loan file an inbound message belongs to (LP-805, LP-1008, LP-1009).

THIS MODULE CONTAINS THE ONE INVERSION OF THE TENANCY INVARIANT IN THE CODEBASE.

Everywhere else, `company_id` comes from an authenticated user and a query is scoped to it before it
runs. Here it comes from an EMAIL ADDRESS a stranger typed. The company comes from the resolved file,
or from the company's own mail domain the mail was delivered to (`company_from_delivered_domain`,
LP-1009); never from headers or the sender.

Nothing else in this codebase may do this. The execution protocol makes a second one a blocking
finding, and the reason is that every other tenancy guarantee in the system is a consequence of
company scoping happening before the query rather than after it.

THREE PROPERTIES THE RESOLVER HAS, EACH FOR A REASON THAT IS NOT OBVIOUS:

* **Unknown file, wrong domain and inactive domain behave identically**, and all behave like an
  address that was never valid. A resolver that distinguished them is an oracle: send to a guessed
  address, and a different response tells you whether that file exists.
* **The lookup is case-insensitive.** Mail clients and relays rewrite case in the local part freely,
  and a case-sensitive lookup sends a borrower's documents to triage because their phone capitalised
  the first letter.
* **The domain is part of the match.** Display ids are short and not secret, so the local part alone
  proves nothing: the file must belong to the company that owns the domain the mail was sent to.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.company_mail_domain import (
    RECEIVING_STATUSES,
    CompanyMailDomain,
)
from app.models.helpers import only_active
from app.models.inbound_message import InboundMessage
from app.models.loan_file import LoanFile

logger = get_logger(__name__)

#: `lf-<code>`, lowercased: the file's `display_id` (`LF-XXXX`, `services/loan_file_ids.py`) as
#: `services/mail_domain.file_address` writes it.
_FILE_ADDRESS_LOCAL_PART = re.compile(r"^lf-[a-z0-9]+$")


class RoutingSignal(StrEnum):
    """Which rung of the ladder matched. Stored, not discarded — a processor deciding whether to
    trust an auto-routed message needs to know what it was routed ON."""

    # Rung 1. The value predates LP-1008 (it now means the file address); the Communication tab
    # labels it "Sent to this file's address".
    INBOX_TOKEN = "inbox_token"
    THREAD_REFERENCE = "thread_reference"  # rung 2
    FOOTER_TAG = "footer_tag"  # rung 3 (LP-808)
    PARTICIPANT = "participant"  # rung 4 (LP-808)
    SUBJECT_REFERENCE = "subject_reference"  # rung 5 (LP-808)
    MANUAL = "manual"  # a person moved it to the file (LP-1009)


#: Rung confidences, from `phase4.md` §2.2. Stored so that confidence gates auto-acceptance.
_CONFIDENCE = {
    RoutingSignal.INBOX_TOKEN: 1.0,
    RoutingSignal.THREAD_REFERENCE: 1.0,
    # HIGH, NOT CERTAIN. §2.2 grades the footer tag "high": it is a display id, which ADR-397 calls
    # an identifier whose predictability is low-risk — so anybody who has seen one of our emails can
    # write one into a message. High is enough to route and not enough to auto-accept.
    RoutingSignal.FOOTER_TAG: 0.8,
    # MEDIUM. The sender is on the file and exactly one open file matches — but a sender address is
    # forgeable, and this rung is reached precisely when nothing checkable matched.
    RoutingSignal.PARTICIPANT: 0.5,
    RoutingSignal.SUBJECT_REFERENCE: 0.5,
    RoutingSignal.MANUAL: 1.0,
}


@dataclass(frozen=True)
class RoutingOutcome:
    """Where a message was routed, and on what evidence."""

    loan_file: LoanFile | None
    signal: RoutingSignal | None
    confidence: float | None

    @property
    def routed(self) -> bool:
        return self.loan_file is not None


def _file_address_parts(address: str | None) -> tuple[str, str] | None:
    """``(local part, domain)`` of a well-formed file address, lowercased, or None."""
    if not address:
        return None
    local, separator, domain = address.strip().strip("<>").lower().partition("@")
    if not separator or not domain or not _FILE_ADDRESS_LOCAL_PART.match(local):
        return None
    return local, domain


async def resolve_loan_file_by_address(db: AsyncSession, *, address: str | None) -> LoanFile | None:
    """THE RESOLVER. An address in, a loan file or None out.

    The ONE place in this codebase permitted to derive a company from something a stranger sent.
    Callers read `company_id` off the returned file; nothing else here produces one.

    `lf-<display_id>@<domain>` finds the active file with that `display_id` whose company has that
    domain, status active or problem. A `problem` domain still receives: the hourly check found its
    DNS broken, which pauses Send, and mail already on its way must still reach the file.

    Returns None for an unknown file, a soft-deleted file, the wrong company's domain, an inactive
    domain and a malformed address — deliberately indistinguishable, so the response cannot be used
    to probe which files exist.
    """
    parts = _file_address_parts(address)
    resolved: LoanFile | None = None
    if parts is not None:
        local, domain = parts
        # `display_id` is globally unique, so this is one row at most.
        resolved = (
            await db.execute(
                only_active(
                    select(LoanFile)
                    .join(CompanyMailDomain, CompanyMailDomain.company_id == LoanFile.company_id)
                    .where(
                        func.lower(LoanFile.display_id) == local,
                        CompanyMailDomain.domain == domain,
                        CompanyMailDomain.status.in_(RECEIVING_STATUSES),
                    ),
                    LoanFile,
                )
            )
        ).scalar_one_or_none()

    if resolved is None:
        # METADATA ONLY — never the address, which names a borrower's file.
        logger.info("inbound_address_unresolved")
    return resolved


def _recipient_addresses(message: InboundMessage) -> tuple[str, ...]:
    """The addresses in the message's own headers. Route B only: routing never reads these (rule 7).

    `to_addresses` is populated at ingest from `To` and `Delivered-To`, which the sender writes.
    """
    return tuple(message.to_addresses or ())


async def _route_by_address(db: AsyncSession, message: InboundMessage) -> RoutingOutcome | None:
    """Rung 1 — the envelope recipients name exactly one file. Certain.

    THE ENVELOPE, NEVER To/Cc (rule 7). Headers are text the sender wrote; `receipt.recipients` is
    where SES actually delivered. Two addresses of one file are one file. Two files mean a person
    decides (decision 11-04), so that is no match, the same as none.
    """
    matched: dict[UUID, LoanFile] = {}
    for address in message.envelope_recipients or ():
        resolved = await resolve_loan_file_by_address(db, address=address)
        if resolved is not None:
            matched[resolved.id] = resolved
    if len(matched) != 1:
        return None
    return RoutingOutcome(
        next(iter(matched.values())),
        RoutingSignal.INBOX_TOKEN,
        _CONFIDENCE[RoutingSignal.INBOX_TOKEN],
    )


async def _route_by_thread(db: AsyncSession, message: InboundMessage) -> RoutingOutcome | None:
    """Rung 2 — `In-Reply-To` or `References` names a message id we generated. Certain.

    THE WHOLE `References` ARRAY IS MATCHED, not just the last entry. The plan calls this out and the
    reason is concrete: clients truncate the middle of a long `References` chain differently, so the
    entry that survives in one borrower's reply is not the one that survives in another's. Matching
    only the tail means a long thread routes for some clients and not others, which reads as
    intermittent.
    """
    from app.models.communication import Communication

    candidates = [
        candidate for candidate in (message.in_reply_to, *(message.references or ())) if candidate
    ]
    if not candidates:
        return None

    normalised = [candidate.strip().strip("<>") for candidate in candidates]
    found = (
        await db.execute(
            select(Communication)
            .where(Communication.external_message_id.in_(normalised))
            .order_by(Communication.sent_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if found is None:
        return None

    loan_file = await db.get(LoanFile, found.loan_file_id)
    if loan_file is None or loan_file.deleted_at is not None:
        return None
    return RoutingOutcome(
        loan_file, RoutingSignal.THREAD_REFERENCE, _CONFIDENCE[RoutingSignal.THREAD_REFERENCE]
    )


async def _scoped_files(db: AsyncSession, company_id: UUID | None) -> list[LoanFile]:
    """Active loan files for one company, or nothing when the company is unknown.

    RUNGS 3-5 ARE COMPANY-SCOPED. Rung 1 gets its company from the address's domain and rung 2 from a
    message id we generated. The last three match on a display id, a sender address or a subject
    line, none of which is unguessable, so scoping is the only thing stopping
    `[LF-7K3M]` in a stranger's subject line from reaching whichever company happens to hold that id.

    NO COMPANY MEANS NO CANDIDATES. A message with no `company_id` reached us at an address nobody
    owns, and there is no set of files it could belong to — returning "all of them" would be the
    cross-tenant failure this scoping exists to prevent.
    """
    if company_id is None:
        return []
    stmt = select(LoanFile).where(LoanFile.company_id == company_id)
    return list((await db.execute(only_active(stmt, LoanFile))).scalars().all())


async def _route_by_footer_tag(db: AsyncSession, message: InboundMessage) -> RoutingOutcome | None:
    """Rung 3 — the `[LF-xxxx]` tag we put in every outbound footer. High, not certain.

    THE ZENDESK FALLBACK, for clients that strip or rewrite `Reply-To`. §2.2 grades it "high"
    rather than certain because a display id is an IDENTIFIER, not a capability (ADR-397): anyone
    who has ever received one of our emails can put that string in a message.

    READ FROM THE SUBJECT AND THE STORED BODY. The subject is on the row; the body is not, so the
    raw message is re-read from storage — which is why this rung is third and not first.
    """
    from app.services.email_send import loan_reference_in

    candidates = await _scoped_files(db, message.company_id)
    if not candidates:
        return None

    haystacks: list[str] = [message.subject or ""]
    body = await _stored_body(message)
    if body:
        haystacks.append(body)

    by_display_id = {loan_file.display_id.upper(): loan_file for loan_file in candidates}
    for text_block in haystacks:
        reference = loan_reference_in(text_block)
        if reference is None:
            continue
        found = by_display_id.get(reference.upper())
        if found is not None:
            return RoutingOutcome(
                found, RoutingSignal.FOOTER_TAG, _CONFIDENCE[RoutingSignal.FOOTER_TAG]
            )
    return None


async def _route_by_participant(db: AsyncSession, message: InboundMessage) -> RoutingOutcome | None:
    """Rung 4 — the sender is on exactly ONE of this company's open files. Medium.

    EXACTLY ONE, and the word is load-bearing. A borrower with two files in progress is the ordinary
    case, and picking either would file half their documents in the wrong place while looking
    confident. Ambiguity here goes to triage, which is the answer a processor can fix in one click.
    """
    from app.services.inbound_participants import normalise_address

    address = normalise_address(message.from_address)
    if address is None:
        return None
    candidates = await _scoped_files(db, message.company_id)
    if not candidates:
        return None

    from app.models.loan_file_participant import LoanFileParticipant

    matches = (
        (
            await db.execute(
                only_active(
                    select(LoanFileParticipant).where(
                        LoanFileParticipant.loan_file_id.in_([f.id for f in candidates]),
                        LoanFileParticipant.email == address,
                    ),
                    LoanFileParticipant,
                )
            )
        )
        .scalars()
        .all()
    )
    files = {row.loan_file_id for row in matches}
    if len(files) != 1:
        return None
    only = next(loan_file for loan_file in candidates if loan_file.id in files)
    return RoutingOutcome(only, RoutingSignal.PARTICIPANT, _CONFIDENCE[RoutingSignal.PARTICIPANT])


async def _route_by_subject(db: AsyncSession, message: InboundMessage) -> RoutingOutcome | None:
    """Rung 5 — the subject names a display id, without the footer's brackets. Medium.

    SEPARATE FROM RUNG 3 rather than folded into it, because they are graded differently and the
    grade is stored. A bracketed `[LF-7K3M]` is our own footer coming back; a bare `LF-7K3M` is
    somebody typing the reference into a subject line, which is likelier to be a person being
    helpful and likelier to be wrong.
    """
    subject = message.subject or ""
    if not subject:
        return None
    candidates = await _scoped_files(db, message.company_id)
    if not candidates:
        return None
    upper = subject.upper()
    matched = [loan_file for loan_file in candidates if loan_file.display_id.upper() in upper]
    if len(matched) != 1:
        return None
    return RoutingOutcome(
        matched[0], RoutingSignal.SUBJECT_REFERENCE, _CONFIDENCE[RoutingSignal.SUBJECT_REFERENCE]
    )


async def _stored_body(message: InboundMessage) -> str | None:
    """The message's text, re-read from the stored `.eml`, or None.

    RE-READ RATHER THAN STORED. `InboundMessage` deliberately holds no body — §4's data model keeps
    the raw message in S3 and the row as metadata, so a borrower's prose lives in one place with one
    retention story. This is the only rung that needs it.

    NEVER RAISES. Storage being unavailable must degrade this rung to "no match" rather than fail
    the whole ingest: a message that cannot be routed goes to triage, which is recoverable, and a
    task that crashes leaves it unrouted anyway with an alarm nobody can action.
    """
    if not message.raw_storage_path:
        return None
    try:
        import email

        from app.storage import get_storage_backend

        path = message.raw_storage_path
        if path.startswith("s3://"):
            path = path.split("/", 3)[3]
        raw = await get_storage_backend().read(path)
        parsed = email.message_from_bytes(raw)
        parts: list[str] = []
        for part in parsed.walk():
            if part.get_content_maintype() != "text":
                continue
            payload = part.get_payload(decode=True)
            if isinstance(payload, bytes):
                parts.append(payload.decode("utf-8", "replace"))
        return "\n".join(parts) if parts else None
    except Exception:
        # METADATA ONLY, and a warning rather than an error: this is a rung failing to fire, not a
        # message being lost.
        logger.warning("inbound_body_unreadable")
        return None


async def route_message(db: AsyncSession, *, message: InboundMessage) -> RoutingOutcome:
    """Rung 1 only: the file named by the envelope recipients, or unrouted.

    NO MATCH IS NOT AN ERROR. An unrouted message has no company, so no company sees it (LP-1008).
    """
    # Rungs 2-5 are off by decision 11-04 (address only); their code stays, uncalled.
    outcome = await _route_by_address(db, message)
    return outcome if outcome is not None else RoutingOutcome(None, None, None)


class Disposition(StrEnum):
    """What happens to a routed message — `phase4.md` §2.3."""

    AUTO_ACCEPT = "auto_accept"
    TRIAGE = "triage"
    REJECT = "reject"


def _verdict(message: InboundMessage, key: str) -> str:
    """One SES verdict, upper-cased, or empty. Never defaults to PASS."""
    value = (message.auth_verdicts or {}).get(key)
    return str(value).upper() if value is not None else ""


def _sender_authenticated(message: InboundMessage) -> bool:
    """Whether the SENDER — not the forwarder — is who they claim.

    TWO DIFFERENT QUESTIONS FOR TWO DIFFERENT PATHS, and conflating them is the Route B trap.

    On a direct message, SES's `dmarcVerdict` is about the sender, so it is the answer. On a
    FORWARDED message, that same verdict is about the forwarder, who is a Google or Microsoft tenant
    and will essentially always pass — reading it would make every forwarded message look
    authenticated regardless of who actually sent it. The original hop's verdict is the one that is
    about the borrower.

    The two are told apart by whether an original hop was recorded at all, which happens only when a
    connection resolved. `PASS` is compared for equality in both branches, so `GRAY`, `none` and
    anything unrecognised fail closed.
    """
    if "originalHopAuthenticated" in (message.auth_verdicts or {}):
        return _verdict(message, "originalHopAuthenticated") == "PASS"
    return _verdict(message, "dmarcVerdict") == "PASS"


async def decide_disposition(
    db: AsyncSession, *, message: InboundMessage, outcome: RoutingOutcome
) -> tuple[Disposition, str]:
    """Whether this message may be accepted, must be triaged, or must be rejected.

    QUARANTINE IS THE DEFAULT, NOT THE EXCEPTION (`phase4.md` §2.3). A processor already reviews
    every document; one click to accept a first-time sender costs almost nothing and closes the whole
    class of "a stranger dropped a document into a loan file". So TRIAGE is what happens unless every
    auto-accept condition holds, and REJECT is reserved for the three cases where there is nothing
    for a person to decide.

    A FORWARDED MESSAGE IS JUDGED ON ITS ORIGINAL HOP (LP-808) — see `_sender_authenticated`. Its
    own SES DMARC verdict is about the forwarder, and reading that would make every Route B message
    look authenticated whoever sent it.

    `GRAY` IS NOT `PASS`, and this is the subtlety §2.3 calls out. SES's `dkimVerdict: GRAY` most
    often means *signed by a domain that does not match `From:`* — precisely the spoofing case. It is
    compared for equality with PASS rather than tested for "not FAIL", so an unrecognised verdict
    fails closed.

    AUTO-ACCEPT IS ALSO OFF PER FILE BY DEFAULT. The conditions below are necessary, not sufficient:
    `LoanFile.auto_accept_inbound` is LP-806's column and does not exist yet, so nothing
    auto-accepts today and this function's AUTO_ACCEPT branch is unreachable in production. Returning
    it anyway is deliberate — the rule is written and tested now, so LP-806 turns a flag on rather
    than inventing the policy under time pressure.
    """
    if _verdict(message, "virusVerdict") == "FAIL":
        return Disposition.REJECT, "The message failed a virus scan."
    if _verdict(message, "dmarcVerdict") == "FAIL" and _verdict(message, "dmarcPolicy") == "REJECT":
        return (
            Disposition.REJECT,
            "The sender's domain asked us to reject messages that fail DMARC.",
        )
    if not outcome.routed:
        return Disposition.TRIAGE, "This message could not be matched to a loan file."

    if message.is_dsn or message.is_auto_reply:
        # Not a document and not a reply worth acting on. Triaged rather than rejected: LP-819 reads
        # bounces, and an auto-reply is a fact a processor may want to see.
        return Disposition.TRIAGE, "This is an automatic reply or a delivery notification."

    if outcome.confidence is None or outcome.confidence < 1.0:
        return Disposition.TRIAGE, "The match to this loan file is not certain."
    if not _sender_authenticated(message):
        return Disposition.TRIAGE, "The sender's domain did not authenticate."
    if _verdict(message, "virusVerdict") != "PASS":
        return Disposition.TRIAGE, "The message has not been confirmed virus-free."

    assert outcome.loan_file is not None  # `outcome.routed` above
    from app.services.inbound_participants import is_trusted_sender

    if not await is_trusted_sender(
        db, loan_file_id=outcome.loan_file.id, address=message.from_address
    ):
        return Disposition.TRIAGE, "This sender has not been trusted on this file."

    return Disposition.AUTO_ACCEPT, "Certain match from a trusted sender that authenticated."


def record_original_hop(message: InboundMessage, *, raw: bytes | None) -> bool:
    """Merge the FIRST HOP's verdicts into `auth_verdicts` for a forwarded message. True if any.

    ONLY FOR A FORWARD, and the caller enforces that by only calling it when a connection resolved.
    §2.3 forbids reading `Authentication-Results` out of the body of a message that arrived
    directly, because RFC 8601 says a stranger can write one; Route B is the single exception,
    because there the header was added by the borrower's own provider before the forward.

    UNDER SEPARATE KEYS. SES's `dmarcVerdict` for a forwarded message is a verdict about the
    FORWARDER, and overwriting it would let the forwarder's pass be read as the borrower's — the
    exact confusion `services/original_hop` exists to prevent.
    """
    if raw is None:
        return False
    import email as email_module

    from app.services.original_hop import as_auth_verdicts, evaluate_original_hop

    parsed = email_module.message_from_bytes(raw)
    recorded = as_auth_verdicts(evaluate_original_hop(parsed))
    message.auth_verdicts = {**(message.auth_verdicts or {}), **recorded}
    return True


async def attach_route_b_company(db: AsyncSession, *, message: InboundMessage) -> bool:
    """Route B — set `company_id` from the `co-<token>@` alias the message arrived at. True if set.

    THIS RUNS BEFORE THE LADDER, and it must: rungs 3-5 are company-scoped, so without a company they
    return nothing and a forwarded message can only ever route on a token or a thread id — which is
    the case Route B exists to cover, because on Route B the borrower wrote to HER address and never
    saw ours.

    IT SETS THE COMPANY AND NOTHING ELSE. The loan file still comes from the ladder. That separation
    is what keeps the file-level tenancy invariant intact while adding a company-level one — see
    `services/mailbox_connections` for the full argument, and for why this is the third and last
    inversion the protocol permits.

    THE ORIGINAL RECIPIENT IS ALSO TRIED. Google's admin-level forward preserves `X-Gm-Original-To`
    and Microsoft's transport rule preserves the original `To` — so a message forwarded to us may
    still carry `lf-<token>@` from the borrower's own reply, and rung 1 then matches with certainty.
    Nothing here needs to know that; it is why `to_addresses` collects both.
    """
    from app.services.mailbox_connections import record_arrival, resolve_connection_by_address

    if message.company_id is not None:
        return False
    for address in _recipient_addresses(message):
        connection = await resolve_connection_by_address(db, address=address)
        if connection is None:
            continue
        message.company_id = connection.company_id
        # VERIFICATION FLIPS ON ARRIVAL, not on a button. `phase4.md` §3: "the moment anything
        # arrives at that address we flip it to verified".
        await record_arrival(db, connection=connection)
        await db.flush()
        logger.info("inbound_routed_via_connection", connection_id=str(connection.id))
        return True
    return False


async def company_from_delivered_domain(db: AsyncSession, message: InboundMessage) -> UUID | None:
    """The one company owning every domain the message was delivered to, or None.

    SAFE BECAUSE OF TWO FACTS: a domain row belongs to one company (a unique column), and the domain
    comes from `envelope_recipients`, where SES says it delivered, not from anything the sender wrote.

    STRICT. A recipient on a domain with no row, or on one that is not receiving (`RECEIVING_STATUSES`,
    the same states the file address and the `inbox` capability use), gives None, as do domains of
    two companies: a message nobody can place on one company goes to no company.
    """
    domains = {
        recipient.strip().lower().rpartition("@")[2]
        for recipient in message.envelope_recipients or ()
    }
    if not domains:
        return None
    rows = (
        await db.execute(
            select(CompanyMailDomain.domain, CompanyMailDomain.company_id).where(
                CompanyMailDomain.domain.in_(domains),
                CompanyMailDomain.status.in_(RECEIVING_STATUSES),
            )
        )
    ).all()
    companies: set[UUID] = {row.company_id for row in rows}
    if {row.domain for row in rows} != domains or len(companies) != 1:
        return None
    return companies.pop()


async def _record_arrival(
    db: AsyncSession,
    *,
    message: InboundMessage,
    loan_file: LoanFile,
    summary: str,
    disposition: Disposition,
    reason: str,
    actor_user_id: UUID | None = None,
) -> None:
    """The correspondence record and the activity entry for a message now on a file."""
    from app.models.activity_log import ActivityType
    from app.models.communication import (
        Communication,
        CommunicationDirection,
        CommunicationStatus,
    )
    from app.services.activity_log import log_activity

    # The model and the enum value have both existed since LP-20 and have never been used.
    db.add(
        Communication(
            loan_file_id=loan_file.id,
            direction=CommunicationDirection.INBOUND,
            status=CommunicationStatus.RECEIVED,
            external_message_id=message.message_id,
            # LP-812 — the timeline's row for this arrival is THIS one, and the attachments hang
            # off `inbound_messages`. A real FK rather than matching on `external_message_id`,
            # which the sender writes and which is neither unique nor always present.
            inbound_message_id=message.id,
            # NO subject, NO body, NO sender. They are on the inbound_message row, which the
            # readonly view already drops; copying them here would put borrower prose in a second
            # place with its own exposure decisions.
            #
            # And no arrival timestamp: `Communication` has `sent_at`, which is about OUTBOUND mail,
            # and reusing it for a received-at would make "when did we send this" answer with a time
            # nobody sent anything. The inbound_message row carries `received_at`.
        )
    )
    await log_activity(
        db,
        loan_file_id=loan_file.id,
        activity_type=ActivityType.COMMUNICATION_RECEIVED,
        summary=summary,
        actor_user_id=actor_user_id,
        detail={
            "inbound_message_id": str(message.id),
            "routing_signal": message.routing_signal,
            "routing_confidence": message.routing_confidence,
            "disposition": disposition.value,
            "reason": reason,
        },
    )


async def move_message_to_file(
    db: AsyncSession, *, message: InboundMessage, loan_file: LoanFile, actor_user_id: UUID
) -> None:
    """A person places an unrouted message on a file (LP-1009). ``flush`` only.

    The caller has already checked that the message and the file are both the caller's company's.
    """
    from app.models.inbound_message import InboundRoutingState

    message.loan_file_id = loan_file.id
    message.routing_state = InboundRoutingState.ROUTED
    message.routing_signal = RoutingSignal.MANUAL.value
    message.routing_confidence = _CONFIDENCE[RoutingSignal.MANUAL]
    await _record_arrival(
        db,
        message=message,
        loan_file=loan_file,
        summary="An unmatched email was moved to this file",
        disposition=Disposition.TRIAGE,
        reason="A person moved it to this file.",
        actor_user_id=actor_user_id,
    )
    await db.flush()


async def apply_routing(db: AsyncSession, *, message: InboundMessage) -> RoutingOutcome:
    """Route one message, record what happened, and open the correspondence record. ``flush`` only.

    THE COMPANY IS READ OFF THE RESOLVED FILE, or, for unmatched mail, off the company's own mail
    domain it was delivered to. `message.company_id` is written here and from nowhere else.
    """
    from app.models.inbound_message import InboundRoutingState

    # Route B (`attach_route_b_company`, `record_original_hop`) is off by decision 11-04, address only.
    outcome = await route_message(db, message=message)
    disposition, reason = await decide_disposition(db, message=message, outcome=outcome)

    message.routing_signal = outcome.signal.value if outcome.signal else None
    message.routing_confidence = outcome.confidence

    if outcome.loan_file is None:
        message.routing_state = (
            InboundRoutingState.REJECTED
            if disposition is Disposition.REJECT
            else InboundRoutingState.UNROUTED
        )
        # Never guessed from the sender. Unmatched mail goes to the company owning the domain it was
        # delivered to, or to no company, whose queue no one reads (LP-1008). A rejection stays
        # with no company: there is nothing for a person to place.
        if message.routing_state is InboundRoutingState.UNROUTED:
            message.company_id = await company_from_delivered_domain(db, message)
        await db.flush()
        return outcome

    message.company_id = outcome.loan_file.company_id
    message.loan_file_id = outcome.loan_file.id
    message.routing_state = {
        Disposition.REJECT: InboundRoutingState.REJECTED,
        Disposition.TRIAGE: InboundRoutingState.ROUTED,
        Disposition.AUTO_ACCEPT: InboundRoutingState.ROUTED,
    }[disposition]

    await _record_arrival(
        db,
        message=message,
        loan_file=outcome.loan_file,
        summary="A message arrived for this file",
        disposition=disposition,
        reason=reason,
    )
    # LP-1013 — a reply from the person a follow-up is chasing pauses that follow-up.
    from app.services.follow_ups import pause_for_reply

    await pause_for_reply(db, message=message, loan_file=outcome.loan_file)
    await db.flush()
    return outcome


__all__ = [
    "Disposition",
    "RoutingOutcome",
    "RoutingSignal",
    "apply_routing",
    "attach_route_b_company",
    "company_from_delivered_domain",
    "decide_disposition",
    "move_message_to_file",
    "record_original_hop",
    "resolve_loan_file_by_address",
    "route_message",
]
