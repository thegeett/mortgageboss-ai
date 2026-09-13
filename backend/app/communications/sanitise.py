"""The allowlist that replaces "safe by construction" (LP-853).

`email-body.ts` needs no sanitiser: it escapes every character that could begin markup BEFORE it
emits a single tag, so there is no passthrough to leave open and no rules to keep up with a
renderer. Its own comment says so, and it was right.

STORING AUTHOR HTML ENDS THAT PROPERTY, and this is what replaces it. A sanitiser added later is a
window in which every draft written is untrusted, so it ships in the same ticket as the column.

RE-SERIALISED, NOT FILTERED. Nothing from the input reaches the output as markup: the parser reports
tags and text, and this builds a new document from the allowlist. A tag that is not on the list
contributes its TEXT and nothing else; an attribute that is not on the list does not exist. That is
the same shape as the escape-first renderer it replaces — fail-closed by construction rather than by
a list of things to strip — which is also why it is stdlib `HTMLParser` rather than a dependency: a
remove-what-is-bad sanitiser is the design that has to keep up with an attacker, and there is no
allowlist sanitiser in this project's dependencies to reach for.

THE LIST IS THE EDITOR'S SCHEMA. `ALLOWED` is the one place the tag set is written down; the Tiptap
extensions and `emailBodyToHtml`'s output name the same tags, and LP-854 extends all three from
here. LP-849's own notes record formatting vanishing on save when two of the three drifted.

NO CLASSES AND NO INLINE STYLES, EVER — and that is a mail rule before it is a security one. Outlook
on the desktop renders with Word's engine and discards most CSS, so anything that leaned on a
stylesheet would arrive unformatted. `style` and `class` being absent from the allowlist enforces
the same thing twice over.

THERE IS NO `html_to_plain` HERE, DELIBERATELY. `mailto:` and LP-855's compose routes need plain
text, and `from-html.ts` already derives it — tested as a round-trip fixed point since LP-849. A
second implementation on this side would be two answers to one question, which is A22. The only
thing the backend reads the body's LENGTH for is the `mailto:` ceiling, and an HTML body is longer
than the text it renders to, so that gate stays conservative rather than wrong.

`text_lines` IS NOT THAT FUNCTION, and the distinction is worth stating because it looks like it.
It produces the lines of a body for a HUMAN TO READ IN A WARNING — LP-851 quotes a processor's own
sentence back at them. It is never the message, never stored, never sent, and nothing round-trips
through it, so the property `from-html.ts` has to hold (that its output converts back) is not a
property this needs at all. Two functions, two jobs; the one that must be reversible has exactly
one implementation.
"""

from __future__ import annotations

from html import escape
from html.parser import HTMLParser

#: Tag -> the attributes it may keep. THE EDITOR'S SCHEMA, WRITTEN ONCE.
#:
#: LP-854 — THE CANONICAL COPY IS `frontend/lib/markdown/schema.ts`, and this must equal it.
#: Python cannot import TypeScript, so the agreement is a test rather than an import:
#: `frontend/lib/markdown/schema-drift.test.ts` reads THIS dict and fails when the two disagree.
#: Adding a mark means adding it to that file, and this one, and the Tiptap extensions — and the
#: test is what stops two of the three being enough.
#:
#: WHY EQUAL AND NOT MERELY COMPATIBLE: a tag the editor can produce and this strips is formatting
#: that vanishes on save, which LP-849's notes record happening; a tag this allows and the editor
#: cannot make is a hole with nothing watching it.
ALLOWED: dict[str, frozenset[str]] = {
    # LP-849's original set: paragraphs, a single-newline break, bold, and bullet lists.
    "p": frozenset(),
    "br": frozenset(),
    "strong": frozenset(),
    "ul": frozenset(),
    "li": frozenset(),
    # LP-854 — the Gmail marks that need a tag of their own. `em` is here despite that ticket's
    # table claiming italic already existed: it did not, in the editor or in the renderer.
    "em": frozenset(),
    "u": frozenset(),
    "ol": frozenset(),
    "blockquote": frozenset(),
    # THE ONLY TAG WITH AN ATTRIBUTE, and the only one with a security dimension. `href` is checked
    # against `ALLOWED_SCHEMES` below; nothing else on an `<a>` survives — no `target`, no `rel`,
    # no `class`, no `style`.
    "a": frozenset({"href"}),
}

#: Tags that close themselves. Written down rather than inferred, because emitting `</br>` produces
#: a second line break in several composers.
VOID = frozenset({"br"})

#: Elements whose CONTENT is dropped along with their tags.
#:
#: Everything else contributes its text: a `<div>` is not markup we keep, but the sentence inside it
#: is a processor's sentence and throwing it away would lose their words. These are the opposite —
#: the text inside a `<script>` or a `<style>` is not prose, and a processor pasting from a web page
#: would otherwise find a stylesheet in the middle of their email.
DROP_CONTENT = frozenset({"script", "style", "head", "title", "textarea", "noscript"})

#: The schemes an `href` may use. Not reachable yet — nothing in `ALLOWED` takes an href until
#: LP-854 — and defined here because the rule belongs with the allowlist rather than with the ticket
#: that first needs it.
#:
#: A LINK IN AN EMAIL TO A BORROWER IS A PHISHING SURFACE if we let it be, so this is three schemes
#: and nothing relative. `javascript:`, `data:` and `vbscript:` are the obvious ones, and an
#: allowlist does not have to know their names.
ALLOWED_SCHEMES = frozenset({"http", "https", "mailto"})


