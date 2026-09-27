"""The refusal sentences the API returns are the spec's, character for character (LP-912).

WHY THIS READS THE SPEC RATHER THAN A COPY OF IT. Spec §6 rule 5 says the UI shows the server's
sentence as-is and never makes up its own, so the sentence IS the contract — and a contract asserted
against a second hand-typed copy of itself is not asserted at all. The four below are compared with the
bytes in `docs/phases/phase4.5-stage2-tickets.md`, so a sentence edited in one place and not the other
fails here.

THE SENTENCES ARE NOT IN THE DESIGN PACK, WHICH IS WHERE I LOOKED FIRST. All eleven Stage 2 screens
were grepped and none of the four appears; the only related wording is S2-05's hint ("Moving back keeps
the history. Moving forward never needs a reason."), which is not a refusal. That is consistent rather
than an omission — every mockup is a happy-path state, and a refusal appears only once a processor
trips it. So the tickets file is the single source, and this test is what ties the code to it.

TWO DIFFERENCES ARE PERMITTED, AND BOTH ARE STATED RATHER THAN QUIETLY ALLOWED:

1. **Markdown emphasis.** The spec is prose, and it writes "Moving back to *To do* needs a short
   reason." The asterisks are emphasis in a document, not part of what a processor reads; returning
   them would put a rendering artifact on screen.
2. **The interpolated target.** The spec gives that sentence for the one case S2-05 draws. A move from
   *Sent to lender* back to *Waiting on Borrower* is also backward, and naming "To do" there would be
   simply wrong — so the code carries a `{target}` placeholder and the To-do instance is what is
   pinned.

Five more codes exist (`waiting_needs_owner`, `nothing_to_reopen`, `verdict_needs_round`,
`status_not_offered`, `condition_was_replaced`) and are deliberately NOT checked here: the spec gives
its four "for example", the others are mine, and a test comparing my sentences against my own constants
would be a tautology. What IS asserted about them is that every code has a non-empty sentence, and that
the set of codes and the set of sentences cannot drift apart.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from app.services import condition_status as status
from app.services.condition_status import RefusalCode

_SPEC = (
    Path(__file__).resolve().parents[2].parent / "docs" / "phases" / "phase4.5-stage2-tickets.md"
)

#: `code` → the module constant that holds its sentence. Only the spec's four.
_FROM_THE_SPEC: dict[str, str] = {
    "backward_move_needs_reason": status._BACKWARD_MOVE_NEEDS_REASON,
    "info_only_has_no_status": status._INFO_ONLY_HAS_NO_STATUS,
    "verdict_needs_source": status._VERDICT_NEEDS_SOURCE,
    "stale": status._STALE,
}

#: The target the spec's backward-move example names, so the placeholder can be filled to match it.
_SPEC_TARGET = "To do"


def _spec_sentences() -> dict[str, str]:
    """`code` → the sentence as the tickets file writes it, emphasis stripped.

    Parsed rather than transcribed. The spec's form is:

        `backward_move_needs_reason` → "Moving back to *To do* needs a short reason." ·

    so the code is in backticks, the sentence is in the following double quotes, and the `·` is a
    separator between list items rather than part of anything.
    """
    text = _SPEC.read_text(encoding="utf-8")
    found: dict[str, str] = {}
    for code, sentence in re.findall(r"`([a-z_]+)`\s*→\s*\"([^\"]+)\"", text):
        # Markdown emphasis is the document's, not the sentence's — see the module docstring.
        found[code] = sentence.replace("*", "")
    return found


def test_the_spec_still_states_these_sentences() -> None:
    """WITHOUT THIS, EVERY ASSERTION BELOW IS VACUOUS. If the spec is moved, renamed, or its list
    reformatted, `_spec_sentences()` returns nothing and a comparison against an empty dict passes for
    every sentence. That is this suite's most repeated defect and the one it keeps re-learning."""
    assert _SPEC.is_file(), f"the Stage 2 tickets file is not at {_SPEC}"

    sentences = _spec_sentences()
    missing = sorted(set(_FROM_THE_SPEC) - set(sentences))
    assert not missing, (
        f"the spec no longer states a sentence for {missing}. Either §LP-912's refusal list changed "
        "shape, or the regex in this file stopped matching it — and in both cases this guard is no "
        "longer comparing anything."
    )


