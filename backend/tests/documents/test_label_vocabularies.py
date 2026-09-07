"""Two label vocabularies that look like one, and must not be merged (LP-638 review).

`_TYPE_LABEL_OVERRIDES` (the type picker) and `NAME_RULES[...].label` (standard filenames) both map
a document-type slug to a human-ish string, overlap on one entry, and already DISAGREE on another:
`voe` is "VOE" in one and "Verification of employment (VOE)" in the other. That reads as drift of
exactly the kind LP-638 was opened about — a second list of the same knowledge — and the natural
instinct is to make them agree.

That instinct would break filenames. `standard_name` joins its label into
``{Type}_{Identifier}_{Date}``, so a label containing a space, a slash or an underscore stops
producing a usable name. The picker has the opposite requirement: it is prose a processor scans.

So this pins the property that keeps them apart, rather than a comment claiming it.
"""

from __future__ import annotations

import re

from app.api.documents import _TYPE_LABEL_OVERRIDES
from app.documents.naming import NAME_RULES

#: A filename component: no whitespace, and none of the characters `standard_name` joins on or that
#: a filesystem dislikes.
_FILENAME_SAFE = re.compile(r"^[A-Za-z0-9.\-()]+$")


def test_filename_labels_stay_filename_safe() -> None:
    """The reason the picker's labels cannot simply be used here."""
    for slug, rule in NAME_RULES.items():
        assert _FILENAME_SAFE.match(rule.label), (
            f"NAME_RULES[{slug!r}].label = {rule.label!r} is not usable in a filename. If this was "
            "changed to match the type picker's display label, revert it — they are different "
            "vocabularies, and standard_name joins this one into {Type}_{Identifier}_{Date}."
        )


def test_the_picker_is_free_to_be_prose() -> None:
    """The other direction, so the split is asserted rather than assumed.

    At least one display label must be something a filename could not hold — otherwise the two
    vocabularies have quietly converged and the next person is right to merge them.
    """
    prose = [label for label in _TYPE_LABEL_OVERRIDES.values() if not _FILENAME_SAFE.match(label)]
    assert prose, (
        "every type-picker label is now filename-safe, so nothing distinguishes these two maps any "
        "more — either the picker's labels have been flattened, or the two really can be merged"
    )


def test_every_label_override_names_a_real_catalog_type() -> None:
    """The map drifted on the commit that introduced it (LP-638 review).

    Three of its ten keys — `vod`, `hud1`, `form_1003` — were not catalog slugs at all, so those
    entries were dead and the types they meant to fix fell through to the generic label. A second
    hand-maintained list keyed by catalog slug is exactly the drift this ticket exists to end, and
    nothing checked it: the endpoint tests assert every option HAS a label, never that every
    override names something real.
    """
    from app.api.documents import _TYPE_LABEL_OVERRIDES
    from app.documents.catalog import CATALOG

    unknown = sorted(set(_TYPE_LABEL_OVERRIDES) - set(CATALOG))
    assert not unknown, (
        f"{unknown} are not catalog types, so these overrides do nothing and the types they were "
        "written for fall through to the derived label. Either the slug changed or it was guessed."
    )


def test_derived_labels_do_not_flatten_acronyms() -> None:
    """`capitalize()` lowercases everything after the first letter, so a processor picked from
    "Hoa statement", "Aus findings" and "E consent disclosure" — and those labels are now echoed
    back in the confirmation toast."""
    from app.api.documents import _type_label

    assert _type_label("hoa_statement") == "HOA statement"
    assert _type_label("aus_findings") == "AUS findings"
    assert _type_label("emd_withdrawal_proof") == "EMD withdrawal proof"
