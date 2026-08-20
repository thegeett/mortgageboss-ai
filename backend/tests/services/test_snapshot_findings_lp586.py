"""LP-586 — the stability contract for snapshot-based AI findings.

THE REQUIREMENT, in the user's words: the tab must be consistent on every run, and change ONLY when
the snapshot really changed. That cannot come from prompting — an LLM asked the same question twice
gives different words, different ordering, and sometimes a different set. It comes from not asking
again while the snapshot's fingerprint holds.

Three properties, and all three are load-bearing. A pass that only had the first would give a stable
count on an unchanged file and still lose a processor's dismissal the moment anything moved — which
trains people to stop dismissing, and is worse than a count that drifts.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.ai.snapshot_cross_source import SnapshotFindingDraft
from app.models import Company, LoanProgram
from app.services.loan_files import create_loan_file
from app.services.snapshot_findings import refresh_snapshot_findings
from app.verification.snapshot.fields import Field, FieldSource
from app.verification.snapshot.model import MismoSection, Snapshot
from app.verification.snapshot_findings.fingerprint import snapshot_fingerprint
from sqlalchemy.ext.asyncio import AsyncSession

# A FIXED loan file id. It is stable per file in production and therefore part of the content; the
# first version of this helper minted a fresh one per call, so the fingerprint differed for that
# reason and the test "passed its own bug" rather than exercising the per-run exclusion.
_FILE_ID = UUID("11111111-2222-3333-4444-555555555555")


def _snapshot(*, valuation: str = "578000.00", run: int = 1) -> Snapshot:
    """A snapshot whose CONTENT is controlled by `valuation`, and whose per-run fields differ."""
    return Snapshot(
        loan_file_id=_FILE_ID,
        run_id=uuid4(),  # different every call — the per-run field the fingerprint must ignore
        created_at=datetime(2026, 8, 19, run, 0, tzinfo=UTC),
        mismo=MismoSection(
            facts={
                "property.valuation_amount": Field.present(valuation, source=FieldSource.PARSED),
                "loan.amount": Field.present("452000.00", source=FieldSource.PARSED),
            }
        ),
    )


def _drafts(
    title: str = "Assessed value is below the stated valuation",
) -> list[SnapshotFindingDraft]:
    return [
        SnapshotFindingDraft(
            kind="valuation_vs_assessment",
            title=title,
            detail="The tax bill assesses the property below the stated valuation.",
            sources=[
                {"label": "application", "value": "578000.00"},
                {"label": "property tax bill", "value": "551923"},
            ],
        )
    ]


async def _file(db: AsyncSession, slug: str):
    company = Company(name=slug.title(), slug=f"{slug}-{uuid4().hex[:6]}")
    db.add(company)
    await db.flush()
    return await create_loan_file(db, company_id=company.id, loan_program=LoanProgram.CONVENTIONAL)


# --------------------------------------------------------------------------------------------- #
# 1. The fingerprint itself
# --------------------------------------------------------------------------------------------- #


def test_the_fingerprint_ignores_the_per_run_fields() -> None:
    """THE WHOLE TRICK. `run_id` and `created_at` differ on every run WITHOUT the file differing —
    hash them and the cache never hits, so the feature looks implemented and is inert."""
    assert snapshot_fingerprint(_snapshot(run=1)) == snapshot_fingerprint(_snapshot(run=2))


def test_the_fingerprint_moves_when_content_moves() -> None:
    """The other half: a real change must re-ask, or the tab serves a stale answer."""
    assert snapshot_fingerprint(_snapshot()) != snapshot_fingerprint(_snapshot(valuation="551923"))


# --------------------------------------------------------------------------------------------- #
# 2. The cache
# --------------------------------------------------------------------------------------------- #


async def test_an_unchanged_snapshot_does_not_ask_the_model_again(db_session: AsyncSession) -> None:
    """THE HEADLINE. The second run must not call the reasoner at all — not "call it and get the
    same answer", which is exactly what an LLM will not do."""
    loan_file = await _file(db_session, "stable")
    snapshot = _snapshot()
    calls = 0

    async def reasoner(_payload: str):
        nonlocal calls
        calls += 1
        return _drafts()

    first = await refresh_snapshot_findings(
        db_session, loan_file_id=loan_file.id, snapshot=snapshot, reasoner=reasoner
    )
    second = await refresh_snapshot_findings(
        db_session, loan_file_id=loan_file.id, snapshot=_snapshot(run=9), reasoner=reasoner
    )

    assert calls == 1, "the model was asked again about an unchanged file"
    assert [f.finding_key for f in first] == [f.finding_key for f in second]
    assert [f.title for f in first] == [f.title for f in second]


async def test_a_changed_snapshot_re_asks(db_session: AsyncSession) -> None:
    loan_file = await _file(db_session, "changed")
    calls = 0

    async def reasoner(_payload: str):
        nonlocal calls
        calls += 1
        return _drafts()

    await refresh_snapshot_findings(
        db_session, loan_file_id=loan_file.id, snapshot=_snapshot(), reasoner=reasoner
    )
    await refresh_snapshot_findings(
        db_session,
        loan_file_id=loan_file.id,
        snapshot=_snapshot(valuation="551923"),
        reasoner=reasoner,
    )

    assert calls == 2


