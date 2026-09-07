"""Reading the parts out of an inbound message (LP-804a).

STDLIB ONLY, DELIBERATELY. `email` with `policy=default` and `BytesParser` handles RFC 2231 and
RFC 2047 correctly and is maintained alongside the language. The plan's `mail-parser` dependency
buys convenience over a module that is already correct, and the two abandoned alternatives it names
are why depending lightly here is worth something.

THREE THINGS THIS GETS RIGHT THAT A NAIVE WALK DOES NOT:

**Attachments are not identified by `Content-Disposition`.** It is a hint, it is frequently absent,
and a phone photo of a payslip arrives `inline`. Filtering on `attachment` loses exactly the case
borrowers send most. The rule here is *has a filename, or is not text* — which catches the inline
photo, the disposition-less scanner output, and the correctly-labelled attachment alike.

**`message/rfc822` is recursed into.** Borrowers forward. The real PDF is usually one or two
forwards down, and a parser that stops at the outer message finds an attachment that is itself an
email and calls the job done. Depth-capped at 5, because a message can nest arbitrarily and a
malicious one will.

**A filename is attacker-controlled text.** It is decoded, then normalised separately, and the
original is kept because it is what a processor will recognise. The normalised form is what anything
else may use; nothing here builds a path from either.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from email import policy
from email.message import MIMEPart
from email.parser import BytesParser

from app.core.logging import get_logger

logger = get_logger(__name__)

#: How far into nested `message/rfc822` wrappers to go. A forwarded-then-forwarded-again thread is
#: two or three; five is generous. A cap is not optional — nesting is unbounded in the format and a
#: hostile message will use it.
MAX_NESTING_DEPTH = 5

#: Longest filename kept after normalisation. Long enough for anything real, short enough that the
#: column and any future path built from it are bounded.
MAX_FILENAME_LENGTH = 200

#: Anything that is not a plain, safe filename character. Path separators are in here, which is the
#: point: `../../etc/passwd` and `C:\Windows\x` both normalise to something inert.
_UNSAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True)
class ParsedAttachment:
    """One part that looks like a file."""

    filename_original: str | None
    filename_normalized: str | None
    declared_content_type: str
    content: bytes
    sha256: str
    size_bytes: int
    nesting_depth: int


@dataclass(frozen=True)
class ParsedMessage:
    """What a raw message contains, for LP-804a's purposes."""

    attachments: tuple[ParsedAttachment, ...]
    #: True when the walk stopped because of :data:`MAX_NESTING_DEPTH`. Surfaced rather than
    #: swallowed: a message whose contents were not fully enumerated must not look like one that
    #: simply had nothing deeper.
    depth_limit_reached: bool


def normalise_filename(raw: str | None) -> str | None:
    """A filename safe to store and display, or None.

    NOT A ROUND TRIP. Information is lost on purpose — the original is kept beside it for anything a
    person reads. This form exists so nothing downstream has to reason about whether a name from a
    stranger's email can contain a path separator, a null byte, or a right-to-left override that
    makes `photo_gnp.exe` render as `photo_exe.png`.
    """
    if not raw:
        return None
    # Strip any directory component the sender supplied, both separators, before anything else.
    tail = raw.replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = _UNSAFE_FILENAME.sub("_", tail).strip("._")
    if not cleaned:
        return None
    if len(cleaned) > MAX_FILENAME_LENGTH:
        stem, _, extension = cleaned.rpartition(".")
        if stem and len(extension) <= 10:
            keep = MAX_FILENAME_LENGTH - len(extension) - 1
            cleaned = f"{stem[:keep]}.{extension}"
        else:
            cleaned = cleaned[:MAX_FILENAME_LENGTH]
    return cleaned


def _looks_like_a_file(part: MIMEPart) -> bool:
    """Whether this part is something a borrower attached.

    HAS A FILENAME, OR IS NOT TEXT. Never `Content-Disposition`, which the plan calls out and which
    is the trap: it is advisory, often missing, and a photo taken on a phone arrives `inline`. A
    filter on `attachment` throws away the most common thing borrowers actually send.

    `get_filename()` already handles RFC 2231 continuations and falls back to RFC 2047 encoded
    words, which is most of the reason this module is stdlib-only.
    """
    if part.get_filename():
        return True
    content_type = part.get_content_type()
    return not content_type.startswith("text/") and content_type != "multipart/alternative"


def _walk(part: MIMEPart, depth: int, out: list[ParsedAttachment]) -> bool:
    """Collect file-like parts. Returns True if the depth cap stopped the walk anywhere below."""
    truncated = False

    if part.get_content_type() == "message/rfc822":
        if depth >= MAX_NESTING_DEPTH:
            # NOT silently ignored. A message whose contents were not fully enumerated must be
            # distinguishable from one that had nothing deeper — otherwise a hostile sender hides a
            # payload by nesting past the cap and the file looks clean.
            logger.warning("inbound_mime_depth_limit", depth=depth)
            return True
        for nested in part.iter_parts():
            truncated |= _walk(nested, depth + 1, out)
        return truncated

    if part.is_multipart():
        for child in part.iter_parts():
            truncated |= _walk(child, depth, out)
        return truncated

    if not _looks_like_a_file(part):
        return truncated

    content = part.get_payload(decode=True)
    if not isinstance(content, bytes):
        return truncated

    original = part.get_filename()
    out.append(
        ParsedAttachment(
            filename_original=original,
            filename_normalized=normalise_filename(original),
            declared_content_type=part.get_content_type(),
            content=content,
            sha256=hashlib.sha256(content).hexdigest(),
            size_bytes=len(content),
            nesting_depth=depth,
        )
    )
    return truncated


def parse_message(raw: bytes) -> ParsedMessage:
    """Every file-like part in ``raw``, including inside forwarded messages.

    Deduplicated by sha256 within one message: a borrower forwarding a thread sends the same PDF
    under three names, and a processor should be offered it once. The FIRST occurrence wins, so the
    shallowest copy — the one most likely to carry the sender's own filename — is the one kept.
    """
    parsed = BytesParser(policy=policy.default).parsebytes(raw)
    collected: list[ParsedAttachment] = []
    truncated = _walk(parsed, 0, collected)

    seen: set[str] = set()
    unique: list[ParsedAttachment] = []
    for attachment in collected:
        if attachment.sha256 in seen:
            continue
        seen.add(attachment.sha256)
        unique.append(attachment)

    return ParsedMessage(attachments=tuple(unique), depth_limit_reached=truncated)


__all__ = [
    "MAX_NESTING_DEPTH",
    "ParsedAttachment",
    "ParsedMessage",
    "normalise_filename",
    "parse_message",
]
