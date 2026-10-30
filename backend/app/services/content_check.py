"""The pre-send content check (LP-996, `loan-email.md` §2 rule 5).

Runs on what a `transmit=True` Send will actually put on the wire: the final subject and body, after
`finalise_draft_body` and `build_outbound`. Deterministic, and only three grounds — a stated rate or
APR, approval or denial wording, and an account or routing number or wire instructions. The patterns
are the AI drafter's own (`ai/email_draft.send_check_grounds`), imported rather than restated.

A blocked Send is refused with every reason in plain words. The processor can send anyway by adding a
note; `send_draft` records the reasons and the note on the evidence row and the activity log.
"""

from __future__ import annotations

from app.ai.email_draft import send_check_grounds
from app.services.outbound_mime import html_to_text

#: The plain-words reason for each ground, in the order they are reported. One place: the API's
#: refusal and the activity log both read it.
CONTENT_CHECK_REASONS: dict[str, str] = {
    "rate": "Mentions an interest rate or APR",
    "commitment": "Uses approval or denial wording (for example approved, denied, cleared to close)",
    "payment_routing": "Contains an account or routing number, or wire instructions",
}

#: An override note shorter than this, after trimming, is refused.
OVERRIDE_NOTE_MIN_CHARS = 10


def content_check_grounds(subject: str, body: str, *, html: bool) -> list[str]:
    """The grounds the subject or body trips, in `CONTENT_CHECK_REASONS` order; empty when clean.

    An HTML body is read as text first, so a tag cannot split a word (`<b>appro</b>ved`). A link's
    hidden target is left out: the borrower reads its text, which is checked, not its address (a
    9-digit path segment is not a routing number she was sent). Subject and body are checked
    separately, so a match cannot be made across the join.
    """
    text = html_to_text(body, keep_link_targets=False) if html else body
    found = send_check_grounds(subject) | send_check_grounds(text)
    return [ground for ground in CONTENT_CHECK_REASONS if ground in found]


def reasons_for(grounds: list[str]) -> list[str]:
    return [CONTENT_CHECK_REASONS[ground] for ground in grounds]


def reason_items(grounds: list[str]) -> list[dict[str, str]]:
    """The API's `reasons`: each ground with its plain-words text."""
    return [
        {"ground": ground, "text": text}
        for ground, text in zip(grounds, reasons_for(grounds), strict=True)
    ]


__all__ = [
    "CONTENT_CHECK_REASONS",
    "OVERRIDE_NOTE_MIN_CHARS",
    "content_check_grounds",
    "reason_items",
    "reasons_for",
]
