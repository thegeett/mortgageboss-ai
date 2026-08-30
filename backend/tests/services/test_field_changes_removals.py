"""`field_changes` records REMOVALS, not just additions and edits (LP-UI-026).

Found on screen rather than in a test: the overlay editor's change history read
"Avery Stone saved the overlay with no threshold changes" for an edit that had
just deleted an override. The function iterated `after` alone, so a key present
before and absent after produced nothing at all — and the audit trail, which
exists to say what happened, held no record that the override was ever removed.

The three other callers (property, stated financials, loan-file edits) build
`before` from `after`'s own keys, so their key sets are equal by construction and
the union changes nothing for them. Pinned below so that stays true.
"""

from app.services.activity_log import field_changes


class TestRemovals:
    def test_a_removed_key_is_recorded(self) -> None:
        changes = field_changes({"conv.dti.max": "45"}, {})
        assert changes == [{"field": "conv.dti.max", "from": "45", "to": None}]

    def test_an_added_key_is_recorded(self) -> None:
        changes = field_changes({}, {"conv.dti.max": "45"})
        assert changes == [{"field": "conv.dti.max", "from": None, "to": "45"}]

    def test_an_edited_key_is_recorded(self) -> None:
        changes = field_changes({"a": "1"}, {"a": "2"})
        assert changes == [{"field": "a", "from": "1", "to": "2"}]

    def test_an_unchanged_key_is_not(self) -> None:
        assert field_changes({"a": "1"}, {"a": "1"}) == []

    def test_a_removal_alongside_an_edit(self) -> None:
        # The real shape of an overlay edit: one threshold moved, one dropped.
        changes = field_changes({"a": "1", "b": "2"}, {"a": "9"})
        assert changes == [
            {"field": "a", "from": "1", "to": "9"},
            {"field": "b", "from": "2", "to": None},
        ]

    def test_equal_key_sets_are_unaffected(self) -> None:
        # How the other three callers use it — `before` built from `after`'s keys.
        provided = {"city": "Newark", "state": "NJ"}
        before = {"city": "Trenton", "state": "NJ"}
        assert field_changes(before, provided) == [
            {"field": "city", "from": "Trenton", "to": "Newark"}
        ]
