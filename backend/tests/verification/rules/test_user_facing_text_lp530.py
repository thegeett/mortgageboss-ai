"""LP-530 — what a PROCESSOR reads is held to a different standard than what an ENGINEER reads.

A spec file is both at once. Comments, tag descriptions and AI prompts are written for us and for the
model; ``couldnt_check_fix``, ``guidance``, ``materiality`` and ``verdict_labels`` are rendered verbatim
into a loan processor's queue. The repo uses a warning emoji freely in the first kind — that is a
convention, and it is fine.

It reached the second kind. CR-6 and IN-3 shipped a fix that opened a sentence with a warning sign in
front of a processor:

    "... so both the report and a closing date are needed. ⚠️ If the borrower has no derogatory events
     the report shows that too — this check will not assume a clean history ..."

Two things are wrong with it and only one is the emoji. The sentence is also written in the engine's
own voice — "this check will not assume", "this check abstains rather than choosing one" — which tells
the reader about the software's decision procedure when what they need is what to do about a document.
The same register is what makes the composer reach for "the system" (LP-529), so it is worth removing
at the source rather than only at the output.
"""

from __future__ import annotations

import pytest
import yaml
from app.verification.rules.specs import _SPECS_DIR

# Fields rendered verbatim into the UI. Everything not listed is engineer- or model-facing.
_USER_FACING = ("couldnt_check_fix", "guidance", "materiality", "verdict_labels")


def _user_facing_strings() -> list[tuple[str, str, str]]:
    found: list[tuple[str, str, str]] = []
    for path in sorted(_SPECS_DIR.glob("*.yaml")):
        document = yaml.safe_load(path.read_text())

        def walk(node: object, trail: tuple[str, ...], rule: str = path.stem) -> None:
            if isinstance(node, dict):
                for key, value in node.items():
                    walk(value, (*trail, str(key)))
            elif isinstance(node, list):
                for value in node:
                    walk(value, trail)
            elif isinstance(node, str) and any(field in trail for field in _USER_FACING):
                found.append((rule, ".".join(trail), node))

        walk(document, ())
    return found


def test_no_user_facing_string_carries_a_warning_emoji() -> None:
    """⚠️ THE EXACT SHAPE THAT SHIPPED — and note that this docstring may carry one, because a
    docstring is read by us. The assertion is about the other kind of text."""
    offenders = [(rule, field) for rule, field, text in _user_facing_strings() if "⚠️" in text]

    assert not offenders, (
        "a warning emoji reached text a loan processor reads — write the caveat as a plain "
        f"sentence: {offenders}"
    )


@pytest.mark.parametrize(
    "phrase",
    ["this check", "the rule engine", "the system", "abstain", "couldnt_check", "not_applicable"],
)
def test_no_user_facing_string_describes_the_machinery(phrase: str) -> None:
    """A processor is told what to do about a DOCUMENT. "this check abstains rather than choosing one"
    describes our control flow, which they can neither act on nor verify.

    This is the same failure the composer's ``machinery_talk`` guard catches on the way out (LP-528/529)
    — caught here at the source, where a human wrote it, rather than only in a generation."""
    offenders = [
        (rule, field) for rule, field, text in _user_facing_strings() if phrase in text.lower()
    ]

    assert not offenders, f"{phrase!r} describes the software, not the loan file: {offenders}"
