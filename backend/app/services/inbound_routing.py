"""Deciding which loan file an inbound message belongs to (LP-805).

THIS MODULE CONTAINS THE ONE INVERSION OF THE TENANCY INVARIANT IN THE CODEBASE.

Everywhere else, `company_id` comes from an authenticated user and a query is scoped to it before it
runs. Here it comes from an EMAIL ADDRESS a stranger typed. `resolve_loan_file_by_address` starts
from that address, finds a loan file, and the company is read OFF THE FILE — never from the message,
never from the sender, never from a header.

Nothing else in this codebase may do this. The execution protocol makes a second one a blocking
finding, and the reason is that every other tenancy guarantee in the system is a consequence of
company scoping happening before the query rather than after it.

THREE PROPERTIES THE RESOLVER HAS, EACH FOR A REASON THAT IS NOT OBVIOUS:

* **Unknown and expired behave identically**, and both behave like an address that was never valid.
  A resolver that distinguished them is an oracle: send to a guessed token, and a different response
  tells you whether that file exists.
* **The lookup is case-insensitive.** Mail clients and relays rewrite case in the local part freely,
  and a case-sensitive lookup sends a borrower's documents to triage because their phone capitalised
  the first letter.
* **The domain is part of the credential.** Matching the local part alone would let a token lifted
  from one environment's address resolve against another's — staging tokens opening production files.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.helpers import only_active
from app.models.inbound_message import InboundMessage
from app.models.loan_file import LoanFile

logger = get_logger(__name__)

#: `lf-<token>@<domain>`. The token is what `services/loan_file_ids.py` mints; the prefix is what
#: `LoanFile.get_inbox_address` writes.
_INBOX_LOCAL_PART = re.compile(r"^lf-(?P<token>[A-Za-z0-9_-]+)$")


class RoutingSignal(StrEnum):
    """Which rung of the ladder matched. Stored, not discarded — a processor deciding whether to
    trust an auto-routed message needs to know what it was routed ON."""

    INBOX_TOKEN = "inbox_token"  # rung 1
    THREAD_REFERENCE = "thread_reference"  # rung 2


#: Rung confidences, from `phase4.md` §2.2. Stored so that CONFIDENCE GATES AUTO-ACCEPTANCE, NEVER
#: VISIBILITY: an unrouted message is always visible to its company's processors, it is simply not
#: attached to a file until somebody says so.
_CONFIDENCE = {
    RoutingSignal.INBOX_TOKEN: 1.0,
    RoutingSignal.THREAD_REFERENCE: 1.0,
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


def inbox_token_in(address: str | None) -> str | None:
    """The inbox token an address carries, or None.

    Checks BOTH halves. The local part must be `lf-<token>` and the domain must be this
    environment's `settings.inbox_domain` — see the module docstring on why the domain is part of the
    credential rather than decoration.
    """
    if not address:
        return None
    candidate = address.strip().strip("<>").lower()
    local, separator, domain = candidate.partition("@")
    if not separator or domain != settings.inbox_domain.lower():
        return None
    found = _INBOX_LOCAL_PART.match(local)
    return found.group("token") if found else None


async def resolve_loan_file_by_address(db: AsyncSession, *, address: str | None) -> LoanFile | None:
    """THE RESOLVER. An address in, a loan file or None out.

    The ONE place in this codebase permitted to derive a company from something a stranger sent.
    Callers read `company_id` off the returned file; nothing else here produces one.

    Returns None for an unknown token, an expired one, a soft-deleted file, a well-formed address on
    the wrong domain, and a malformed address — deliberately indistinguishable, so the response
    cannot be used to probe which files exist.
    """
    token = inbox_token_in(address)
    if token is None:
        return None

    # LOWER() ON BOTH SIDES rather than a normalised column: `inbox_token` is minted from
    # `secrets.token_urlsafe`, which is case-SIGNIFICANT, so two distinct tokens can differ only in
    # case. Comparing case-insensitively is therefore a deliberate narrowing of the token's entropy
    # — accepted because a mail relay may rewrite the local part and a borrower whose documents
    # vanish is a worse outcome than the ~1 bit per alphabetic character this costs against an
    # attacker who already has to guess 128 bits.
    resolved = (
        await db.execute(
            only_active(select(LoanFile).where(func.lower(LoanFile.inbox_token) == token), LoanFile)
        )
    ).scalar_one_or_none()

    if resolved is None:
        # METADATA ONLY — never the address, which is the token itself and therefore a capability.
        logger.info("inbound_token_unresolved")
        return None
    return resolved


def _recipient_addresses(message: InboundMessage) -> tuple[str, ...]:
    """Every address the message was delivered to.

    `to_addresses` is populated at ingest from `To` and `Delivered-To`. Cc, Bcc and
    `X-Gm-Original-To` are named by `phase4.md` §2.2 rung 1 and are NOT here — LP-803 does not
    collect them. Recorded rather than silently narrowed: a borrower who Ccs the file address instead
    of To-ing it currently goes to triage.
    """
    return tuple(message.to_addresses or ())


async def _route_by_token(db: AsyncSession, message: InboundMessage) -> RoutingOutcome | None:
    """Rung 1 — a recipient carries the file's inbox token. Certain."""
    for address in _recipient_addresses(message):
        resolved = await resolve_loan_file_by_address(db, address=address)
        if resolved is not None:
            return RoutingOutcome(
                resolved, RoutingSignal.INBOX_TOKEN, _CONFIDENCE[RoutingSignal.INBOX_TOKEN]
            )
    return None


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


