"""LP-808 — what a forwarded message's authentication is worth.

This is the one place in the codebase that reads `Authentication-Results` out of a message body,
which §2.3 otherwise forbids outright because RFC 8601's security section says a message can carry a
forged header claiming `dmarc=pass`. So every test here is really the same question asked five ways:
**can a stranger write a header that makes this say yes?**

The answers are all "only if they control an allowlisted sealer or the sender's DKIM key", and each
one is tested by writing the forged header rather than by asserting that a well-formed message
works.
"""

from __future__ import annotations

from email import message_from_string

import pytest
from app.services.original_hop import (
    TRUSTED_ARC_SEALERS,
    as_auth_verdicts,
    evaluate_original_hop,
    surviving_dkim_alignment,
)


def _message(headers: str, *, sender: str = "jane@borrower.example") -> object:
    return message_from_string(f"From: {sender}\n{headers}\nSubject: Docs\n\nbody\n")


# --------------------------------------------------------------------------------------------- #
# SPF is never read, in either direction
# --------------------------------------------------------------------------------------------- #
def test_an_spf_fail_on_a_forward_does_not_condemn_the_sender() -> None:
    """A FORWARDED MESSAGE ALWAYS FAILS SPF — the connecting IP is the forwarder's. That is a
    protocol property, not a misconfiguration, and treating it as evidence would send every
    correctly-forwarded borrower message to triage."""
    verdicts = evaluate_original_hop(
        _message("Authentication-Results: mx.google.com; spf=fail; dkim=pass; dmarc=pass")
    )

    assert verdicts.authenticated is True


def test_an_spf_pass_does_not_vouch_for_the_sender() -> None:
    """The other direction, which is the one that could be exploited. On a forward, `spf=pass` says
    the FORWARDER is who they claim — which we already knew — and says nothing about the borrower."""
    verdicts = evaluate_original_hop(
        _message("Authentication-Results: mx.google.com; spf=pass; dkim=fail; dmarc=fail")
    )

    assert verdicts.authenticated is False


def test_there_is_no_field_an_spf_result_could_be_read_from() -> None:
    """STRONGER THAN NOT USING IT. A parsed-but-ignored value is a choice a later edit reverses
    without noticing; an absent field is a type error."""
    from dataclasses import fields

    from app.services.original_hop import OriginalHopVerdicts

    assert "spf" not in {field.name for field in fields(OriginalHopVerdicts)}


# --------------------------------------------------------------------------------------------- #
# Only the first Authentication-Results is read
# --------------------------------------------------------------------------------------------- #
def test_a_forged_header_below_the_forwarders_is_not_read() -> None:
    """THE ATTACK THIS MODULE EXISTS FOR. RFC 8601 §5: headers are prepended, so the FIRST is the
    most recent — the forwarder's own, added after they authenticated the message. Anything below it
    was in the message when they received it, which is to say a stranger put it there.

    Here the attacker's `dmarc=pass` sits second and the forwarder's real `dmarc=fail` sits first.
    """
    verdicts = evaluate_original_hop(
        _message(
            "Authentication-Results: mx.google.com; dkim=fail; dmarc=fail\n"
            "Authentication-Results: totally.legit; dkim=pass; dmarc=pass"
        )
    )

    assert verdicts.authority == "mx.google.com"
    assert verdicts.dmarc == "fail"
    assert verdicts.authenticated is False


def test_the_first_header_is_read_when_it_is_the_good_one() -> None:
    """THE CONTROL. Without it, the test above passes against a parser that reads nothing at all."""
    verdicts = evaluate_original_hop(
        _message(
            "Authentication-Results: mx.google.com; dkim=pass; dmarc=pass\n"
            "Authentication-Results: older.hop; dkim=fail; dmarc=fail"
        )
    )

    assert verdicts.authority == "mx.google.com"
    assert verdicts.authenticated is True


# --------------------------------------------------------------------------------------------- #
# ARC, and the allowlist that decides what a seal is worth
# --------------------------------------------------------------------------------------------- #
def test_an_arc_chain_from_a_stranger_is_ignored() -> None:
    """ "Walking the chain" without an allowlist is reading a claim by whoever wrote it. An ARC seal
    is self-asserted: anybody can add `ARC-Authentication-Results` saying they checked."""
    verdicts = evaluate_original_hop(
        _message("ARC-Authentication-Results: i=1; attacker.example; dkim=pass; dmarc=pass")
    )

    assert verdicts.authenticated is False
    assert verdicts.source in {"none", "dkim_only"}


