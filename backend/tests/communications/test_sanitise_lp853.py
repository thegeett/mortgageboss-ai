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

#: THE CORPUS. One list, so a payload added for one property is checked by all of them — including
#: the idempotence property below, which would otherwise be a hand-picked four.
HOSTILE = [
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
]

#: What a processor legitimately writes. Kept beside the hostile payloads because the properties
#: below have to hold over both: a sanitiser that ate the message would satisfy every "not in".
BENIGN = [
    "<p>Hello <strong>Akash</strong>,</p>",
    "<ul><li>Bank statement<ul><li>Where to get it: your bank</li></ul></li><li>Pay stub</li></ul>",
    "<p>a<br>b</p>",
    "<p>5 &lt; 6 &amp; 7 &gt; 2</p>",
    "<p>&amp;lt;</p>",
    "<p>caf\u00e9 &#233; &#x69;</p>",
    "<p>unclosed <strong>bold",
    "<ul><li>a<li>b</ul>",
    "<div>kept text</div>",
    "<p>March statement only, not February.</p>",
    # LP-854 — the seven marks. The idempotence property below is what `was_edited` now depends on,
    # and seven new marks is exactly the change that could break it, so they join the corpus every
    # property in this file runs over rather than getting a test of their own.
    "<p><em>italic</em> and <u>underline</u></p>",
    "<ol><li>one</li><li>two</li></ol>",
    "<blockquote><p>Their own sentence, quoted back.</p></blockquote>",
    '<p>See <a href="https://example.com/docs">the guidance</a>.</p>',
    '<p><a href="mailto:closings@acmetitle.example">Email the closer</a></p>',
    "<ul><li>Bank statement<ol><li>March</li><li>April</li></ol></li></ul>",
]


@pytest.mark.parametrize("payload", HOSTILE)
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


@pytest.mark.parametrize(
    "payload",
    [
        "<p><em>italic</em></p>",
        "<p><u>underline</u></p>",
        "<ol><li>one</li></ol>",
        "<blockquote>quoted</blockquote>",
        '<p><a href="https://example.com">link</a></p>',
        "<ul><li>a<ul><li>b</li></ul></li></ul>",
    ],
)
def test_each_new_mark_survives(payload: str) -> None:
    """LP-854 ACCEPTANCE 1, the server's half — the stored HTML keeps the mark.

    A mark the editor can produce and this strips is formatting that vanishes on save, which is the
    failure LP-849's notes record. Asserted per mark rather than over one payload containing all of
    them, so a single stripped tag names itself.
    """
    assert sanitise_html(payload) == payload


@pytest.mark.parametrize(
    "href",
    [
        "https://example.com/docs",
        "http://example.com",
        "mailto:closings@acmetitle.example",
    ],
)
def test_a_safe_link_keeps_its_href(href: str) -> None:
    assert f'href="{href}"' in sanitise_html(f'<a href="{href}">text</a>')


@pytest.mark.parametrize(
    "href",
    ["javascript:alert(1)", "data:text/html,<script>x</script>", "/relative", "#anchor"],
)
def test_a_refused_link_loses_the_TAG_not_just_the_href(href: str) -> None:
    """AN ANCHOR WITH NO href IS NOT A LINK, AND IS NOT EMITTED AS ONE.

    The first version kept the tag and dropped the attribute, leaving `<a>click</a>`: something that
    looks like a link, is styled like one in every mail client, and goes nowhere. The processor's
    TEXT survives — their words are not ours to delete — and the thing that was refused is visibly
    absent rather than silently inert.
    """
    out = sanitise_html(f'<a href="{href}">click here</a>')
    assert "<a" not in out
    assert "click here" in out


def test_no_other_attribute_survives_on_a_link() -> None:
    """`href` is the only one. `target`, `rel`, `class` and `style` are not allowlisted, and the
    output has to survive Word's engine, which discards most of what it does not recognise."""
    out = sanitise_html(
        '<a href="https://example.com" target="_blank" rel="noopener" '
        'class="x" style="color:red" onclick="steal()">text</a>'
    )
    assert out == '<a href="https://example.com">text</a>'