async def route_message(db: AsyncSession, *, message: InboundMessage) -> RoutingOutcome:
    """Run the ladder. First hit wins; the confidence is stored, not discarded.

    Rungs 1 and 2 only. `phase4.md` §7 assigns rungs 3-5 to LP-808 and rung 6 is an AI SUGGESTION
    that never auto-accepts. The build plan's LP-805 section says "the six-rung ladder", which
    disagrees with the ticket table in the design doc — recorded in the ticket rather than resolved
    by picking the larger reading.

    NO MATCH IS NOT AN ERROR. An unrouted message goes to its company's triage queue and is visible
    there; confidence gates auto-acceptance, never visibility.
    """
    for rung in (_route_by_token, _route_by_thread):
        outcome = await rung(db, message)
        if outcome is not None:
            return outcome
    return RoutingOutcome(None, None, None)


class Disposition(StrEnum):
    """What happens to a routed message — `phase4.md` §2.3."""

    AUTO_ACCEPT = "auto_accept"
    TRIAGE = "triage"
    REJECT = "reject"


def _verdict(message: InboundMessage, key: str) -> str:
    """One SES verdict, upper-cased, or empty. Never defaults to PASS."""
    value = (message.auth_verdicts or {}).get(key)
    return str(value).upper() if value is not None else ""


async def decide_disposition(
    db: AsyncSession, *, message: InboundMessage, outcome: RoutingOutcome
) -> tuple[Disposition, str]:
    """Whether this message may be accepted, must be triaged, or must be rejected.

    QUARANTINE IS THE DEFAULT, NOT THE EXCEPTION (`phase4.md` §2.3). A processor already reviews
    every document; one click to accept a first-time sender costs almost nothing and closes the whole
    class of "a stranger dropped a document into a loan file". So TRIAGE is what happens unless every
    auto-accept condition holds, and REJECT is reserved for the three cases where there is nothing
    for a person to decide.

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
    if _verdict(message, "dmarcVerdict") != "PASS":
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


async def apply_routing(db: AsyncSession, *, message: InboundMessage) -> RoutingOutcome:
    """Route one message, record what happened, and open the correspondence record. ``flush`` only.

    THE COMPANY IS READ OFF THE RESOLVED FILE. That is the invariant this whole module exists to keep
    in one place: `message.company_id` is written here, from `loan_file.company_id`, and from nowhere
    else.
    """
    from app.models.activity_log import ActivityType
    from app.models.communication import (
        Communication,
        CommunicationDirection,
        CommunicationStatus,
    )
    from app.models.inbound_message import InboundRoutingState
    from app.services.activity_log import log_activity

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
        # NO company_id. An unrouted message belongs to nobody yet, and guessing one from the sender
        # is exactly the derivation this module exists to confine. LP-806's triage queue is
        # per-company and reads only routed-or-quarantined rows for that reason.
        await db.flush()
        return outcome

    message.company_id = outcome.loan_file.company_id
    message.loan_file_id = outcome.loan_file.id
    message.routing_state = {
        Disposition.REJECT: InboundRoutingState.REJECTED,
        Disposition.TRIAGE: InboundRoutingState.ROUTED,
        Disposition.AUTO_ACCEPT: InboundRoutingState.ROUTED,
    }[disposition]

    # The model and the enum value have both existed since LP-20 and have never been used.
    db.add(
        Communication(
            loan_file_id=outcome.loan_file.id,
            direction=CommunicationDirection.INBOUND,
            status=CommunicationStatus.RECEIVED,
            external_message_id=message.message_id,
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
        loan_file_id=outcome.loan_file.id,
        activity_type=ActivityType.COMMUNICATION_RECEIVED,
        summary="A message arrived for this file",
        detail={
            "inbound_message_id": str(message.id),
            "routing_signal": message.routing_signal,
            "routing_confidence": message.routing_confidence,
            "disposition": disposition.value,
            "reason": reason,
        },
    )
    await db.flush()
    return outcome


__all__ = [
    "Disposition",
    "RoutingOutcome",
    "RoutingSignal",
    "apply_routing",
    "decide_disposition",
    "inbox_token_in",
    "resolve_loan_file_by_address",
    "route_message",
]
