"""LP-993 — `build_mime`: headers, threading, body parts, and refusals.

Asserted on the BYTES that would go on the wire, parsed back, not on the `EmailMessage` object: what
the borrower's client reads is the serialised form, and quoting and encoding only exist there.
"""

from __future__ import annotations

from email import message_from_bytes, policy
from email.message import EmailMessage
from typing import Any

import pytest
from app.services.outbound_mime import build_mime, html_to_text

_BASE: dict[str, Any] = {
    "from_name": "Priya Thaker, ABC Mortgage",
    "from_address": "lf-y36e@mb-mail.abcmortgage.test",
    "to": "john.smith@example.test",
    "cc": "priya@abcmortgage.test",
    "reply_to": "lf-y36e@mb-mail.abcmortgage.test",
    "subject": "Documents for your loan",
    "body": "Hello John,\n\nPlease send your bank statements.\n\n[LF-Y36E]\n",
    "html": False,
}


def _wire(**overrides: Any) -> tuple[bytes, EmailMessage]:
    raw = build_mime(**(_BASE | overrides)).as_bytes()
    parsed = message_from_bytes(raw, policy=policy.default)
    assert isinstance(parsed, EmailMessage)
    return raw, parsed


def test_the_headers_a_borrower_sees() -> None:
    raw, msg = _wire()

    # The comma is inside quotes, so it is one display name and not two recipients.
    assert b'From: "Priya Thaker, ABC Mortgage" <lf-y36e@mb-mail.abcmortgage.test>' in raw
    assert msg["From"].addresses[0].display_name == "Priya Thaker, ABC Mortgage"
    assert msg["From"].addresses[0].addr_spec == "lf-y36e@mb-mail.abcmortgage.test"
    assert len(msg["From"].addresses) == 1
    assert msg["To"] == "john.smith@example.test"
    assert msg["Cc"] == "priya@abcmortgage.test"
    assert msg["Reply-To"] == "lf-y36e@mb-mail.abcmortgage.test"
    assert msg["Subject"] == "Documents for your loan"
    assert msg["Date"] is not None
    assert "Bcc" not in msg
    assert b"\r\nBcc:" not in raw and not raw.startswith(b"Bcc:")
    # Our own id, on the sending domain.
    assert msg["Message-ID"].startswith("<") and msg["Message-ID"].endswith(
        "@mb-mail.abcmortgage.test>"
    )
    # CRLF on the wire, as SMTP and SES expect.
    assert b"\r\n" in raw


def test_no_cc_and_no_reply_to_mean_no_header() -> None:
    _, msg = _wire(cc=None, reply_to=None)
    assert "Cc" not in msg
    assert "Reply-To" not in msg


def test_threading_headers_when_replying() -> None:
    _, msg = _wire(
        in_reply_to="<abc@mail.example.test>",
        references=["<root@mail.example.test>", "<abc@mail.example.test>"],
    )
    assert msg["In-Reply-To"] == "<abc@mail.example.test>"
    assert msg["References"] == "<root@mail.example.test> <abc@mail.example.test>"


def test_no_threading_headers_on_a_new_message() -> None:
    _, msg = _wire()
    assert "In-Reply-To" not in msg
    assert "References" not in msg


def test_a_plain_body_is_one_text_part() -> None:
    _, msg = _wire()
    assert not msg.is_multipart()
    assert msg.get_content_type() == "text/plain"
    assert msg.get_content_charset() == "utf-8"
    # CRLF on the wire; the words are the draft's.
    assert msg.get_content().replace("\r\n", "\n") == _BASE["body"]


def test_an_html_body_is_text_then_html() -> None:
    html = (
        "<p>Hello John,</p><p>Please send:</p><ul><li>Bank statements</li><li>Pay stubs</li></ul>"
        '<p><a href="https://app.example.test/u/tok">Upload securely</a></p><p>[LF-Y36E]</p>'
    )
    _, msg = _wire(body=html, html=True)

    assert msg.get_content_type() == "multipart/alternative"
    parts = list(msg.iter_parts())
    assert [p.get_content_type() for p in parts] == ["text/plain", "text/html"]
    text = parts[0].get_content().replace("\r\n", "\n")
    assert "<" not in text and ">" not in text
    assert text == (
        "Hello John,\n\nPlease send:\n\n- Bank statements\n- Pay stubs\n\n"
        "Upload securely (https://app.example.test/u/tok)\n\n[LF-Y36E]\n"
    )
    assert parts[1].get_content().strip() == html


def test_html_to_text_decodes_entities_and_breaks() -> None:
    # A non-breaking space reads as a space; script contents are dropped.
    assert html_to_text("<p>A &amp; B<br>C&nbsp;D</p><script>x()</script>") == "A & B\nC D\n"


def test_non_ascii_name_and_subject_are_encoded() -> None:
    raw, msg = _wire(from_name="José Núñez, Ñandú Mortgage", subject="Documentos — José Núñez")

    header_block = raw.split(b"\r\n\r\n", 1)[0]
    header_block.decode("ascii")  # encoded words only; raises if a raw é reached the headers
    assert msg["From"].addresses[0].display_name == "José Núñez, Ñandú Mortgage"
    assert msg["Subject"] == "Documentos — José Núñez"


@pytest.mark.parametrize(
    "overrides",
    [
        {"subject": "Hello\r\nBcc: attacker@example.test"},
        {"subject": "Hello\nX-Evil: 1"},
        {"from_name": "Priya\r\nBcc: attacker@example.test"},
        {"to": "john@example.test\r\nBcc: attacker@example.test"},
        {"reply_to": "lf-x@example.test\n"},
        {"in_reply_to": "<a@b>\r\nX: y"},
        {"headers": {"X-Auto": "yes\r\nBcc: attacker@example.test"}},
    ],
)
def test_a_line_break_in_a_header_is_refused(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="line break"):
        build_mime(**(_BASE | overrides))


@pytest.mark.parametrize("to", ["", [], ["  "]])
def test_no_recipient_is_refused(to: Any) -> None:
    with pytest.raises(ValueError, match="at least one To"):
        build_mime(**(_BASE | {"to": to}))


@pytest.mark.parametrize("from_address", ["lf-y36e", "@mb-mail.test", "lf-y36e@"])
def test_a_from_address_without_a_domain_is_refused(from_address: str) -> None:
    with pytest.raises(ValueError, match="from_address is not an email address"):
        build_mime(**(_BASE | {"from_address": from_address}))


@pytest.mark.parametrize("name", ["Bcc", "bcc", "From", "Message-ID", "X Bad"])
def test_headers_cannot_name_a_managed_header_or_a_bad_name(name: str) -> None:
    with pytest.raises(ValueError, match="sets"):
        build_mime(**(_BASE | {"headers": {name: "x"}}))


def test_extra_headers_for_automated_mail() -> None:
    _, msg = _wire(headers={"Auto-Submitted": "auto-generated"})
    assert msg["Auto-Submitted"] == "auto-generated"


def test_build_mime_has_no_attachment_parameter() -> None:
    """GLBA: outbound carries a link, never a document."""
    import inspect

    params = set(inspect.signature(build_mime).parameters)
    assert not {p for p in params if "attach" in p or "file" in p}
