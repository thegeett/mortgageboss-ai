"""Snapshot persistence (LP-209, ADR-246) — immutable, insert-only, per run.

``persist_snapshot`` writes a built LP-204 ``Snapshot`` as one immutable
``snapshot_records`` row; ``load_snapshot`` reads it back to the frozen Snapshot.
It does NOT build snapshots (LP-208 does) and never mutates a prior row.

* **Insert-only, write-once.** A second persist for the same ``run_id`` raises
  ``SnapshotAlreadyPersisted`` — a run's snapshot is never overwritten (the DB
  UNIQUE is the real guard; the raise is the clear signal). A NEW ``run_id`` → a
  NEW row; prior rows are untouched (append-only history — the jump-back-to-a-
  previous-run guarantee). There is no update path anywhere.
* **PII-clean-at-rest guard (the last line of defense).** Before the insert the
  serialized snapshot is scanned for RAW PII — a dashed SSN or a long bare digit
  run that should have been masked. If any is found the write **fails loudly**
  (``RawPiiAtRestError``): a raw SSN at rest is the worst outcome, so a leaking
  snapshot is never stored. This guards against an upstream assembler bug; it does
  not re-mask (masking is the assemblers' job).
"""

from __future__ import annotations

import re
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.snapshot_record import SnapshotRecord
from app.verification.snapshot.model import Snapshot

# A raw dashed SSN (``123-45-6789``). A MASKED SSN is ``***-**-1234`` — the
# asterisks mean this never matches a masked display.
_RAW_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")

# A bare run of 9+ digits as a standalone JSON token — an unmasked SSN-without-
# dashes or an account number. ``\b`` bounds it to a token, so it does NOT match a
# hex ``match_hash`` (digit runs there are surrounded by hex letters, no word
# boundary). The trailing ``(?!\.\d)`` excludes the integer part of a decimal number,
# so a legitimate large money amount (``"123456789.00"`` — a $123M+ value) does NOT
# trip the guard and abort the whole persist; a bare-integer id ("123456789", no
# decimal) is still caught. Residual: a whole-dollar amount ≥ 9 digits with no cents
# ("123456789") would still trip — rare, and safer to over-flag than to leak.
_LONG_DIGITS = re.compile(r"\b\d{9,}\b(?!\.\d)")


class SnapshotAlreadyPersisted(Exception):
    """Raised when a snapshot already exists for this run_id (write-once)."""


class RawPiiAtRestError(Exception):
    """Raised when a snapshot about to be written contains RAW (unmasked) PII."""


def _assert_no_raw_pii(serialized: str) -> None:
    """Fail loudly if the serialized snapshot carries raw PII (the at-rest guard)."""
    if _RAW_SSN.search(serialized):
        raise RawPiiAtRestError("refusing to persist: a raw SSN pattern is present in the snapshot")
    if _LONG_DIGITS.search(serialized):
        raise RawPiiAtRestError(
            "refusing to persist: a long bare digit run (unmasked account/SSN) is present"
        )


async def persist_snapshot(db: AsyncSession, snapshot: Snapshot) -> SnapshotRecord:
    """Persist a built Snapshot as one immutable row (flush-only; caller commits).

    Raises :class:`SnapshotAlreadyPersisted` if the run already has a snapshot, and
    :class:`RawPiiAtRestError` if the serialized snapshot contains raw PII (the write
    is refused — nothing is inserted).
    """
    # PII-clean-at-rest: scan the canonical serialization before touching the DB.
    _assert_no_raw_pii(snapshot.model_dump_json())

    existing = await db.scalar(
        select(SnapshotRecord.id).where(SnapshotRecord.run_id == snapshot.run_id)
    )
    if existing is not None:
        raise SnapshotAlreadyPersisted(f"snapshot already persisted for run {snapshot.run_id}")

    record = SnapshotRecord(
        run_id=snapshot.run_id,
        loan_file_id=snapshot.loan_file_id,
        created_at=snapshot.created_at,
        snapshot_version=snapshot.snapshot_version,
        # Store the full blob verbatim (dict); load reconstructs via model_validate.
        snapshot_json=snapshot.model_dump(mode="json"),
    )
    db.add(record)
    await db.flush()
    return record


async def load_snapshot(db: AsyncSession, run_id: UUID) -> Snapshot | None:
    """Load a persisted snapshot for a run, or ``None`` if there is none."""
    record = await db.scalar(select(SnapshotRecord).where(SnapshotRecord.run_id == run_id))
    if record is None:
        return None
    return Snapshot.model_validate(record.snapshot_json)


async def load_snapshots_for_loan_file(db: AsyncSession, loan_file_id: UUID) -> list[Snapshot]:
    """Load every persisted snapshot for a loan file, newest build first (history)."""
    records = (
        (
            await db.execute(
                select(SnapshotRecord)
                .where(SnapshotRecord.loan_file_id == loan_file_id)
                .order_by(SnapshotRecord.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return [Snapshot.model_validate(r.snapshot_json) for r in records]
