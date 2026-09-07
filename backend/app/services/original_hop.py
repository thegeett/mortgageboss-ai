"""What a FORWARDED message's authentication is worth (LP-808).

THE ONE EXCEPTION TO A RULE THIS CODEBASE OTHERWISE HOLDS ABSOLUTELY. `phase4.md` §2.3: never read
`Authentication-Results` out of the MIME body of a message that arrived directly, because RFC 8601's
security section is explicit that a message can carry a forged header claiming `dmarc=pass`. Verdicts
come from SES's structured `receipt` object.

Route B breaks that, and has to. The message reached the borrower's intended recipient — a Google or
Microsoft tenant — was authenticated THERE, and only then forwarded to us. By the time SES sees it,
every original signal is gone. The header added at that first hop is the only surviving evidence, and
it was written before anything we control touched the message.

SO EVERY FUNCTION HERE IS ABOUT WHY THAT HEADER MIGHT BE A LIE:

* **SPF IS NEVER EVALUATED.** A forwarded message always fails SPF — the connecting IP is now the
  forwarder's. That is a protocol property, not a misconfiguration, and reading it as evidence about
  the borrower is meaningless in both directions: a `spf=fail` on a forward says nothing bad, and a
  `spf=pass` says the FORWARDER is who they claim, which we already knew.
* **`Authentication-Results` is trusted only from the FIRST header**, which by RFC 8601 §5 is the
  one added most recently — the forwarder's own. Anything below it was in the message when the
  forwarder received it, which is to say a stranger could have put it there.
* **An ARC chain is trusted only from an allowlisted sealer**, and the allowlist is a closed set of
  domains we have a reason to believe. `ARC-Authentication-Results` is self-asserted otherwise: a
  sealer nobody vouches for is a stranger writing "I checked, it's fine".
* **A surviving `DKIM-Signature` is worth more than any of it**, because it is checkable rather than
  asserted. This module records that one is PRESENT and aligned with `From:`; verifying the
  cryptography needs the sender's public key and a DNS lookup, which is a network call on the ingest
  path — see :func:`surviving_dkim_alignment` for what that does and does not buy.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from email.message import Message
from email.utils import parseaddr

from app.core.logging import get_logger

logger = get_logger(__name__)

#: Sealers whose `ARC-Authentication-Results` we are willing to read. A CLOSED SET, and short on
#: purpose: an ARC seal is a claim by whoever sealed it, so "trusting the chain" is exactly
#: "trusting these domains". Google and Microsoft are here because Route B's supported providers are
#: Google Workspace and Microsoft 365 — the two consoles §3 renders steps for — and because a
#: forwarded message's first hop IS one of them by construction.
#:
#: ADDING ONE IS A SECURITY DECISION, not configuration. It is a constant rather than a setting so
#: that widening it is a code change with a reviewer, not an environment variable somebody sets at
#: three in the morning to make a customer's mail work.
TRUSTED_ARC_SEALERS: frozenset[str] = frozenset(
    {
        "google.com",
        "mx.google.com",
        "microsoft.com",
        "outlook.com",
        "protection.outlook.com",
    }
)

#: `method=result`, with the result taken up to the first space, semicolon or open bracket. RFC 8601
#: allows `dkim=pass (1024-bit key) header.d=example.com`, and a naive split on whitespace takes
#: "pass" correctly while a split on ";" takes "pass (1024-bit key) header.d=example.com".
_METHOD = re.compile(r"\b(?P<method>spf|dkim|dmarc|arc)\s*=\s*(?P<result>[A-Za-z]+)")

#: `header.d=` / `header.from=` — the domain a DKIM signature covers, and the domain DMARC aligned.
_PROPERTY = re.compile(r"\bheader\.(?P<name>[a-z]+)\s*=\s*(?P<value>[^\s;]+)")


@dataclass(frozen=True)
class OriginalHopVerdicts:
    """What the first hop said, and what we are prepared to believe of it.

    `spf` IS ABSENT BY CONSTRUCTION. There is no field for it, so nothing downstream can read one —
    which is stronger than parsing it and choosing not to use it, because the second is a choice a
    later edit can reverse without noticing.
    """

    #: The authserv-id that wrote the header we read — who is making these claims.
    authority: str | None
    dkim: str | None
    dmarc: str | None
    #: The domain a surviving `DKIM-Signature` covers, lowercased, or None.
    dkim_domain: str | None
    #: True when a `DKIM-Signature` survived the forward AND its `d=` aligns with `From:`.
    dkim_aligned: bool
    #: Where the verdicts came from, for the triage card and the ticket. Never a decision input.
    source: str

    @property
    def authenticated(self) -> bool:
        """Whether the original hop is evidence the sender is who they say.

        DMARC PASS **OR** AN ALIGNED SURVIVING DKIM SIGNATURE, and the disjunction is the point: a
        forward that preserved the body preserves the DKIM signature, which is checkable evidence
        that outlives the hop; a forward that rewrote the body breaks it, and then the first hop's
        DMARC verdict is all there is.

        `PASS` IS COMPARED FOR EQUALITY, so `none`, `neutral`, `temperror` and anything unrecognised
        fail closed — the same rule §2.3 states for SES's `GRAY`.
        """
        return (self.dmarc or "").lower() == "pass" or self.dkim_aligned


def _from_domain(parsed: Message) -> str | None:
    """The domain in `From:`, lowercased. None when there is no usable address."""
    _name, address = parseaddr(parsed.get("From") or "")
    _local, separator, domain = address.partition("@")
    return domain.strip().lower() if separator and domain.strip() else None


def _parse_results(value: str) -> tuple[str | None, dict[str, str], dict[str, str]]:
    """One `Authentication-Results`-shaped header → (authserv-id, methods, properties).

    Tolerant on purpose. This header is written by other people's software and arrives folded,
    re-wrapped and with comments in it; a strict parser here fails on a real message from a real
    tenant, which routes a borrower's documents to triage for a reason nobody can see.
    """
    # THE INSTANCE NUMBER COMES FIRST ON AN ARC HEADER. RFC 8617 §4.1.1:
    # `ARC-Authentication-Results: i=1; authserv-id; ...` — so taking the first segment as the
    # authority reads "i=1", which is in no allowlist, and EVERY ARC chain is then refused. That
    # refusal looks exactly like a working allowlist from the outside: the "a stranger's seal is
    # ignored" test passes, and so would one asserting that Google's is read, if the control had not
    # been written. Skipped explicitly rather than by index, so a header without it still parses.
    segments = [segment.strip() for segment in value.split(";") if segment.strip()]
    head = next(
        (
            segment
            for segment in segments
            if not re.fullmatch(r"i\s*=\s*\d+", segment, flags=re.IGNORECASE)
        ),
        "",
    )
    authority = head.split()[0].lower() if head else None
    methods = {
        match.group("method").lower(): match.group("result").lower()
        for match in _METHOD.finditer(value)
    }
    properties = {
        match.group("name").lower(): match.group("value").strip().lower()
        for match in _PROPERTY.finditer(value)
    }
    return authority, methods, properties


def surviving_dkim_alignment(parsed: Message) -> tuple[str | None, bool]:
    """`(d= domain, aligned with From:)` for a `DKIM-Signature` that survived the forward.

    ALIGNMENT, NOT VERIFICATION, and the difference matters enough to state twice. This reads the
    `d=` tag off the signature header and compares it to the `From:` domain. It does NOT check the
    cryptography — that needs the signing key from DNS, which is a network call on the ingest path
    and a lookup an attacker chooses the timing of.

    So what this buys is narrow and real: a message whose `From:` is `borrower@gmail.com` and whose
    only surviving signature is `d=attacker.example` is NOT aligned, and that is a signal. A message
    that IS aligned has a signature somebody with the domain's key could have made — which the first
    hop already verified, and which is why this is used as corroboration of that hop's verdict rather
    than as evidence on its own.

    Relaxed alignment (RFC 7489 §3.1.1): an organisational-domain match counts, so `d=mail.acme.com`
    aligns with `From: jane@acme.com`. Strict alignment would refuse a great deal of legitimate mail.
    """
    signature = parsed.get("DKIM-Signature")
    if not signature:
        return None, False
    found = re.search(r"\bd\s*=\s*([^;\s]+)", signature)
    if not found:
        return None, False
    domain = found.group(1).strip().lower().rstrip(".")
    sender = _from_domain(parsed)
    if sender is None:
        return domain, False
    aligned = domain == sender or sender.endswith(f".{domain}") or domain.endswith(f".{sender}")
    return domain, aligned


def evaluate_original_hop(parsed: Message) -> OriginalHopVerdicts:
    """What the message's first hop concluded, from the evidence we are willing to read.

    THE ORDER IS THE ARGUMENT, and each step is weaker than the one before:

    1. The **first** `Authentication-Results` header. RFC 8601 §5: headers are prepended, so the
       first is the most recent — the forwarder's own, added after they authenticated the message
       and before they handed it to us. Every later one was already in the message when they
       received it, which is to say a stranger could have written it.
    2. An `ARC-Authentication-Results` from an **allowlisted** sealer. Only reached when there is no
       usable `Authentication-Results`, and only from a domain in :data:`TRUSTED_ARC_SEALERS` —
       otherwise "walking the chain" is reading a claim by whoever forged it.
    3. A surviving `DKIM-Signature`, always read, because it is the one piece of evidence that is
       checkable rather than asserted.

    `spf` is not read at any step. See the module docstring.
    """
    dkim_domain, dkim_aligned = surviving_dkim_alignment(parsed)

    for raw in parsed.get_all("Authentication-Results") or []:
        authority, methods, _properties = _parse_results(str(raw))
        if not methods:
            continue
        # RETURNS ON THE FIRST that carries any verdict. The loop exists to skip a leading header
        # that parsed to nothing, NOT to search for a better answer further down — searching down
        # the list is exactly how a forged header gets read.
        return OriginalHopVerdicts(
            authority=authority,
            dkim=methods.get("dkim"),
            dmarc=methods.get("dmarc"),
            dkim_domain=dkim_domain,
            dkim_aligned=dkim_aligned,
            source="authentication_results",
        )

    for raw in parsed.get_all("ARC-Authentication-Results") or []:
        authority, methods, _properties = _parse_results(str(raw))
        if authority is None or authority not in TRUSTED_ARC_SEALERS:
            # METADATA ONLY. The authority is a domain, not message content, and knowing which
            # sealer was refused is the difference between "add it" and "somebody is spoofing".
            logger.info("arc_sealer_not_trusted", authority=authority)
            continue
        if not methods:
            continue
        return OriginalHopVerdicts(
            authority=authority,
            dkim=methods.get("dkim"),
            dmarc=methods.get("dmarc"),
            dkim_domain=dkim_domain,
            dkim_aligned=dkim_aligned,
            source="arc",
        )

    return OriginalHopVerdicts(
        authority=None,
        dkim=None,
        dmarc=None,
        dkim_domain=dkim_domain,
        dkim_aligned=dkim_aligned,
        source="dkim_only" if dkim_domain else "none",
    )


def as_auth_verdicts(verdicts: OriginalHopVerdicts) -> dict[str, str]:
    """The original hop's findings, in the shape `InboundMessage.auth_verdicts` already holds.

    NAMED DIFFERENTLY FROM SES'S KEYS, deliberately. SES writes `dmarcVerdict`; this writes
    `originalHopDmarc`. A forwarded message's own SES verdicts are still recorded and are still what
    `decide_disposition` reads — and if these overwrote them, a `PASS` earned by the FORWARDER would
    be read as a pass earned by the borrower, which is the whole failure this module exists to avoid.
    """
    recorded: dict[str, str] = {"originalHopSource": verdicts.source}
    if verdicts.authority:
        recorded["originalHopAuthority"] = verdicts.authority
    if verdicts.dmarc:
        recorded["originalHopDmarc"] = verdicts.dmarc.upper()
    if verdicts.dkim:
        recorded["originalHopDkim"] = verdicts.dkim.upper()
    if verdicts.dkim_domain:
        recorded["originalHopDkimDomain"] = verdicts.dkim_domain
    recorded["originalHopDkimAligned"] = "PASS" if verdicts.dkim_aligned else "FAIL"
    recorded["originalHopAuthenticated"] = "PASS" if verdicts.authenticated else "FAIL"
    return recorded


__all__ = [
    "TRUSTED_ARC_SEALERS",
    "OriginalHopVerdicts",
    "as_auth_verdicts",
    "evaluate_original_hop",
    "surviving_dkim_alignment",
]
