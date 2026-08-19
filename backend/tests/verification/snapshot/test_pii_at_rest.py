def test_a_parcel_number_does_not_refuse_the_whole_snapshot() -> None:
    """LP-565 — an Assessor's Parcel Number is identifier-shaped (9+ digits) and was passing through
    RAW, so the at-rest guard refused the write. On staging that meant 22 completed runs and ZERO
    persisted snapshots: no run auditable, no calculator output recoverable, no cross-run comparison.

    It is a public-record identifier rather than borrower PII, but the guard cannot tell one digit run
    from another — and its own message says to route the field through the PII map rather than relax
    the guard, because relaxing it is how the at-rest promise stops being true."""
    from app.verification.snapshot.documents_section import _PII_FIELDS

    assert "parcel_or_apn" in _PII_FIELDS
