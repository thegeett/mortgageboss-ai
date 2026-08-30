"""Parse warnings carry the subject the parser was looking at (LP-UI-024).

Every warning used to be a bare sentence. A screen wanting to link one to the
field it concerns had to recognise its own prose — and the parser already knew,
at the moment it gave up, exactly which section it was reading. The subject is
recorded there rather than recovered later by matching strings.

The read path has to stay tolerant: `parse_warnings` is a JSON column and rows
written before this change hold plain strings. They are still true, so they read
as `OTHER` rather than being dropped or crashing the response.
"""

from app.mismo.schema import ParseWarning, WarningSubject


class TestCoercingAStoredWarning:
    def test_a_legacy_string_row_still_reads(self) -> None:
        # The rows this has to keep working for: every import before LP-UI-024.
        warning = ParseWarning.coerce("Loan is missing a base loan amount.")
        assert warning.message == "Loan is missing a base loan amount."
        assert warning.subject is WarningSubject.OTHER

    def test_a_structured_row_keeps_its_subject(self) -> None:
        warning = ParseWarning.coerce(
            {"message": "Subject property is missing an estimated value.", "subject": "property"}
        )
        assert warning.subject is WarningSubject.PROPERTY

    def test_a_row_missing_its_subject_is_not_a_crash(self) -> None:
        # Half-written JSON is likelier than none, and a warnings panel that 500s
        # is worse than one that cannot link a row to its section.
        assert ParseWarning.coerce({"message": "odd"}).subject is WarningSubject.OTHER

    def test_a_subject_this_build_does_not_know_still_reads(self) -> None:
        """The MIRROR of the legacy case, and the one a rollback produces.

        `coerce` was written for old rows read by new code. The other direction
        is a newer version writing a subject an older one then reads, and a
        bare `model_validate` raises there — a 500 on the response rather than a
        missing link. Handling one direction is half a guarantee.
        """
        warning = ParseWarning.coerce(
            {"message": "A future field is missing.", "subject": "collateral"}
        )
        assert warning.message == "A future field is missing."
        assert warning.subject is WarningSubject.OTHER

    def test_a_shape_it_cannot_read_at_all_does_not_crash(self) -> None:
        # A JSON column can hold anything a past writer put there.
        assert ParseWarning.coerce(None).subject is WarningSubject.OTHER
        assert ParseWarning.coerce(42).subject is WarningSubject.OTHER
        assert ParseWarning.coerce({"subject": "loan"}).subject is WarningSubject.OTHER

    def test_other_is_a_real_member_not_a_hole(self) -> None:
        # A warning belonging to no section still has to appear somewhere. The
        # UI groups on this value, so it must be a value.
        assert WarningSubject.OTHER in set(WarningSubject)

    def test_the_subject_survives_a_json_round_trip(self) -> None:
        # It goes into a JSON column and comes back out; a StrEnum that dumped to
        # something `coerce` could not read would lose the link on every reload.
        stored = ParseWarning(message="No LOAN found.", subject=WarningSubject.LOAN).model_dump(
            mode="json"
        )
        assert stored == {"message": "No LOAN found.", "subject": "loan"}
        assert ParseWarning.coerce(stored).subject is WarningSubject.LOAN