def href_is_safe(value: str) -> bool:
    """Whether this href may survive.

    NORMALISED BEFORE IT IS READ. A scheme can carry leading whitespace, a NUL or mixed case and
    still be honoured — `java\\tscript:` and `JaVaScRiPt:` both run in a browser. Stripping the
    invisible characters and lowercasing first compares against what a client would actually
    resolve rather than against what the string looks like.
    """
    cleaned = "".join(ch for ch in value if ch.isprintable() and not ch.isspace()).lower()
    if ":" not in cleaned:
        # A relative or anchor-only href. Refused rather than resolved: this text is pasted into a
        # mail client, where there is no page for it to be relative to.
        return False
    return cleaned.split(":", 1)[0] in ALLOWED_SCHEMES


class _Allowlist(HTMLParser):
    """Rebuilds the document from `ALLOWED`. Nothing is copied through."""

    def __init__(self) -> None:
        # `convert_charrefs` leaves entity decoding to the parser, so `&amp;lt;` arrives as the text
        # `&lt;` and is escaped once on the way out rather than decoded twice — the same ordering
        # bug `from-html.ts` records in `unescapeHtml`.
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        #: Open allowlisted tags, so a stray `</p>` cannot close something it did not open and an
        #: unclosed `<strong>` is closed at the end rather than bleeding into whatever follows.
        self.open: list[str] = []
        #: Depth inside an element whose content is dropped.
        self.muted = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in DROP_CONTENT:
            self.muted += 1
            return
        if self.muted or tag not in ALLOWED:
            return
        kept: list[str] = []
        for name, value in attrs:
            if name not in ALLOWED[tag] or value is None:
                continue
            if name == "href" and not href_is_safe(value):
                continue
            kept.append(f' {name}="{escape(value, quote=True)}"')
        # LP-854 — AN ANCHOR WITH NO SURVIVING href IS NOT A LINK, so it is not emitted as one. The
        # first version kept the tag and dropped the attribute, which left `<a>click</a>`: something
        # that looks like a link, is styled like one in every client, and goes nowhere. Dropping the
        # element and keeping its TEXT is the honest outcome — the processor's words survive and the
        # thing that was refused is visibly absent.
        if tag == "a" and not kept:
            return
        self.out.append(f"<{tag}{''.join(kept)}>")
        if tag not in VOID:
            self.open.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if not self.muted and tag in VOID and tag in ALLOWED:
            self.out.append(f"<{tag}>")

    def handle_endtag(self, tag: str) -> None:
        if tag in DROP_CONTENT:
            self.muted = max(self.muted - 1, 0)
            return
        if self.muted or tag not in ALLOWED or tag in VOID or tag not in self.open:
            return
        # Close everything opened inside it too, so the output nests even where the input did not.
        while self.open:
            closing = self.open.pop()
            self.out.append(f"</{closing}>")
            if closing == tag:
                break

    def handle_data(self, data: str) -> None:
        if not self.muted:
            self.out.append(escape(data, quote=False))

    def finish(self) -> str:
        while self.open:
            self.out.append(f"</{self.open.pop()}>")
        return "".join(self.out)


def sanitise_html(html: str) -> str:
    """The stored form of an author's HTML body.

    Everything outside `ALLOWED` becomes text or nothing: `onclick=` and `style=` are not attributes
    of anything, a `<script>` loses its tags AND its contents, and an `href` that is not
    http/https/mailto is dropped while the link text survives.

    CALLED ON THE WAY IN, NOT ON THE WAY OUT. A sanitiser at render time is one renderer's decision;
    doing it here means the column never holds anything that was not allowed, so every reader of it
    — the modal, the clipboard, a future send provider — inherits the guarantee without knowing the
    rule.
    """
    parser = _Allowlist()
    parser.feed(html)
    parser.close()
    return parser.finish()


class _Text(HTMLParser):
    """Visible text, one entry per block — see `text_lines`."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: list[str] = []
        self.buffer: list[str] = []
        self.muted = 0

    def _flush(self) -> None:
        text = " ".join("".join(self.buffer).split())
        self.buffer = []
        if text:
            self.lines.append(text)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in DROP_CONTENT:
            self.muted += 1
        elif tag in BLOCK:
            self._flush()

    def handle_endtag(self, tag: str) -> None:
        if tag in DROP_CONTENT:
            self.muted = max(self.muted - 1, 0)
        elif tag in BLOCK:
            self._flush()

    def handle_data(self, data: str) -> None:
        if not self.muted:
            self.buffer.append(data)

    def finish(self) -> list[str]:
        self._flush()
        return self.lines


#: Tags that end a line of visible text. `br` is here with the block elements because a processor
#: pressing shift-return means a new line, whatever the schema calls it.
BLOCK = frozenset({"p", "br", "li", "ul", "ol", "blockquote", "div", "tr"})


def text_lines(html: str) -> list[str]:
    """The visible lines of an HTML body, for a human to read in a warning (LP-851).

    NOT A PLAIN-TEXT CONVERSION — see the module docstring. Whitespace is collapsed and nothing is
    reversible: this exists so a dialog can say *"your changes — including ..."* in the processor's
    own words, and the only property it needs is that a line a person typed comes back recognisable.
    """
    parser = _Text()
    parser.feed(html)
    parser.close()
    return parser.finish()


__all__ = [
    "ALLOWED",
    "ALLOWED_SCHEMES",
    "DROP_CONTENT",
    "href_is_safe",
    "sanitise_html",
    "text_lines",
]