# --------------------------------------------------------------------------------------------- #
# 3. Identity — the half that protects the processor's work
# --------------------------------------------------------------------------------------------- #


def test_identity_is_the_sources_not_the_wording() -> None:
    """The model rewords the same observation between calls even at temperature 0. Hashing the
    sentence would mint a NEW finding for a reworded one, and the dismissal attached to the old key
    would evaporate."""
    a = _drafts("Assessed value is below the stated valuation")[0]
    b = _drafts("The county assessment sits under the value on the application")[0]

    assert a.finding_key == b.finding_key


async def test_a_dismissal_survives_a_snapshot_change(db_session: AsyncSession) -> None:
    """THE PROPERTY THAT MAKES THE TAB USABLE. A processor clears a finding; the file then moves for
    an unrelated reason. If the finding returns as open, they learn that dismissing is pointless."""
    loan_file = await _file(db_session, "dismissed")

    async def reasoner(_payload: str):
        return _drafts()

    (finding,) = await refresh_snapshot_findings(
        db_session, loan_file_id=loan_file.id, snapshot=_snapshot(), reasoner=reasoner
    )
    finding.disposition = "not_an_issue"
    finding.disposition_note = "assessment lags market in this county"
    await db_session.flush()

    async def reworded(_payload: str):
        return _drafts("A different sentence about the very same two figures")

    (after,) = await refresh_snapshot_findings(
        db_session,
        loan_file_id=loan_file.id,
        snapshot=_snapshot(valuation="551923"),
        reasoner=reworded,
    )

    assert after.disposition == "not_an_issue"
    assert after.disposition_note == "assessment lags market in this county"
    assert (
        after.title == "A different sentence about the very same two figures"
    )  # wording refreshes


async def _sees(_payload: str):
    return _drafts()


async def _sees_nothing(_payload: str):
    return []


async def test_an_open_finding_the_model_no_longer_sees_shows_as_resolved(
    db_session: AsyncSession,
) -> None:
    """FEEDBACK, not silence. Deleting outright is honest about the current file but tells a
    processor nothing: they upload the appraisal and the finding simply vanishes, indistinguishable
    from a bug. Resolved says the file moved and this is why."""
    loan_file = await _file(db_session, "gone")

    await refresh_snapshot_findings(
        db_session, loan_file_id=loan_file.id, snapshot=_snapshot(), reasoner=_sees
    )
    (after,) = await refresh_snapshot_findings(
        db_session,
        loan_file_id=loan_file.id,
        snapshot=_snapshot(valuation="551923"),
        reasoner=_sees_nothing,
    )

    assert after.disposition == "resolved"


async def test_a_resolved_finding_clears_on_the_next_change(db_session: AsyncSession) -> None:
    """ONE run, not forever. It survives exactly as long as the snapshot that resolved it — long
    enough to be seen, not long enough to silt the tab up with old good news."""
    loan_file = await _file(db_session, "cleared")

    await refresh_snapshot_findings(
        db_session, loan_file_id=loan_file.id, snapshot=_snapshot(), reasoner=_sees
    )
    await refresh_snapshot_findings(
        db_session,
        loan_file_id=loan_file.id,
        snapshot=_snapshot(valuation="551923"),
        reasoner=_sees_nothing,
    )
    remaining = await refresh_snapshot_findings(
        db_session,
        loan_file_id=loan_file.id,
        snapshot=_snapshot(valuation="540000"),
        reasoner=_sees_nothing,
    )

    assert remaining == []


async def test_a_resolved_finding_that_comes_back_reopens(db_session: AsyncSession) -> None:
    """THE CASE THAT IS EASY TO MISS. `resolved` is the SYSTEM's label, not the processor's — and
    seeing the finding again means it did not stay resolved. Leaving the label on a live finding
    would tell a processor something was fixed while it sits in front of them."""
    loan_file = await _file(db_session, "reopened")

    await refresh_snapshot_findings(
        db_session, loan_file_id=loan_file.id, snapshot=_snapshot(), reasoner=_sees
    )
    await refresh_snapshot_findings(
        db_session,
        loan_file_id=loan_file.id,
        snapshot=_snapshot(valuation="551923"),
        reasoner=_sees_nothing,
    )
    (back,) = await refresh_snapshot_findings(
        db_session,
        loan_file_id=loan_file.id,
        snapshot=_snapshot(valuation="540000"),
        reasoner=_sees,
    )

    assert back.disposition == "open"