def test_an_arc_chain_from_an_allowlisted_sealer_is_read() -> None:
    """THE CONTROL for the test above — otherwise it passes against code that ignores ARC entirely.

    It asserts the chain is READ, which is what it is for: `source`, `authority` and the parsed
    verdicts all come from the ARC header. It used to assert `authenticated is True` as well, and
    that stopped being right when the review narrowed ARC to its checkable half — an allowlist
    matches a CLAIMED authserv-id and no seal is verified. See
    `test_a_forged_arc_header_alone_does_not_authenticate`; the assertion moved rather than went.
    """
    verdicts = evaluate_original_hop(
        _message("ARC-Authentication-Results: i=1; mx.google.com; dkim=pass; dmarc=pass")
    )

    assert verdicts.source == "arc"
    assert verdicts.authority == "mx.google.com"
    assert verdicts.dmarc == "pass"
    assert verdicts.dkim == "pass"


def test_arc_is_only_reached_when_there_is_no_authentication_results() -> None:
    """A forwarder's own header outranks a seal, even an allowlisted one: it is about THIS hop."""
    verdicts = evaluate_original_hop(
        _message(
            "Authentication-Results: protection.outlook.com; dkim=fail; dmarc=fail\n"
            "ARC-Authentication-Results: i=1; mx.google.com; dkim=pass; dmarc=pass"
        )
    )

    assert verdicts.source == "authentication_results"
    assert verdicts.authenticated is False


def test_the_allowlist_holds_only_the_two_providers_route_b_supports() -> None:
    """A CLOSED SET, and widening it is a security decision rather than configuration.

    §3 renders steps for Google Workspace and Microsoft 365 only, and a forwarded message's first
    hop is one of them by construction. A sealer nobody vouches for is a stranger writing "I
    checked, it's fine".
    """
    assert all(
        domain.endswith(("google.com", "microsoft.com", "outlook.com"))
        for domain in TRUSTED_ARC_SEALERS
    )


# --------------------------------------------------------------------------------------------- #
# Surviving DKIM — the one checkable signal
# --------------------------------------------------------------------------------------------- #
def test_a_signature_from_another_domain_is_not_aligned() -> None:
    """`From: jane@borrower.example` signed only by `d=attacker.example` is the spoofing shape."""
    domain, aligned = surviving_dkim_alignment(
        _message("DKIM-Signature: v=1; a=rsa-sha256; d=attacker.example; s=sel; b=xx")
    )

    assert domain == "attacker.example"
    assert aligned is False


def test_a_subdomain_signature_is_aligned() -> None:
    """RFC 7489 §3.1.1 relaxed alignment. Strict would refuse a great deal of legitimate mail —
    `d=mail.acme.com` signing `From: jane@acme.com` is the ordinary configuration."""
    _domain, aligned = surviving_dkim_alignment(
        _message(
            "DKIM-Signature: v=1; d=mail.borrower.example; s=sel; b=xx",
            sender="jane@borrower.example",
        )
    )

    assert aligned is True


def test_an_aligned_signature_authenticates_without_a_dmarc_pass() -> None:
    """THE DISJUNCTION IS THE POINT. A forward that preserved the body preserves the signature, which
    is checkable evidence that outlives the hop; a forward that rewrote it breaks the signature, and
    then the hop's own DMARC verdict is all there is."""
    verdicts = evaluate_original_hop(
        _message("DKIM-Signature: v=1; d=borrower.example; s=sel; b=xx")
    )

    assert verdicts.dmarc is None
    assert verdicts.dkim_aligned is True
    assert verdicts.authenticated is True


# --------------------------------------------------------------------------------------------- #
# Failing closed
# --------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("result", ["none", "neutral", "temperror", "permerror", "bestguesspass"])
def test_anything_that_is_not_pass_fails_closed(result: str) -> None:
    """Compared for EQUALITY with pass, the rule §2.3 states for SES's `GRAY`. `bestguesspass` is in
    the list because it is a real value some resolvers emit and it is exactly the shape that a
    `startswith("pass")` or a `!= "fail"` would wave through."""
    verdicts = evaluate_original_hop(
        _message(f"Authentication-Results: mx.google.com; dkim=fail; dmarc={result}")
    )

    assert verdicts.authenticated is False


def test_a_message_with_no_headers_at_all_authenticates_nothing() -> None:
    verdicts = evaluate_original_hop(_message("X-Nothing: here"))

    assert verdicts.authenticated is False
    assert verdicts.source == "none"


