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


async def test_an_open_finding_the_model_no_longer_sees_is_dropped(
    db_session: AsyncSession,
) -> None:
    """The list stays honest to the current file. An OPEN finding that is gone is gone."""
    loan_file = await _file(db_session, "gone")

    async def sees(_payload: str):
        return _drafts()

    async def sees_nothing(_payload: str):
        return []

    await refresh_snapshot_findings(
        db_session, loan_file_id=loan_file.id, snapshot=_snapshot(), reasoner=sees
    )
    remaining = await refresh_snapshot_findings(
        db_session,
        loan_file_id=loan_file.id,
        snapshot=_snapshot(valuation="551923"),
        reasoner=sees_nothing,
    )

    assert remaining == []


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
