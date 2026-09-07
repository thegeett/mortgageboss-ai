"""LP-804a — reading the files out of a message people actually send.

The plan names one trap and one hard case, and both are here as named tests over committed fixtures:

* **`Content-Disposition` is not how you find an attachment.** It is advisory and frequently absent,
  and a photo taken on a phone arrives `inline`. Filtering on `attachment` throws away the single
  most common thing a borrower sends.
* **`message/rfc822` must be recursed into.** Borrowers forward, and the real PDF is one or two
  forwards down. A parser that stops at the outer message finds an attachment that is itself an
  email and reports success.

The fixture for the second of those was WRONG in its first version — `attach()` inlined the forwarded
message instead of nesting it, so there was no `message/rfc822` part at all and the recursion test
would have passed without recursing. It is regenerated with `add_attachment()`, and
`test_the_forwarded_fixture_really_is_nested` now asserts the shape rather than trusting it.
"""

from __future__ import annotations

from email import policy
from email.parser import BytesParser
from pathlib import Path

import pytest
from app.services.inbound_mime import (
    MAX_NESTING_DEPTH,
    normalise_filename,
    parse_message,
)

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "eml"


def _eml(name: str) -> bytes:
    return (_FIXTURES / f"{name}.eml").read_bytes()


# --------------------------------------------------------------------------------------------- #
# The two the plan names
# --------------------------------------------------------------------------------------------- #
def test_an_inline_photo_with_no_disposition_is_found() -> None:
    """THE TRAP, as a test. A phone photo of a payslip arrives `inline` with no
    `Content-Disposition: attachment` anywhere — filtering on that header loses it silently, and the
    borrower is told their document never arrived."""
    parsed = parse_message(_eml("inline_photo_no_disposition"))

    assert len(parsed.attachments) == 1
    only = parsed.attachments[0]
    assert only.declared_content_type == "image/png"
    # No filename at all, which is why "has a filename" cannot be the sole rule either.
    assert only.filename_original is None


def test_the_forwarded_fixture_really_is_nested() -> None:
    """Asserts the FIXTURE, not the parser. The first version of this file used `attach()`, which
    inlines a message rather than wrapping it — so there was no `message/rfc822` part and the
    recursion test below passed without recursing. A fixture that does not contain what the test
    claims is worse than a missing test."""
    parsed = BytesParser(policy=policy.default).parsebytes(_eml("forwarded_nested_pdf"))
    types = [part.get_content_type() for part in parsed.walk()]
    assert "message/rfc822" in types


def test_a_forwarded_message_yields_the_nested_pdf() -> None:
    """The ticket's own "Done when". Depth 1 is the assertion that matters: at depth 0 the parser
    would be reporting the forwarded EMAIL as the attachment."""
    parsed = parse_message(_eml("forwarded_nested_pdf"))

    assert len(parsed.attachments) == 1
    pdf = parsed.attachments[0]
    assert pdf.filename_normalized == "statement.pdf"
    assert pdf.declared_content_type == "application/pdf"
    assert pdf.nesting_depth == 1
    assert pdf.content.startswith(b"%PDF")


def test_a_twice_forwarded_message_still_yields_it() -> None:
    """Two forwards is the ordinary shape once a thread has been passed around, and it is the case
    where a single level of recursion looks like it works."""
    parsed = parse_message(_eml("twice_forwarded_pdf"))

    assert len(parsed.attachments) == 1
    assert parsed.attachments[0].nesting_depth == 2


def test_a_plain_reply_with_no_attachments_yields_none() -> None:
    """The control. A parser that returned the body as an attachment would satisfy every test above
    and would file a borrower's sentence as a document."""
    assert parse_message(_eml("plain_reply")).attachments == ()


# --------------------------------------------------------------------------------------------- #
# Filenames, which are text a stranger wrote
# --------------------------------------------------------------------------------------------- #
def test_an_rfc_2231_filename_is_decoded() -> None:
    """Anything beyond a plain ASCII name is encoded on the wire, and `get_filename()` handles both
    RFC 2231 continuations and the RFC 2047 fallback — which is most of why this module needs no
    dependency."""
    parsed = parse_message(_eml("rfc2231_filename"))

    original = parsed.attachments[0].filename_original
    assert original is not None
    assert "August" in original
    assert "ä" in original  # decoded, not mangled into mojibake


