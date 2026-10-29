"""The finished email, built from plain values (LP-993).

`build_mime` turns what LP-994 gathers (the approver, the company, the file address, the draft) into
the RFC 5322 message a transport sends: headers, threading, and a plain or plain+HTML body. It
touches no database and decides nothing about whether to send.

    From:     "Priya Thaker, ABC Mortgage" <lf-y36e@mb-mail.abcmortgage.com>
    To:       john.smith@gmail.com
    Cc:       priya@abcmortgage.com
    Reply-To: lf-y36e@mb-mail.abcmortgage.com

NO ATTACHMENTS, and no parameter for one: the GLBA rule on `OutboundEnvelope`
(`services/mail_transport.py`) — outbound carries a link, never a document.

NO BCC, EVER. A Bcc header in a raw message is a list of hidden recipients that some relays strip and
some do not; the borrower's copy must not be able to carry one.

HEADER INJECTION IS REFUSED, NOT CLEANED. Every value that becomes a header is checked for CR and LF
and the build raises `ValueError`. A subject or a display name comes from a person or a template; a
newline in one is either a bug or an attempt to add a header, and neither should leave quietly
"fixed".
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from email import policy
from email.headerregistry import Address
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid
from html.parser import HTMLParser

#: Headers `build_mime` sets itself, or must never be set. `headers=` may not name these.
_MANAGED = frozenset(
    {
        "from",
        "to",
        "cc",
        "bcc",
        "reply-to",
        "subject",
        "date",
        "message-id",
        "in-reply-to",
        "references",
        "mime-version",
        "content-type",
        "content-transfer-encoding",
    }
)


def build_mime(
    *,
    from_name: str,
    from_address: str,
    to: str | Sequence[str],
    cc: str | Sequence[str] | None = None,
    reply_to: str | None,
    subject: str,
    body: str,
    html: bool,
    in_reply_to: str | None = None,
    references: Sequence[str] | None = None,
    headers: Mapping[str, str] | None = None,
) -> EmailMessage:
    """The complete message. Raises `ValueError` on a header value with CR/LF, an empty `to`, an
    address without `@`, or a `headers` entry that names a header this function owns.

    `body` is the draft as stored: plain text, or the sanitised HTML an authored draft holds
    (`html=True`). An HTML body goes out as multipart/alternative with a plain-text part first.
    `reply_to` is the file address, or None when the file has none (LP-991).
    """
    recipients = _as_list(to)
    copies = _as_list(cc)
    if not recipients:
        raise ValueError("An email needs at least one To recipient.")
    extra = dict(headers or {})
    for name, value in extra.items():
        if name.strip().lower() in _MANAGED or not _is_header_name(name):
            raise ValueError(f"build_mime sets {name!r} itself, or it is not a header name.")
        _no_newline(name, value)

    _no_newline("from_name", from_name)
    _no_newline("subject", subject)
    for label, address in [
        ("from_address", from_address),
        *(("to", a) for a in recipients),
        *(("cc", a) for a in copies),
        *([("reply_to", reply_to)] if reply_to is not None else []),
    ]:
        _check_address(label, address)
    if in_reply_to is not None:
        _no_newline("in_reply_to", in_reply_to)
    for ref in references or []:
        _no_newline("references", ref)

    # SMTP policy: CRLF line endings and RFC-compliant folding, which is what goes on the wire, so
    # `as_bytes()` is the raw message SES and SMTP both take.
    message = EmailMessage(policy=policy.SMTP)
    # `Address` quotes a display name with a comma ("Priya Thaker, ABC Mortgage") and encodes a
    # non-ASCII one; formatting it by hand is how a comma becomes two recipients.
    message["From"] = Address(display_name=from_name, addr_spec=from_address)
    message["To"] = ", ".join(recipients)
    if copies:
        message["Cc"] = ", ".join(copies)
    if reply_to is not None:
        message["Reply-To"] = reply_to
    message["Subject"] = subject
    message["Date"] = format_datetime(datetime.now(UTC))
    # Our own id on the sending domain. SES may replace it with its own; LP-998 records which one
    # actually arrives, and threading of replies reads what arrived.
    message["Message-ID"] = make_msgid(domain=from_address.rsplit("@", 1)[1])
    if in_reply_to:
        message["In-Reply-To"] = in_reply_to
    if references:
        message["References"] = " ".join(references)
    for name, value in extra.items():
        message[name] = value

    if html:
        message.set_content(html_to_text(body), subtype="plain", charset="utf-8")
        message.add_alternative(body, subtype="html", charset="utf-8")
    else:
        message.set_content(body, subtype="plain", charset="utf-8")
    return message


def _as_list(value: str | Sequence[str] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    return [item for item in value if item.strip()]


def _no_newline(label: str, value: str) -> None:
    if "\r" in value or "\n" in value:
        raise ValueError(f"{label} contains a line break; refusing to build the header.")


def _check_address(label: str, address: str) -> None:
    _no_newline(label, address)
    if "@" not in address or address.startswith("@") or address.endswith("@"):
        raise ValueError(f"{label} is not an email address.")


def _is_header_name(name: str) -> bool:
    # RFC 5322 field name: printable ASCII except colon and space.
    return bool(name) and all(33 <= ord(ch) <= 126 and ch != ":" for ch in name)


class _PlainText(HTMLParser):
    """The text of an HTML body, with paragraphs, line breaks, bullets and link targets kept."""

    _BLOCK_END = frozenset({"p", "div", "blockquote", "ul", "ol", "tr", "h1", "h2", "h3"})
    _DROP = frozenset({"script", "style", "head", "title"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.muted = 0
        self.href: str | None = None
        self.link_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._DROP:
            self.muted += 1
        elif tag == "br":
            self.out.append("\n")
        elif tag == "li":
            self.out.append("\n- ")
        elif tag == "a":
            self.href = dict(attrs).get("href")
            self.link_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag in self._DROP:
            self.muted = max(self.muted - 1, 0)
        elif tag in self._BLOCK_END:
            self.out.append("\n\n")
        elif tag == "a":
            # A text-only reader cannot click, so the address goes in the text. The upload link is
            # the one a borrower needs, and its text alone ("Upload securely") is no use.
            text = "".join(self.link_text).strip()
            if self.href and self.href != text:
                self.out.append(f" ({self.href})")
            self.href = None

    def handle_data(self, data: str) -> None:
        if self.muted:
            return
        collapsed = " ".join(data.split())
        if data[:1].isspace() and collapsed:
            collapsed = " " + collapsed
        if data[-1:].isspace() and collapsed:
            collapsed += " "
        self.out.append(collapsed)
        if self.href is not None:
            self.link_text.append(data)


def html_to_text(html: str) -> str:
    """Readable plain text for the text/plain part of an HTML email.

    A FALLBACK FOR TEXT-ONLY READERS, not the message: almost every client shows the HTML part. It is
    not the plain text `mailto:` uses (`frontend/lib/markdown/from-html.ts`, which must round-trip
    back into the editor); this one only needs to be readable. See `communications/sanitise.py`.
    """
    parser = _PlainText()
    parser.feed(html)
    parser.close()
    lines = [" ".join(line.split()) for line in "".join(parser.out).split("\n")]
    text = "\n".join(lines)
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return text.strip() + "\n"


__all__ = ["build_mime", "html_to_text"]