def test_the_allowlist_is_exactly_the_editor_schema() -> None:
    """LP-854 EXTENDS THIS AND THE TIPTAP EXTENSIONS TOGETHER, OR FORMATTING VANISHES ON SAVE.

    LP-849's own notes record exactly that: `htmlToEmailBody` stripped `**` from any `<strong>`
    ending in a colon while the renderer re-bolded only a capitalised run of 3-41 characters, and
    everything in the gap lost its asterisks. Three lists, two of them drifted.

    Pinned as a literal so that widening it is a decision somebody makes on purpose. A tag the
    editor can produce and this cannot store is formatting a processor watches disappear; a tag this
    stores and the editor cannot produce is a hole nothing else is watching.
    """
    assert set(ALLOWED) == {
        # LP-849
        "p",
        "br",
        "strong",
        "ul",
        "li",
        # LP-854
        "em",
        "u",
        "ol",
        "blockquote",
        "a",
    }
    # ONE TAG HAS AN ATTRIBUTE, and it is the one with a security dimension. Anything else gaining
    # one is a decision somebody has to make here, on purpose.
    assert {tag: set(attributes) for tag, attributes in ALLOWED.items() if attributes} == {
        "a": {"href"}
    }


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


@pytest.mark.parametrize("payload", HOSTILE + BENIGN)
def test_sanitising_twice_changes_nothing(payload: str) -> None:
    """IDEMPOTENCE, AND IT IS LOAD-BEARING RATHER THAN TIDY (LP-853 review, second round).

    The obvious reason: a draft is saved repeatedly as a processor types, and a sanitiser that
    escaped its own output would turn a bold word into `&lt;strong&gt;` on the second save.

    THE LOAD-BEARING REASON IS THE EVIDENCE RECORD. `body_as_sent` is `communication.body`, which
    the send now sanitises; `body_composed` is assembled from the stored body and does NOT pass
    through here. So `EvidencePublic.was_edited` — "did the processor change the drafted words" —
    is false only while `sanitise_html(sanitise_html(x)) == sanitise_html(x)`. The day a tag with
    attributes joins `ALLOWED` and the serialiser reorders or re-escapes anything, every authored
    send records as edited, and it will read as a fourth instance of the same false-edit bug rather
    than as a sanitiser change.

    OVER THE WHOLE CORPUS, not a hand-picked few: the two lists above are what every other property
    in this file is checked against, so a payload added for one reason is checked for this too.
    """
    once = sanitise_html(payload)
    assert sanitise_html(once) == once


def test_an_invisible_inside_the_scheme_is_not_cleaned_into_a_safe_one() -> None:
    """LP-854 REVIEW — `href_is_safe` answered about a string the browser never sees.

    It stripped everything not `isprintable()` or that `isspace()`, which is far wider than the URL
    parser's rule. Over-stripping cannot let a dangerous scheme through — deleting characters from
    `javascript:` still spells `javascript` — but it did the opposite: `h​ttp://x.com` cleaned
    to `http`, passed, and was STORED with the zero-width space intact. No browser resolves that as
    http, so the borrower received a link to nowhere that this function had called safe.

    WHATWG strips leading/trailing C0 and space, and tab/CR/LF anywhere. Nothing else.
    """
    for href in ("h​ttp://x.com", "ht﻿tp://x.com", "h\xa0ttp://x.com"):
        assert href_is_safe(href) is False, f"{href!r} was accepted as a safe scheme"
        assert "<a" not in sanitise_html(f'<a href="{href}">click</a>')

    # THE POSITIVE CONTROL, and it is the reason the strip exists at all: the characters a browser
    # DOES remove must still be removed, or `java<TAB>script:` stops being refused.
    assert href_is_safe("java\tscript:alert(1)") is False
    assert href_is_safe("java\nscript:alert(1)") is False
    assert href_is_safe("\x00javascript:alert(1)") is False
    assert href_is_safe("  javascript:alert(1)  ") is False
    # And an ordinary link is untouched by all of it.
    assert href_is_safe("https://example.com/path?q=1") is True


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        # Markup INSIDE a refused anchor is the processor's too, and survives with it.
        (
            '<p><a href="javascript:x"><strong>bold</strong> tail</a></p>',
            "<p><strong>bold</strong> tail</p>",
        ),
        # Dropping one must not disturb the next, in either order.
        (
            '<p><a href="javascript:x">bad</a> and <a href="https://ok.com">good</a></p>',
            '<p>bad and <a href="https://ok.com">good</a></p>',
        ),
        (
            '<p><a href="https://ok.com">good</a> and <a href="javascript:x">bad</a></p>',
            '<p><a href="https://ok.com">good</a> and bad</p>',
        ),
        # No closing tag at all — the refused anchor was never opened, so nothing is left dangling.
        ('<p><a href="javascript:x">text', "<p>text</p>"),
        # Nested anchors are not something the editor can produce, and a paste can.
        (
            '<p><a href="javascript:x">out <a href="https://ok.com">in</a></a></p>',
            '<p>out <a href="https://ok.com">in</a></p>',
        ),
        # Nothing between the tags: no stray empty element, and the text either side is intact.
        ('<p>before<a href="javascript:x"></a>after</p>', "<p>beforeafter</p>"),
    ],
)
def test_dropping_a_refused_link_neither_duplicates_nor_loses_its_text(
    source: str, expected: str
) -> None:
    """LP-854 REVIEW — the anchor is dropped and its CONTENTS are not.

    `handle_starttag` returns early for an `<a>` whose href did not survive, so the element is never
    pushed onto the open stack — which is what keeps the matching `</a>` from closing something it
    did not open, and what keeps `handle_endtag`'s unwinding loop from popping past it. These are
    the shapes where that could go wrong: nested markup, an adjacent link in either order, no
    closing tag, a nested anchor, and an empty one.
    """
    assert sanitise_html(source) == expected


