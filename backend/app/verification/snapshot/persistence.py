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
  snapshot is scanned for RAW PII — a dashed SSN or a long bare digit run that
  should have been masked. If any is found the write **fails loudly**
  (``RawPiiAtRestError``): a raw SSN at rest is the worst outcome, so a leaking
  snapshot is never stored. This guards against an upstream assembler bug; it does
  not re-mask (masking is the assemblers' job). The scan walks the DECODED document
  and the error NAMES THE PATH (never the value) — LP-509-C1, where a refusal that
  said only "a long bare digit run is present" left a loan file with no snapshot,
  no persisted tag values and no way to tell which field was responsible.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from typing import Any
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
#
# NOTE (LP review): this is a DELIBERATE over-flag. A legitimate ≥9-digit identifier
# riding in a plain ``Field.value`` — an insurance policy / member number, an
# un-hyphenated 9-digit ZIP+4 — will also trip and refuse the persist. That is the
# accepted trade (a raw account/SSN at rest is the worse outcome) and is pinned by
# ``test_raw_account_number_run_is_rejected``. A raw account is only distinguishable
# from a legit identifier by which field carries it, not by pattern.
#
# LP-509-C1 did NOT narrow it. The over-flag stands exactly as described above:
# deciding which ≥9-digit identifiers are safe at rest is a per-field data decision,
# not a pattern one, and guessing it would trade a loud failure for a silent leak.
# What changed is only that the refusal now NAMES THE FIELD, so such a case can be
# identified and routed through ``_PII_FIELDS`` — instead of costing the whole loan
# file its snapshot with no indication of which field was responsible.
_LONG_DIGITS = re.compile(r"\b\d{9,}\b(?!\.\d)")


def refuses_at_rest(text: str) -> str | None:
    """Why this value could not be persisted in a snapshot, or None if it can.

    EXPORTED so a value can be refused where a PERSON types it, rather than at the
    end of the next verification run. LP-703 opened a hand-typed path into
    `Field.value`, and a processor typing the parcel number off a title commitment
    — a ten-digit run, on a field `_PII_FIELDS` does not route — aborted the whole
    loan file's snapshot write from then on. Nineteen offerable fields across five
    document types have that shape. One person, one field, one keystroke, and every
    subsequent run persisted nothing.

    THE SAME FUNCTION the persist guard applies, not the same two patterns restated.
    An earlier version repeated the patterns here with a comment saying the two must
    not disagree — and they did, because the guard also skipped uuids and this did
    not. Sharing the code is the only form of that promise which cannot rot.
    """
    scannable = _without_uuids(text)
    if _RAW_SSN.search(scannable):
        return "a dashed SSN pattern"
    found = _LONG_DIGITS.search(scannable)
    return f"a {len(found.group(0))}-digit run" if found is not None else None


class SnapshotAlreadyPersisted(Exception):
    """Raised when a snapshot already exists for this run_id (write-once)."""


class RawPiiAtRestError(Exception):
    """Raised when a snapshot about to be written contains RAW (unmasked) PII."""


# A CANONICAL UUID — skipped, and this one is not a precaution but a fix (LP-509-C1).
#
# A uuid4 renders as five hyphen-separated hex groups, and the last is TWELVE characters bounded by
# a hyphen and a quote. When those twelve happen to be all decimal — about 1 uuid in 281 — that is a
# 12-digit run between two non-word characters, which is precisely the shape of an unmasked account
# number. The guard then refused the write.
#
# THE STABLE IDS ARE WHAT MAKE THIS SEVERE. ``run_id`` varies per run, so it only ever cost a run.
# ``loan_file_id`` and the borrower ids do NOT vary: a loan file whose id draws such a uuid can
# never persist a snapshot, on any run, forever — no tag values, no observations, nothing to
# diagnose from, and (before this ticket) no indication of which field was responsible. Roughly 1-2%
# of loan files, decided by nothing but the luck of a uuid draw. Found by the path-naming above,
# which pointed straight at ``loan_file_id`` and ``run_id``.
#
# Matched by SHAPE rather than by key name, so every uuid is covered wherever it appears — borrower
# refs and subject keys included — and no leak can hide behind it: a 36-character canonical uuid is
# not a shape an SSN or an account number can take.
#
# UNANCHORED SINCE LP-705, and the anchors were the bug. ``\A…\Z`` matched a value that IS a uuid
# and not one that CONTAINS one, so ``f"debt.{liab.id}"`` — a DTI line key, prefix plus uuid — was
# scanned, and the uuid's own twelve-character tail was read as an account number. Measured over
# 2,000,000 samples: 0.354% of uuid4s carry a 9+ digit run, so roughly one stated liability in 283
# permanently refused its whole loan file's snapshot. ``f"income.{item.id}"`` has the same shape.
#
# WHY REMOVING IS STILL SAFE, restated for the wider match: substitution can only delete an exact
# 36-character canonical uuid, and neither pattern this guard applies can be hidden that way. An
# SSN carries hyphens at positions 3 and 6, a bare account number carries none — neither can
# contain, or be contained by, an 8-4-4-4-12 hex-with-hyphens run. The replacement is a SPACE
# rather than nothing, so removal can only ever create a word boundary, never close one: a leak
# written flush against an id (``<uuid>123456789``) is still caught.
#
# The other two derived ids need no exemption and get none: a ``content_id`` is LETTER-prefixed
# (``doc…`` / ``txn…``) and a ``match_hash`` is ``v1:<hex>``, so in both the digit run is preceded
# by a word character and ``\b`` never opens one. That prefix is deliberate and is pinned by
# ``test_content_ids_never_trip_the_pii_guard``.
#: DELIMITED, and the lookarounds are the whole safety of this skip.
#:
#: The argument for removing uuids was that neither leak pattern can be CONTAINED
#: by an 8-4-4-4-12 run. True, and not sufficient — a leak does not need to be
#: contained, only to OVERLAP. The final group is exactly 12 hex, so an undelimited
#: match will happily eat the first twelve digits of a longer run and leave the
#: remainder too short to report:
#:
#:     "aaaaaaaa-aaaa-aaaa-aaaa-4111111111111111"   a 16-digit card
#:      └────────── matched as a uuid ──────────┘   leaves "1111"
#:
#: That value was refused before this skip existed and was accepted after. Requiring
#: a non-alphanumeric on both sides costs nothing real — `debt.{id}` is preceded by
#: `.` and `income.{id}` likewise — and a uuid glued directly to more hex or more
#: digits is not a uuid the guard should be exempting anyway.
_UUID_ANYWHERE = re.compile(
    r"(?<![0-9a-zA-Z])[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(?![0-9a-zA-Z])",
    re.IGNORECASE,
)


def _without_uuids(text: str) -> str:
    """``text`` with every DELIMITED canonical uuid replaced by a space.

    The space is defence in depth rather than the thing that makes this safe. It
    was load-bearing when any uuid-shaped run was removed — `"12345<uuid>6789"`
    would have become a nine-digit leak with an empty replacement — but the
    lookarounds on :data:`_UUID_ANYWHERE` now reject a match with an alphanumeric
    on either side, so digits can never be adjacent to what is removed. Kept
    because it costs nothing and stops mattering only while those hold.
    """
    return _UUID_ANYWHERE.sub(" ", text)


#: At most this many offending paths are named in the error; the rest are counted.
_MAX_REPORTED = 10


def _walk_scalars(node: Any, path: str = "") -> Iterator[tuple[str, str, str]]:
    """Yield ``(path, key, text)`` for every scalar in the decoded snapshot document."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _walk_scalars(value, f"{path}.{key}" if path else str(key))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _walk_scalars(value, f"{path}[{index}]")
    elif node is not None and not isinstance(node, bool):
        yield path, path.rsplit(".", 1)[-1].split("[")[0], str(node)


def _assert_no_raw_pii(serialized: str) -> None:
    """Fail loudly if the serialized snapshot carries raw PII (the at-rest guard).

    STRUCTURAL, and the error NAMES THE FIELD (LP-509-C1). This used to regex the serialized blob
    and raise "a long bare digit run is present" — true, unactionable, and the reason LF-WCHG had
    zero persisted snapshots with nobody able to say which field was responsible. Losing the
    snapshot loses every per-document tag value the rules ran on, so an undiagnosable refusal here
    takes the whole file's observability with it.

    THE PATH IS REPORTED; THE VALUE NEVER IS. The message names the location and the shape of what
    was found (``a 12-digit run``), because this message goes to the logs and a guard against
    logging raw PII must not log raw PII itself.

    Still the same two patterns, still refusing the write outright. Two things changed: the scan
    walks the decoded document rather than its text, so a match can be attributed to a field; and
    canonical uuids are removed before scanning (see :data:`_UUID_ANYWHERE` — a self-inflicted
    refusal, not a leak). ``serialized`` must therefore be valid JSON, which the one production
    caller (``snapshot.model_dump_json()``) always passes.

    THE DECISION IS ``refuses_at_rest``'S, not a second copy of it. That function is also what the
    reviewer calls when a person types a value, and the two answering differently is the failure
    LP-703 opened and LP-705 found: a value accepted at the door and refused at the end of the run,
    or the reverse.
    """
    violations: list[str] = []
    for path, _key, text in _walk_scalars(json.loads(serialized)):
        if (reason := refuses_at_rest(text)) is not None:
            violations.append(f"{path} ({reason})")

    if not violations:
        return
    shown = ", ".join(sorted(violations)[:_MAX_REPORTED])
    extra = (
        "" if len(violations) <= _MAX_REPORTED else f", and {len(violations) - _MAX_REPORTED} more"
    )
    raise RawPiiAtRestError(
        "refusing to persist: unmasked account/SSN-shaped value(s) at "
        f"{shown}{extra}. Route the field through the documents section's PII map "
        "(_PII_FIELDS) so it is masked + hashed, rather than relaxing this guard."
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
