"""Condition-scoped propagation depends on one library fact (Stage 3B acceptance review).

WHAT THE ACCEPTANCE TEST FIXED. A deposit answered on one statement left the same deposit open on
another copy of it, and that held the condition forever. `answer_finding` now answers the same
(account, date, amount) across the CONDITION's other statements.

WHY THE CONDITION IS THE RIGHT SCOPE, AND WHAT THAT RESTS ON. A large-deposit finding is only ever
raised on an item whose checks include `covers_required_funds`, and exactly ONE library item declares
that check: `AS-10` "Short funds to close or reserves". So every copy of a given deposit finding lives
under one condition, and a condition-scoped sweep reaches all of them.

That is a fact about `types.yaml`, not a property of the code. Give a second type the same check — a
reserves type, say, or a second short-funds type for a lender that splits the ask — and two conditions
can each carry a copy of the same deposit. Answering it on one would leave the other open and holding,
which is the defect the acceptance test just closed, returning through a different door.

This test is the tripwire. It does not forbid the second type; it makes adding one a moment where
somebody looks at `answer_finding`'s scope again.
"""

from __future__ import annotations

from app.conditions.library.loader import load_library
from app.models.condition_vocabulary import EvidenceCheck

#: The one item that may raise a large-deposit finding, as `(type id, item key)`.
_COVERS_ITEMS: frozenset[tuple[str, str]] = frozenset({("AS-10", "statements")})


def _items_declaring_covers() -> set[tuple[str, str]]:
    library = load_library()
    types = library.types if isinstance(library.types, dict) else {t.id: t for t in library.types}
    return {
        (condition_type.id, item.key)
        for condition_type in types.values()
        for item in condition_type.items
        if EvidenceCheck.COVERS_REQUIRED_FUNDS in item.checks
    }


def test_the_library_was_actually_read() -> None:
    """The positive control: the assertion below passes on an empty library too."""
    library = load_library()
    types = library.types if isinstance(library.types, dict) else {t.id: t for t in library.types}

    assert len(types) >= 40, len(types)
    assert "AS-10" in types


def test_only_one_item_can_raise_a_large_deposit_finding() -> None:
    """A second one means `answer_finding`'s condition-scoped sweep no longer reaches every copy."""
    declaring = _items_declaring_covers()

    assert declaring == set(_COVERS_ITEMS), (
        f"items declaring covers_required_funds: {sorted(declaring)}; recorded: "
        f"{sorted(_COVERS_ITEMS)}. A large-deposit finding is raised only on such an item, and "
        "`answer_finding` sweeps the CONDITION's statements. With two of them on one file, answering "
        "the deposit on one condition leaves the identical finding open on the other, holding it — "
        "the Stage 3B defect again. Widen the sweep, or add the item here having checked it cannot "
        "share a deposit with the first."
    )