def test_a_comment_in_the_result_does_not_swallow_the_verdict() -> None:
    """RFC 8601 allows `dkim=pass (1024-bit key) header.d=example.com`. A parser splitting on `;`
    reads the result as everything up to the semicolon."""
    verdicts = evaluate_original_hop(
        _message(
            "Authentication-Results: mx.google.com; "
            "dkim=pass (1024-bit key) header.d=borrower.example; dmarc=pass header.from=x"
        )
    )

    assert verdicts.dkim == "pass"
    assert verdicts.dmarc == "pass"


# --------------------------------------------------------------------------------------------- #
# What gets recorded
# --------------------------------------------------------------------------------------------- #
def test_the_recorded_keys_never_collide_with_ses_verdicts() -> None:
    """SES's `dmarcVerdict` for a forwarded message is about the FORWARDER. If these overwrote it, a
    pass earned by Google would be read as a pass earned by the borrower — the exact confusion this
    module exists to prevent."""
    recorded = as_auth_verdicts(
        evaluate_original_hop(_message("Authentication-Results: mx.google.com; dmarc=pass"))
    )

    assert all(key.startswith("originalHop") for key in recorded)
    assert "dmarcVerdict" not in recorded
    assert recorded["originalHopAuthenticated"] == "PASS"


# --------------------------------------------------------------------------------------------- #
# The allowlist matches a CLAIM, not a seal (review finding)
# --------------------------------------------------------------------------------------------- #
def test_a_forged_arc_header_alone_does_not_authenticate() -> None:
    """`TRUSTED_ARC_SEALERS` matches the authserv-id a header CLAIMS. No `ARC-Seal` signature is
    verified, so nothing establishes the named sealer sealed anything — anyone can type the name.

    Measured before the fix: this exact message produced `authenticated=True` with
    `dkim_aligned=False`. `authenticated` was `dmarc == pass OR dkim_aligned`, so a `dmarc=pass` an
    attacker wrote satisfied it outright — and DMARC is the control that stops a spoofed `From:`,
    which `is_trusted_sender` then matches on, and `_sender_authenticated` gates auto-accept.
    """
    forged = message_from_string(
        "From: someone@borrower-domain.com\r\n"
        "Subject: documents\r\n"
        "ARC-Authentication-Results: i=1; google.com; dmarc=pass; dkim=pass\r\n"
        "\r\nbody\r\n"
    )

    verdicts = evaluate_original_hop(forged)

    assert verdicts.source == "arc"
    assert verdicts.authority == "google.com"  # the allowlist did match the claim
    assert verdicts.dmarc == "pass"  # and the claim says pass
    assert verdicts.dkim_aligned is False  # but nothing checkable backs it
    assert verdicts.authenticated is False


def test_an_arc_chain_with_an_aligned_signature_does_authenticate() -> None:
    """The control, and the reason this is a narrowing rather than a removal.

    Collapsing ARC to `False` unconditionally would satisfy the test above while making every
    genuinely forwarded message look unauthenticated — silence that reads as a working defence. The
    half a forger cannot write is an aligned surviving signature: it needs the `From:` domain's key.
    """
    genuine = message_from_string(
        "From: someone@borrower-domain.com\r\n"
        "Subject: documents\r\n"
        "ARC-Authentication-Results: i=1; google.com; dmarc=pass\r\n"
        "DKIM-Signature: v=1; d=borrower-domain.com; b=abc\r\n"
        "\r\nbody\r\n"
    )

    verdicts = evaluate_original_hop(genuine)

    assert verdicts.source == "arc"
    assert verdicts.dkim_aligned is True
    assert verdicts.authenticated is True


def test_a_real_authentication_results_still_authenticates_on_dmarc_alone() -> None:
    """The second control: the narrowing must apply ONLY to ARC.

    A forwarder's own `Authentication-Results` is added by the party that received the message, not
    by the sender, so `dmarc=pass` there is an assertion by somebody in a position to check. That
    disjunction stays.
    """
    forwarded = message_from_string(
        "From: someone@borrower-domain.com\r\n"
        "Subject: documents\r\n"
        "Authentication-Results: mx.google.com; dmarc=pass\r\n"
        "\r\nbody\r\n"
    )

    verdicts = evaluate_original_hop(forwarded)

    assert verdicts.source == "authentication_results"
    assert verdicts.dkim_aligned is False
    assert verdicts.authenticated is True
