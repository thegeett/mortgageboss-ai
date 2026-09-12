"""Sending as her, through a mailbox connection (LP-816).

AN INTERFACE WITH NO PROVIDER BEHIND IT, AND THAT IS THE TICKET. The execution protocol's §5 settles
it: *"Which mail provider is the pilot customer on? **Unknown — build Route B (forwarding) only.** Do
not build Gmail API or Graph. LP-816 stays scoped to a mailbox connection interface with no provider
implementation."*

That is not a shortcut. `phase4.md` §3 prices the alternative: Google's read scopes are *restricted*
and need brand verification, scope justification, a demo video and an **App Defense Alliance CASA
assessment** — realistically 6 to 12 weeks for a first-timer, with annual re-assessment forever. On
Microsoft, Graph is a clean ~1-week build. **Which of those we are looking at is decided by an
answer nobody has given**, and writing the wrong one costs more than writing neither.

SO WHAT THIS MODULE IS: the seam the answer plugs into, and — far more importantly — the proof that
plugging one in cannot skip anything.

THE GUARDS ARE NOT HERE, AND THAT IS THE DESIGN. LP-811a's suppression check, its rate limit and its
approver requirement all live in `send_draft`, and transmission happens INSIDE that function, after
all of them. There is no second send path and no route that reaches a transport directly. A message
that went out through a different transport with none of the checks is the same message with none of
the checks — and the way to make that impossible is not to remember, it is to have nowhere else to
call from.

THE SCOPES ARE A CLOSED SET, for the same reason `TRUSTED_ARC_SEALERS` is. Asking for anything
broader than `gmail.send` or Graph's delegated `Mail.Send` changes the review burden on the
customer's own admin — a *restricted* Google scope drags them into CASA, and an over-broad Entra
permission is a grant their security team is right to refuse. Widening this is a code change with a
reviewer, never configuration.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.core.logging import get_logger
from app.models.mailbox_connection import (
    MailboxConnection,
    MailboxConnectionKind,
    MailboxConnectionStatus,
)

logger = get_logger(__name__)

#: The ONLY scopes a provider implementation may request.
#:
#: `gmail.send` is *sensitive*, not restricted: a scope review, no security assessment. The read
#: scopes (`gmail.readonly`, `gmail.modify`) ARE restricted and would pull the customer into a CASA
#: assessment — which is why inbound is forwarding (Route B) and only OUTBOUND is an API here.
#: `phase4.md` §3 calls that pairing "the cheapest full-duplex configuration" and asks for an ADR.
#:
#: Graph's `Mail.Send` is delegated, needs no admin consent, and has no CASA equivalent. If app-only
#: is ever needed it must be scoped with RBAC for Applications AND the org-wide Entra grant removed —
#: permissions are a UNION, so an unscoped consent makes the RBAC scope do nothing.
ALLOWED_SCOPES: frozenset[str] = frozenset(
    {
        "https://www.googleapis.com/auth/gmail.send",
        "Mail.Send",
    }
)


#: What a HUMAN-APPROVED send carries: nothing.
#:
#: LP-811a built `AUTO_REPLY_SUPPRESSION_HEADERS` and said why they exist — they ask a well-behaved
#: correspondent not to answer. A document request is the one message we most want answered, so
#: setting them on it would ask a borrower's mail system to suppress the reply the whole feature is
#: waiting for. Named rather than passing `None`, so the absence reads as a decision.
AUTO_REPLY_HEADERS_NONE: dict[str, str] = {}


class TransportError(Exception):
    """The message could not be handed to a provider. Never raised for a refusal — a guard refusing
    a send is `CannotSendError`, and conflating the two would make a policy decision look like an
    outage."""


@dataclass(frozen=True)
class OutboundEnvelope:
    """What a transport is given.

    NO ATTACHMENTS FIELD, and it is the same enforcement LP-815 put on `OutboundMessage`: GLBA
    Safeguards 16 CFR 314.4(c)(3) means outbound carries an authenticated, expiring link and never a
    document. A transport that could take one would be the way that rule is bypassed by a provider
    integration nobody re-read the compliance note for.
    """

    to: str
    subject: str
    body: str
    #: `In-Reply-To`, so a reply threads (RFC 5322 §3.6.4). None on a new message.
    in_reply_to: str | None = None
    #: Headers that ask an autoresponder not to answer. Set only on automated mail; a human-approved
    #: send carries none of them.
    headers: dict[str, str] | None = None


@dataclass(frozen=True)
class SentResult:
    """What a transport returns.

    `provider_message_id` IS THE POINT OF SENDING THIS WAY. A message we transmitted has an id we
    generated, which is what LP-805's rung 2 matches a borrower's `References` against — so a reply
    routes with certainty rather than falling to the footer tag. On copy-and-send there is no such
    id, because the message left from her client and we never saw it.
    """

    provider_message_id: str | None


class MailTransport(ABC):
    """One way of putting a message into the world as the processor's own company."""

    #: Which scopes this implementation needs. Checked against `ALLOWED_SCOPES` at registration.
    scopes: frozenset[str] = frozenset()

    @abstractmethod
    async def send(self, envelope: OutboundEnvelope) -> SentResult:
        """Transmit. Raises :class:`TransportError` on failure; never returns a partial success."""


