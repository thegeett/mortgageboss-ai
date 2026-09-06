"""What field names a document type declares (LP-703).

The universe a hand-entered field key is checked against, and the reason it needs
its own tests: the set is used two ways that differ, and the difference is invisible
in the data — both halves are bare strings.
"""

from __future__ import annotations

from app.documents.schema_fields import (
    declared_fields,
    fields_for,
    schema_field_pairs,
)


class TestTheSetIsRealAtAll:
    """The positive control.

    Every assertion below is about what the set CONTAINS or EXCLUDES, and all of
    them would pass over an empty set. A packaging change that stopped the specs
    shipping is exactly what happened once before (the container's package root is
    ``/app``, and a path derived from ``backend/`` walked off it), and it read as a
    field rename for the whole life of that image.
    """

    def test_it_finds_the_specs(self) -> None:
        assert len(declared_fields()) >= 100

    def test_it_finds_the_fields(self) -> None:
        assert sum(len(v) for v in declared_fields().values()) >= 1000


class TestAddableFieldsAreTypedCoreOnly:
    """A nested-row column is NOT a field of the document.

    ``earning_type`` is a column inside a pay stub's ``earnings_lines`` list. Added
    at the TOP level it would be stored, displayed, and read by nothing — a value a
    processor typed that reaches no rule, on a file that then looks more complete
    for it. A first version of this returned typed core and nested rows in one set
    and offered exactly that.
    """

    def test_a_typed_core_field_is_offered(self) -> None:
        assert "gross_pay" in fields_for("pay_stub")

    def test_a_nested_row_column_is_NOT(self) -> None:
        assert "earning_type" not in fields_for("pay_stub")
        assert "current_amount" not in fields_for("pay_stub")

    def test_the_nested_column_really_is_declared_somewhere(self) -> None:
        # The control for the test above. If `earning_type` were simply not in the
        # specs at all, that assertion would pass for the wrong reason and would go
        # on passing if the split were removed.
        assert ("pay_stub", "earning_type") in schema_field_pairs()


class TestTheWiderSetKeepsItsCaller:
    """``distrust`` validates against typed core AND nested rows, and must keep both.

    A distrusted field can be a nested-row column, so narrowing this set to match
    ``fields_for`` would make every such entry look like a typo.
    """

    def test_it_is_a_superset_of_the_typed_core(self) -> None:
        pairs = schema_field_pairs()
        for document_type, fields in declared_fields().items():
            for field in fields:
                assert (document_type, field) in pairs

    def test_it_is_strictly_wider(self) -> None:
        core = sum(len(v) for v in declared_fields().values())
        assert len(schema_field_pairs()) > core


class TestAnUnknownTypeCanAddNothing:
    """Empty is a refusal, not a permission."""

    def test_an_untyped_document_declares_nothing(self) -> None:
        assert fields_for(None) == frozenset()
        assert fields_for("") == frozenset()

    def test_a_type_no_spec_names_declares_nothing(self) -> None:
        assert fields_for("a_type_that_does_not_exist") == frozenset()