@pytest.mark.parametrize("code", sorted(_FROM_THE_SPEC))
def test_each_sentence_matches_the_spec_byte_for_byte(code: str) -> None:
    """The em dashes are U+2014 and the brackets and commas are the spec's.

    `info_only_has_no_status` is the one to watch: its em dash is the character most likely to become a
    hyphen in an editor, and nothing else in the stack would notice.
    """
    expected = _spec_sentences()[code]
    actual = _FROM_THE_SPEC[code]

    if "{target}" in actual:
        actual = actual.format(target=_SPEC_TARGET)

    assert actual == expected, (
        f"the sentence for `{code}` differs from the spec.\n"
        f"  spec: {expected!r}\n"
        f"  code: {actual!r}\n"
        "Spec §6 rule 5 says the UI shows the server's sentence as-is, so these are one string in two "
        "places and the spec is the authority."
    )


def test_the_interpolated_target_is_actually_interpolated() -> None:
    """The backward-move sentence must NAME the status being moved to.

    A placeholder left unfilled would read "Moving back to {target} needs a short reason." on screen,
    and a sentence with the placeholder REMOVED would read "Moving back to needs a short reason." Both
    pass a naive substring check, so this asserts the target appears and the braces do not.
    """
    filled = status._BACKWARD_MOVE_NEEDS_REASON.format(target="Waiting on someone")

    assert "Waiting on someone" in filled
    assert "{" not in filled and "}" not in filled
    # And it is not the spec's example dressed up: a different target gives a different sentence.
    assert filled != status._BACKWARD_MOVE_NEEDS_REASON.format(target=_SPEC_TARGET)


def test_every_refusal_code_has_a_sentence_and_none_is_orphaned() -> None:
    """The five authored codes are not compared against the spec — this is what covers them instead.

    Every code must resolve to a non-empty sentence, and every sentence constant must belong to a code.
    A code added without wording would otherwise refuse a write with an empty string, which is the one
    thing worse than a wrong sentence: the screen shows nothing and the processor is simply stuck.
    """
    sentences = {
        RefusalCode.BACKWARD_MOVE_NEEDS_REASON: status._BACKWARD_MOVE_NEEDS_REASON,
        RefusalCode.INFO_ONLY_HAS_NO_STATUS: status._INFO_ONLY_HAS_NO_STATUS,
        RefusalCode.VERDICT_NEEDS_SOURCE: status._VERDICT_NEEDS_SOURCE,
        RefusalCode.STALE: status._STALE,
        RefusalCode.WAITING_NEEDS_OWNER: status._WAITING_NEEDS_OWNER,
        RefusalCode.NOTHING_TO_REOPEN: status._NOTHING_TO_REOPEN,
        RefusalCode.VERDICT_NEEDS_ROUND: status._VERDICT_NEEDS_ROUND,
        RefusalCode.STATUS_NOT_OFFERED: status._STATUS_NOT_OFFERED,
        RefusalCode.CONDITION_WAS_REPLACED: status._CONDITION_WAS_REPLACED,
    }

    uncovered = sorted(code.value for code in RefusalCode if code not in sentences)
    assert not uncovered, f"these refusal codes have no sentence in this map: {uncovered}"

    blank = sorted(code.value for code, sentence in sentences.items() if not sentence.strip())
    assert not blank, f"these refusal codes resolve to an empty sentence: {blank}"

    # Each sentence ends like a sentence. A fragment is what a hurried edit leaves behind.
    unfinished = sorted(
        code.value for code, sentence in sentences.items() if not sentence.rstrip().endswith(".")
    )
    assert not unfinished, f"these refusal sentences do not end in a full stop: {unfinished}"