async def test_a_resolved_finding_is_retained_even_when_no_longer_seen(
    db_session: AsyncSession,
) -> None:
    """A processor's action is a record. Deleting it the first time the file moved would erase their
    work — the same reason the older cross-source layer retains resolved findings (ADR-061)."""
    loan_file = await _file(db_session, "retained")

    async def sees(_payload: str):
        return _drafts()

    async def sees_nothing(_payload: str):
        return []

    (finding,) = await refresh_snapshot_findings(
        db_session, loan_file_id=loan_file.id, snapshot=_snapshot(), reasoner=sees
    )
    finding.disposition = "signed_off"
    await db_session.flush()

    remaining = await refresh_snapshot_findings(
        db_session,
        loan_file_id=loan_file.id,
        snapshot=_snapshot(valuation="551923"),
        reasoner=sees_nothing,
    )

    assert [f.disposition for f in remaining] == ["signed_off"]


# --------------------------------------------------------------------------------------------- #
# LP-589 — the cache cases the first version got backwards
# --------------------------------------------------------------------------------------------- #


async def test_a_file_with_no_findings_is_not_re_asked(db_session: AsyncSession) -> None:
    """THE CASE THE ORIGINAL COMMENT CLAIMED TO HANDLE AND DID NOT. The guard was
    `existing and all(...)`, and `existing` is falsy when the model found nothing — so a clean file
    re-asked on every run, forever, paying for a full call each time and discarding it."""
    loan_file = await _file(db_session, "quiet")
    calls = 0

    async def finds_nothing(_payload: str):
        nonlocal calls
        calls += 1
        return []

    await refresh_snapshot_findings(
        db_session, loan_file_id=loan_file.id, snapshot=_snapshot(), reasoner=finds_nothing
    )
    await refresh_snapshot_findings(
        db_session, loan_file_id=loan_file.id, snapshot=_snapshot(run=7), reasoner=finds_nothing
    )

    assert calls == 1, "a file with nothing to report was re-asked about an unchanged snapshot"


async def test_a_retained_disposition_does_not_break_the_cache(db_session: AsyncSession) -> None:
    """A finding a processor signed off, which the model later stopped seeing, kept its OLD
    fingerprint — so `all(...)` never held again and the file re-asked forever after. Because the
    model's answer differs between calls, the tab then moved on a file that had not changed."""
    loan_file = await _file(db_session, "retainedcache")
    calls = 0

    async def counting(_payload: str):
        nonlocal calls
        calls += 1
        return _drafts() if calls == 1 else []

    (finding,) = await refresh_snapshot_findings(
        db_session, loan_file_id=loan_file.id, snapshot=_snapshot(), reasoner=counting
    )
    finding.disposition = "not_an_issue"
    await db_session.flush()

    # snapshot B: the model no longer sees it, so the row is RETAINED with its old fingerprint
    await refresh_snapshot_findings(
        db_session,
        loan_file_id=loan_file.id,
        snapshot=_snapshot(valuation="551923"),
        reasoner=counting,
    )
    # snapshot B again, unchanged — this must be a cache hit
    await refresh_snapshot_findings(
        db_session,
        loan_file_id=loan_file.id,
        snapshot=_snapshot(valuation="551923", run=9),
        reasoner=counting,
    )

    assert calls == 2, "a retained disposition kept the file re-asking on an unchanged snapshot"


async def test_two_drafts_with_the_same_key_do_not_break_the_run(db_session: AsyncSession) -> None:
    """`finding_key` ignores the wording by design, so two drafts describing one pairing in
    different words COLLIDE — ordinary model output. Both missed the lookup, both were inserted, and
    the flush raised IntegrityError on the unique constraint. That does not degrade gracefully: it
    poisons the session, so the caller's own commit raises PendingRollbackError and the rule
    findings, the persisted snapshot and the COMPLETED status roll back with it."""
    loan_file = await _file(db_session, "collide")

    async def says_it_twice(_payload: str):
        first = _drafts("One phrasing")[0]
        second = _drafts("A different phrasing of the very same pairing")[0]
        return [first, second]

    rows = await refresh_snapshot_findings(
        db_session, loan_file_id=loan_file.id, snapshot=_snapshot(), reasoner=says_it_twice
    )

    assert len(rows) == 1


async def test_reopening_keeps_the_note_the_processor_wrote(db_session: AsyncSession) -> None:
    """LP-589 — ABSENT IS NOT "CLEAR IT". The endpoint assigned `body.note` unconditionally and Reopen
    sends none, so someone who signed off with an explanation and later reopened lost it silently and
    unrecoverably. Asserted at the service level here; the route now only assigns when a note is
    actually supplied."""
    loan_file = await _file(db_session, "note")

    async def sees(_payload: str):
        return _drafts()

    (finding,) = await refresh_snapshot_findings(
        db_session, loan_file_id=loan_file.id, snapshot=_snapshot(), reasoner=sees
    )
    finding.disposition = "signed_off"
    finding.disposition_note = "confirmed with the county assessor"
    await db_session.flush()

    # What Reopen does: change the disposition, supply no note.
    finding.disposition = "open"
    await db_session.flush()

    assert finding.disposition_note == "confirmed with the county assessor"
