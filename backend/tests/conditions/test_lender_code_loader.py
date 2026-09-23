"""The shipped lender code maps parse, and a malformed one is refused (LP-910, ADR-407).

No database. This file is entirely about the YAML and the loader, which is why it can assert the
thing that matters most about shipped reference data: that it is *valid*, not merely present.

THE ASSERTION THAT EARNS ITS KEEP is the leading-zero one. YAML reads an unquoted `0006` as the
integer 6, `str(6)` is `"6"`, and `"6"` is an identifier that looks plausible and matches nothing —
a defect that would surface months later as a condition whose code never resolved. The loader refuses
it rather than coercing, and this pins that.
"""

from __future__ import annotations

import pytest
from app.conditions.lender_codes import LenderCodeSeedError, load_seed, seeded_lender_keys
from app.conditions.lender_codes.loader import _row
from app.models.condition import BucketKind, OwnerHint


def test_both_shipped_maps_parse() -> None:
    """Every row in every shipped file resolves — LP-910's "every seeded code resolves"."""
    assert seeded_lender_keys() == ("champions", "uwm")
    for key in seeded_lender_keys():
        rows = load_seed(key)
        assert len(rows) == 28, f"{key} should ship 28 codes, got {len(rows)}"
        assert all(row.label.strip() for row in rows)


def test_uwm_codes_keep_their_leading_zeros() -> None:
    """⚠️ THE ONE THAT WOULD COST MONTHS. `0006` is an identifier, not the number 6.

    Asserted as a string comparison rather than a truthiness check, because the failure mode is a
    value that is still a valid-looking code — `"6"` — rather than a missing one.
    """
    codes = {row.code for row in load_seed("uwm")}

    assert "0006" in codes
    assert "0007" in codes
    assert "0132" in codes
    assert "6" not in codes, "a leading-zero code was coerced through int and back"


def test_every_enum_value_in_the_shipped_files_is_real() -> None:
    """The class of typo that CHECK tuples and code maps share.

    `prior_to_doc` would load fine as a string, match no `BucketKind`, and quietly downgrade every
    condition carrying that code. The loader resolves to the enum, so this passes only if every
    value in both files is a genuine member.
    """
    for key in seeded_lender_keys():
        for row in load_seed(key):
            assert row.default_bucket_kind is None or isinstance(
                row.default_bucket_kind, BucketKind
            )
            assert row.default_owner_hint is None or isinstance(row.default_owner_hint, OwnerHint)


def test_canonical_type_ids_are_absent_and_that_is_deliberate() -> None:
    """Not a gap — the taxonomy is not in this repository (spec §LP-910).

    The `AS-11`-style ids in `docs/rule-engine.md` are VERIFICATION RULE ids, a different vocabulary
    that happens to look alike. Pinned so that when Stage 3's library lands, filling these is a
    visible change rather than something that drifts in.
    """
    for key in seeded_lender_keys():
        assert all(row.canonical_type_id is None for row in load_seed(key))


def test_an_unknown_lender_key_is_refused() -> None:
    with pytest.raises(LenderCodeSeedError, match="no shipped code map"):
        load_seed("sunwest")


# --------------------------------------------------------------------------- #
# What a malformed file is refused for. Each is an editing accident a domain
# expert could plausibly make, and each is refused rather than absorbed.
# --------------------------------------------------------------------------- #
def test_a_numeric_code_is_refused_rather_than_coerced() -> None:
    """The guard behind `test_uwm_codes_keep_their_leading_zeros`, at the row level."""
    with pytest.raises(LenderCodeSeedError, match="not a string"):
        _row({"code": 6, "label": "Credit report invoice"}, source="test.yaml")


def test_a_row_with_no_label_is_refused() -> None:
    with pytest.raises(LenderCodeSeedError, match="no label"):
        _row({"code": "0006", "label": "  "}, source="test.yaml")


def test_an_unknown_bucket_kind_is_refused_and_named() -> None:
    """The message lists the permitted values, because the reader is a person editing YAML."""
    with pytest.raises(LenderCodeSeedError, match="prior_to_doc"):
        _row(
            {"code": "0006", "label": "x", "default_bucket_kind": "prior_to_doc"},
            source="test.yaml",
        )


def test_an_unknown_owner_hint_is_refused() -> None:
    with pytest.raises(LenderCodeSeedError, match="escrow"):
        _row({"code": "0006", "label": "x", "default_owner_hint": "escrow"}, source="test.yaml")


def test_a_null_default_is_legitimate_and_not_confused_with_a_typo() -> None:
    """⚠️ THE DISTINCTION THE ENUM RESOLVER EXISTS FOR.

    A code whose bucket nobody has decided is `None`; a code whose bucket is misspelled is an error.
    Collapsing them would make `prior_to_doc` behave exactly like "not decided", which is the failure
    the resolver is written to prevent — so both halves are asserted together.
    """
    row = _row({"code": "0006", "label": "x"}, source="test.yaml")

    assert row.default_bucket_kind is None
    assert row.default_owner_hint is None
    assert row.info_only is False