# --------------------------------------------------------------------------------------------- #
# LP-854 review, round two — the href rule, from the corpus BOTH sides read
# --------------------------------------------------------------------------------------------- #
def _href_cases() -> dict[str, list[str]]:
    """The shared corpus. See `frontend/lib/markdown/href-cases.json` for why it is shared."""
    import json
    from pathlib import Path

    path = (
        Path(__file__).resolve().parents[2].parent
        / "frontend"
        / "lib"
        / "markdown"
        / "href-cases.json"
    )
    with path.open(encoding="utf-8") as handle:
        return dict(json.load(handle))


def test_the_shared_corpus_is_readable_and_not_empty() -> None:
    """THE POSITIVE CONTROL. Both assertions below are satisfied by two empty lists, and a path that
    stopped resolving — a moved file, a renamed directory — would produce exactly that."""
    cases = _href_cases()
    assert len(cases["safe"]) >= 10
    assert len(cases["refused"]) >= 20


def test_every_href_the_corpus_calls_safe_is_safe() -> None:
    for href in _href_cases()["safe"]:
        assert href_is_safe(href) is True, f"{href!r} should be safe"


def test_every_href_the_corpus_calls_refused_is_refused() -> None:
    """THE FOUR THAT SEPARATED THE TWO IMPLEMENTATIONS ARE IN HERE.

    `isSafeHref` and this function are one rule in two languages. They were compared once by running
    a set of hrefs through both and found to agree — true, and not the same thing as implementing
    the same rule. A vertical tab, a form feed, a DEL and an SOH in the middle of a scheme were each
    stripped by the editor and kept here, so the editor called them safe and this refused them: an
    editor accepting a link the server then strips, which is a link vanishing on save.
    """
    for href in _href_cases()["refused"]:
        assert href_is_safe(href) is False, f"{href!r} should be refused"


def test_no_single_injected_character_makes_a_dangerous_scheme_pass() -> None:
    """THE SECURITY DIRECTION, AS A PROPERTY OVER A CLASS rather than a list of representatives.

    The shared corpus pins 33 hrefs, which is the right shape for the agreement between the two
    implementations: thirty-one of the divergences found in the LP-854 review were one class, and a
    corpus needs a member of each class rather than every member.

    THIS IS THE OTHER INVARIANT, and it is stronger than any corpus can be: no single character,
    injected at any position in a dangerous scheme, makes it pass. Deleting characters from
    `javascript:` still spells `javascript`, which is why over-stripping never opened a hole — but
    "still spells it" is an argument, and this is the measurement. It also survives somebody adding
    a scheme to `ALLOWED_SCHEMES` later, which a list of examples would not.

    Suggested by the LP-854 reviewer after it swept the same space; written here rather than
    deferred, because the assertion that cannot be weakened by a later edit is the one worth having
    before the later edit.
    """
    dangerous = ["javascript:alert(1)", "vbscript:msgbox(1)", "data:text/html,x"]
    leaked: list[str] = []
    for scheme in dangerous:
        for code in range(0x100):
            character = chr(code)
            for position in range(len(scheme) + 1):
                candidate = scheme[:position] + character + scheme[position:]
                if href_is_safe(candidate):
                    leaked.append(f"{candidate!r} (U+{code:04X} at {position})")
    assert not leaked, f"a dangerous scheme passed: {leaked[:5]}"


def test_that_property_can_fail() -> None:
    """THE POSITIVE CONTROL. The sweep above is `assert not leaked` over a function that could
    reject everything and satisfy it — including the ordinary https URL a processor actually uses."""
    assert href_is_safe("https://example.com") is True
    assert href_is_safe("mailto:a@b.example") is True
