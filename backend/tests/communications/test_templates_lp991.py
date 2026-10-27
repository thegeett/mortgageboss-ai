"""LP-991 — the address phrase renders whole or not at all.

Exact text, both ways, for each of the three templates that carried `$inbox_address`. A company with
no active mail domain must get a clean sentence: no "None", no "send them to .", no double spaces.
The old versions are pinned by hash in `test_templates_lp817.py`
(`test_every_pinned_version_still_resolves_to_the_words_it_names`).
"""

from __future__ import annotations

import pytest
from app.communications.templates import (
    SECURITY_NOTICE,
    TEMPLATES,
    VERSION_FINGERPRINTS,
    TemplateKey,
    file_address_phrase,
    render,
)

_ADDRESS = "lf-y36e@mb-mail.localhost"

_COMMON = {
    "borrower_first_name": "Akash",
    "processor_name": "Priya",
    "loan_reference": "LF-Y36E",
}

_INITIAL = _COMMON | {
    "document_list": "- Bank statements",
    "opening": "We are working through your file.",
    "bridge": "Here is what we still need:",
    "closing": "Ask us if anything is unclear.",
    "secure_upload_block": SECURITY_NOTICE,
}

_INITIAL_HEAD = (
    "Hello Akash,\n\nWe are working through your file.\n\nHere is what we still need:\n\n"
    "- Bank statements\n\n"
)
_INITIAL_TAIL = f"\n\nAsk us if anything is unclear.\n\n{SECURITY_NOTICE}\n\nPriya"

_SECURITY = (
    "Email is not a fully secure channel. If you would rather not send documents this way, reply "
    "and ask — we will send you a secure upload link instead."
)


def test_the_phrase_is_whole_or_empty() -> None:
    assert file_address_phrase(None) == ""
    assert file_address_phrase(None, reassure=True) == ""
    assert file_address_phrase(_ADDRESS) == f", or send them to {_ADDRESS}"


def test_the_initial_request_with_an_address() -> None:
    body = render(
        TemplateKey.INITIAL_DOCUMENTATION_REQUEST,
        _INITIAL | {"file_address_phrase": file_address_phrase(_ADDRESS, reassure=True)},
    ).body
    assert body == (
        _INITIAL_HEAD + "You can reply to this message with them attached, or send them to "
        "lf-y36e@mb-mail.localhost. Anything sent to that address reaches your loan file "
        "directly, so it does not get lost even when we are away from our desks." + _INITIAL_TAIL
    )


def test_the_initial_request_without_an_address() -> None:
    body = render(
        TemplateKey.INITIAL_DOCUMENTATION_REQUEST,
        _INITIAL | {"file_address_phrase": file_address_phrase(None, reassure=True)},
    ).body
    assert body == (
        _INITIAL_HEAD + "You can reply to this message with them attached." + _INITIAL_TAIL
    )


def _reminder(phrase: str) -> str:
    return render(
        TemplateKey.REMINDER_FOLLOW_UP,
        _COMMON | {"document_list": "- Bank statements", "file_address_phrase": phrase},
    ).body


def _reminder_expected(line: str) -> str:
    return (
        "Hello Akash,\n\nA short follow-up. We are still waiting on the following:\n\n"
        f"- Bank statements\n\n{line}\n\n{_SECURITY}\n\n"
        "If you have already sent any of these, tell us and we will go looking rather than asking "
        "you for it again.\n\nPriya"
    )


def test_the_reminder_with_and_without_an_address() -> None:
    assert _reminder(file_address_phrase(_ADDRESS)) == _reminder_expected(
        "You can reply with them attached, or send them to lf-y36e@mb-mail.localhost."
    )
    assert _reminder(file_address_phrase(None)) == _reminder_expected(
        "You can reply with them attached."
    )


def _condition(phrase: str) -> str:
    return render(
        TemplateKey.CONDITION_RESPONSE_REQUEST,
        _COMMON | {"condition_list": "- A letter of explanation", "file_address_phrase": phrase},
    ).body


def _condition_expected(line: str) -> str:
    return (
        "Hello Akash,\n\nThe underwriter has reviewed your file and asked for the following "
        "before your loan can move ahead:\n\n"
        f"- A letter of explanation\n\n{line}\n\n{_SECURITY}\n\n"
        "Conditions are a normal part of underwriting, and most files have them.\n\nPriya"
    )


def test_the_condition_request_with_and_without_an_address() -> None:
    assert _condition(file_address_phrase(_ADDRESS)) == _condition_expected(
        "You can reply with them attached, or send them to lf-y36e@mb-mail.localhost."
    )
    assert _condition(file_address_phrase(None)) == _condition_expected(
        "You can reply with them attached."
    )


@pytest.mark.parametrize(
    ("key", "current", "previous"),
    [
        (TemplateKey.INITIAL_DOCUMENTATION_REQUEST, "v5", "v4"),
        (TemplateKey.REMINDER_FOLLOW_UP, "v3", "v2"),
        (TemplateKey.CONDITION_RESPONSE_REQUEST, "v3", "v2"),
    ],
)
def test_the_code_points_at_the_new_versions_and_the_old_stay_pinned(
    key: TemplateKey, current: str, previous: str
) -> None:
    assert TEMPLATES[key].version == current
    assert "inbox_address" not in TEMPLATES[key].variables
    assert (key, current) in VERSION_FINGERPRINTS
    assert (key, previous) in VERSION_FINGERPRINTS