def test_a_path_traversal_filename_cannot_escape() -> None:
    """`../../../etc/passwd.pdf` normalises to something inert. The original is KEPT, because it is
    what a processor would recognise and because destroying evidence of an attempt is worse than
    storing it — but nothing may build a path from either form."""
    parsed = parse_message(_eml("hostile_filename"))

    only = parsed.attachments[0]
    assert only.filename_original == "../../../etc/passwd.pdf"
    assert only.filename_normalized == "passwd.pdf"
    assert "/" not in (only.filename_normalized or "")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("statement.pdf", "statement.pdf"),
        (r"C:\Users\akash\statement.pdf", "statement.pdf"),
        # The whole directory component goes, not just the dots — `rsplit` on the separator
        # keeps the tail, so this is `passwd` rather than a flattened `etc_passwd`.
        ("../../etc/passwd", "passwd"),
        ("  .hidden.pdf  ", "hidden.pdf"),
        ("photo\u202egnp.exe", "photo_gnp.exe"),  # right-to-left override stripped
        ("", None),
        (None, None),
    ],
)
def test_filenames_are_normalised(raw: str | None, expected: str | None) -> None:
    """The RTL-override case is the one worth naming: `photo\\u202egnp.exe` RENDERS as `photo_exe.png`
    in most clients, which is a file that looks like an image and is not."""
    assert normalise_filename(raw) == expected


def test_a_very_long_filename_keeps_its_extension() -> None:
    """Truncating from the end would leave `aaaa…aaa` with no extension, and the extension is the
    part a person uses to tell what the file is."""
    result = normalise_filename("a" * 400 + ".pdf")
    assert result is not None
    assert result.endswith(".pdf")
    assert len(result) <= 200


# --------------------------------------------------------------------------------------------- #
# The same file, more than once
# --------------------------------------------------------------------------------------------- #
def test_the_same_bytes_under_three_names_are_one_attachment() -> None:
    """A forwarded thread carries `statement.pdf`, `statement (1).pdf` and `ATT00001.pdf` — one
    document. Deduplicated on content, because the filenames are exactly what differs."""
    parsed = parse_message(_eml("repeated_attachment"))

    assert len(parsed.attachments) == 1
    # The FIRST occurrence wins, so the shallowest copy — the one most likely to carry the sender's
    # own filename rather than a client-generated one — is what a processor sees.
    assert parsed.attachments[0].filename_normalized == "statement.pdf"


# --------------------------------------------------------------------------------------------- #
# The depth cap
# --------------------------------------------------------------------------------------------- #
def _nested_message(depth: int) -> bytes:
    from email.message import EmailMessage

    innermost = EmailMessage()
    innermost["Subject"] = "deep"
    innermost["From"] = "a@x"
    innermost["To"] = "b@x"
    innermost.set_content("body")
    innermost.add_attachment(
        b"%PDF-1.4 deep", maintype="application", subtype="pdf", filename="deep.pdf"
    )

    current = innermost
    for level in range(depth):
        wrapper = EmailMessage()
        wrapper["Subject"] = f"Fwd {level}"
        wrapper["From"] = "a@x"
        wrapper["To"] = "b@x"
        wrapper.set_content("fwd")
        wrapper.add_attachment(current)
        current = wrapper
    return current.as_bytes(policy=policy.default)


def test_nesting_past_the_cap_is_reported_not_silently_dropped() -> None:
    """A message whose parts were not fully enumerated must be DISTINGUISHABLE from one that had
    nothing deeper. Without the flag, a hostile sender hides a payload past the cap and the file
    looks clean — the cap turning from a defence into a blind spot."""
    parsed = parse_message(_nested_message(MAX_NESTING_DEPTH + 2))

    assert parsed.depth_limit_reached is True
    assert parsed.attachments == ()


def test_nesting_within_the_cap_is_not_reported() -> None:
    """The control. A flag that was always true would satisfy the test above and would make every
    ordinary forward look truncated."""
    parsed = parse_message(_nested_message(2))

    assert parsed.depth_limit_reached is False
    assert len(parsed.attachments) == 1


# --------------------------------------------------------------------------------------------- #
# The corpus is only a corpus if it looks like the wire (review finding)
# --------------------------------------------------------------------------------------------- #
def test_every_fixture_is_crlf_like_a_real_message() -> None:
    """Email is CRLF on the wire (RFC 5322), and SES stores the bytes it received.

    This asserts the PROPERTY rather than the pre-commit config that protects it, because the
    config is not the only thing that can undo it — an editor, a `sed -i`, or a future hook would
    all normalise these files just as silently. LP-804a found the whole corpus in LF, which meant
    the MIME parser was exercised only against a form no real message has; that gap happened not to
    be hiding a bug, and this is what stops the next one being discovered the same way.

    Three pre-commit hooks rewrite files and all three now exclude `.eml`: `mixed-line-ending` (the
    one LP-804a caught), plus `trailing-whitespace` and `end-of-file-fixer`, which this review
    added — measured stripping the space from `b=sig \\r\\n`, which DKIM's `simple` body
    canonicalisation preserves exactly.
    """
    fixtures = sorted(_FIXTURES.glob("*.eml"))
    assert fixtures, "no .eml fixtures found — this test would pass vacuously"

    offenders: list[str] = []
    for path in fixtures:
        raw = path.read_bytes()
        bare_lf = raw.replace(b"\r\n", b"")
        if b"\n" in bare_lf:
            offenders.append(path.name)

    assert not offenders, (
        "these fixtures contain a bare LF, so they are not in the line ending a real message "
        f"arrives in: {offenders}"
    )