class NoTransport(MailTransport):
    """The one implementation that exists, and it does not send.

    NOT A STUB THAT PRETENDS. It raises, so a caller that reached it by accident fails loudly rather
    than reporting a send that did not happen — which on this path would tell a processor a borrower
    had been written to and start a reminder clock against silence nobody caused.

    `send_draft` never reaches it: it asks `transport_for` first, gets None, and stays on the
    copy-and-send path where a person carries the message to their own client.
    """

    async def send(self, envelope: OutboundEnvelope) -> SentResult:
        raise TransportError(
            "No mailbox transport is configured. This message is prepared for copy-and-send."
        )


#: Provider implementations, by connection kind. EMPTY, per §5 — and the emptiness is what makes
#: `transport_for` return None for every connection today.
_REGISTRY: dict[MailboxConnectionKind, MailTransport] = {}


def register(kind: MailboxConnectionKind, transport: MailTransport) -> None:
    """Register a provider implementation.

    REFUSES A SCOPE OUTSIDE THE ALLOWLIST. This is the one place a future Gmail or Graph build
    declares what it asks the customer's admin for, and a scope creeping past `gmail.send` is the
    change that turns a scope review into a CASA assessment — for them, not for us. Refused here so
    it is a failing import rather than a support conversation six weeks in.
    """
    unknown = transport.scopes - ALLOWED_SCOPES
    if unknown:
        raise TransportError(
            f"{sorted(unknown)} is outside the permitted scopes. "
            "Widening them changes the review burden on the customer's administrator."
        )
    _REGISTRY[kind] = transport


def transport_for(connection: MailboxConnection | None) -> MailTransport | None:
    """The transport that can send as this connection, or None.

    NONE IS THE ORDINARY ANSWER AND MEANS "COPY AND SEND", not "broken". Three ways to reach it:

    * there is no connection — the file has no mailbox connected, which is most files;
    * the connection is `FORWARDED_ALIAS` — **Route B forwards INBOUND mail and cannot send.**
      `phase4.md` §3 names send-as among "what forwarding cannot give", and a transport that tried
      would send from OUR domain with her name on it, which §3's Route C analysis rules out
      explicitly: the borrower sees an unfamiliar sender on a mortgage file, which is the exact shape
      of the phishing they have been warned about;
    * no provider is registered for the kind — which is every kind today, per §5.

    A REVOKED OR UNHEALTHY CONNECTION SENDS NOTHING. `NEEDS_REAUTHORIZATION` is the Route C state
    where a token expired: falling back to copy-and-send there is right, because the alternative is
    refusing to let a processor send at all because an integration lapsed.
    """
    if connection is None:
        return None
    if connection.kind is MailboxConnectionKind.FORWARDED_ALIAS:
        return None
    if connection.status is not MailboxConnectionStatus.CONNECTED:
        return None
    return _REGISTRY.get(connection.kind)


async def transmit(
    connection: MailboxConnection | None, envelope: OutboundEnvelope
) -> SentResult | None:
    """Send if a transport exists. None means nothing was transmitted and the caller stays on
    copy-and-send.

    THIS IS CALLED FROM INSIDE `send_draft`, after the suppression check, the rate limit and the
    approver requirement — never from a route. A provider implementation therefore inherits every
    guard by construction rather than by remembering, which is what stops "send from the app" being
    the same message with none of the checks.

    A TRANSPORT FAILURE DOES NOT UNDO THE RECORD. The message is recorded as sent and the failure is
    surfaced; the alternative is a rollback that loses the evidence row and the needs transition for
    a message that may well have gone out — a provider that timed out after accepting it is the
    ordinary failure, not the exception.
    """
    # LP-847 REVIEW — NO MAILBOX MEANS NOTHING TO TRANSMIT, and this is the one place that can say so
    # for every future provider at once. A no-contact party's draft is now sent with an empty
    # recipient by design, and LP-847 skipped the suppression and rate-limit checks for it because
    # both are questions about a specific address. That is right, and it makes the promise above —
    # that a provider inherits every guard by construction — false for exactly this message unless
    # somebody remembers. Returning None is the answer the docstring already defines: nothing was
    # transmitted and the caller stays on copy-and-send, which is what a draft with no mailbox has
    # always meant in practice.
    if not envelope.to.strip():
        return None
    transport = transport_for(connection)
    if transport is None:
        return None
    try:
        result = await transport.send(envelope)
    except TransportError:
        # METADATA ONLY — never the recipient, the subject or the body. Re-raised, because the
        # caller decides what a failed transmission means for the record it has already written.
        logger.warning("mail_transport_failed", kind=connection.kind.value if connection else None)
        raise
    logger.info(
        "mail_transmitted",
        kind=connection.kind.value if connection else None,
        has_provider_id=result.provider_message_id is not None,
    )
    return result


__all__ = [
    "ALLOWED_SCOPES",
    "AUTO_REPLY_HEADERS_NONE",
    "MailTransport",
    "NoTransport",
    "OutboundEnvelope",
    "SentResult",
    "TransportError",
    "register",
    "transmit",
    "transport_for",
]
