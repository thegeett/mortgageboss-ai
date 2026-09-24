"""Seed the shipped lender code maps into `lender_condition_codes` (LP-910, ADR-407).

Run: ``uv run python -m app.scripts.seed_lender_codes``

IDEMPOTENT. Every row is keyed `(lender_id, code)` — the table's own unique index — so a re-run
updates the shipped fields and leaves everything else alone. Safe to run on every deploy.

⚠️ IT MATCHES ON `canonical_lender_key`, AND NEVER ON THE SLUG. This is the STOP AND ASK the survey
raised and the product owner answered (option 1, 2026-09-23). `lenders` is company-scoped with a slug
unique only per company (ADR-045), each company choosing its own — so "UWM" may be `uwm`,
`uwm-wholesale`, `united-wholesale` or absent, and two companies' UWM rows are two different
`lender_id`s. A seed keyed on a slug matches nothing on some tenants and THE WRONG ROW on others,
which is worse: it would attach UWM's code meanings to a different lender's conditions, and nothing
downstream could tell.

So a lender with `canonical_lender_key` unset is SKIPPED AND REPORTED, never guessed at. That is not
a failure state — its codes simply arrive as `OBSERVED_UNMAPPED` on first import, which is the same
path any unknown code takes, and an admin sets the key when they want the map.

WHAT A RE-RUN DOES NOT TOUCH. `times_seen`, `first_seen_at` and `last_seen_at` are the import path's
to maintain, and `status` is only ever raised from `OBSERVED_UNMAPPED` to `SEEDED` — never lowered.
A code a person has already MAPPED keeps that status: the seed is shipped data, and a human decision
outranks it.
"""

import asyncio
from dataclasses import dataclass
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.conditions.lender_codes import LenderCodeRow, load_seed, seeded_lender_keys
from app.conditions.lender_codes.status import resolved_status
from app.core.database import async_session_maker
from app.models.helpers import only_active
from app.models.lender import Lender
from app.models.lender_condition_code import LenderCodeStatus, LenderConditionCode

logger = structlog.get_logger(__name__)


@dataclass
class SeedResult:
    """What one run did, per lender key. Counts only — never a condition or a borrower fact."""

    matched_lenders: int = 0
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    #: Lender keys this build ships a map for that no lender row claims. Reported rather than
    #: raised: on a fresh database that is every key, and on a real one it is the admin's cue.
    unclaimed_keys: tuple[str, ...] = ()

    def changed(self) -> bool:
        return bool(self.inserted or self.updated)


async def _lenders_for_key(db: AsyncSession, key: str) -> list[Lender]:
    """Every active lender across every company that declares this canonical key.

    NOT scoped to one company, deliberately, and this is the one place in the codebase where that is
    right: the code map is shipped reference data about a LENDER, not about a loan file, and each
    company working with UWM needs its own copy against its own `lender_id`. The rows it writes are
    still per-lender and therefore per-company by construction (ADR-407).
    """
    stmt = select(Lender).where(Lender.canonical_lender_key == key)
    return list(await db.scalars(only_active(stmt, Lender)))


async def _upsert(db: AsyncSession, *, lender_id: UUID, row: LenderCodeRow) -> str:
    """Insert or refresh one `(lender, code)`. Returns "inserted" / "updated" / "unchanged"."""
    existing = await db.scalar(
        select(LenderConditionCode).where(
            LenderConditionCode.lender_id == lender_id,
            LenderConditionCode.code == row.code,
        )
    )
    if existing is None:
        db.add(
            LenderConditionCode(
                lender_id=lender_id,
                code=row.code,
                label=row.label,
                canonical_type_id=row.canonical_type_id,
                default_bucket_kind=row.default_bucket_kind,
                default_owner_hint=row.default_owner_hint,
                info_only=row.info_only,
                status=LenderCodeStatus.SEEDED,
            )
        )
        await db.flush()
        return "inserted"

    # ⚠️ THE ORDER HERE IS LOAD-BEARING, and it is a shape rather than a defect today. `before` is
    # captured, every field is then ASSIGNED, and `after` is compared — so the "unchanged" return
    # below hands back an object that has already been written to. That is harmless while equality
    # is identity (SQLAlchemy sees no net change and emits no UPDATE), and stops being harmless the
    # moment a field is compared non-trivially — a normalised label, a JSON blob, anything where
    # `==` can be True for values that are not the same object. Then "unchanged" would leave a dirty
    # instance for the caller's commit to write. Assign into locals and compare before mutating if
    # that day comes; until then this comment is the warning.
    before = (
        existing.label,
        existing.canonical_type_id,
        existing.default_bucket_kind,
        existing.default_owner_hint,
        existing.info_only,
        existing.status,
    )
    existing.label = row.label
    existing.canonical_type_id = row.canonical_type_id
    existing.default_bucket_kind = row.default_bucket_kind
    existing.default_owner_hint = row.default_owner_hint
    existing.info_only = row.info_only
    # RAISED, NEVER LOWERED. A code a person has reviewed is MAPPED, and shipped data does not
    # demote a human decision back to SEEDED. An OBSERVED_UNMAPPED row that the seed now explains
    # becomes SEEDED, which is the case this exists for.
    #
    # ⚠️ THE RULE MOVED OUT OF THIS FILE AND THIS IS NOW ITS SECOND CALLER, NOT ITS OWNER (LP-909
    # review). It lived here as a local promotion — correct while the seed was the ONLY writer of
    # these rows. LP-909's import is the second, and one rule stated independently in two places is
    # how the two drift. `resolved_status` is the single statement; this line applies it.
    existing.status = resolved_status(existing.status, LenderCodeStatus.SEEDED)

    after = (
        existing.label,
        existing.canonical_type_id,
        existing.default_bucket_kind,
        existing.default_owner_hint,
        existing.info_only,
        existing.status,
    )
    if before == after:
        return "unchanged"
    await db.flush()
    return "updated"


async def seed_lender_codes(db: AsyncSession) -> SeedResult:
    """Apply every shipped map to every lender that claims its key. Flushes; the caller commits.

    Separated from the CLI below so a test can drive it against a session with no database of its
    own — the same split `load_rules.py` uses.
    """
    result = SeedResult()
    unclaimed: list[str] = []

    for key in seeded_lender_keys():
        rows = load_seed(key)
        lenders = await _lenders_for_key(db, key)
        if not lenders:
            unclaimed.append(key)
            continue
        result.matched_lenders += len(lenders)
        for lender in lenders:
            for row in rows:
                outcome = await _upsert(db, lender_id=lender.id, row=row)
                setattr(result, outcome, getattr(result, outcome) + 1)

    result.unclaimed_keys = tuple(unclaimed)
    return result


async def _run() -> SeedResult:
    async with async_session_maker() as db:
        result = await seed_lender_codes(db)
        await db.commit()
        return result


def main() -> None:
    result = asyncio.run(_run())
    # COUNTS AND KEYS ONLY — never a label, a code's meaning, or anything about a loan file.
    logger.info(
        "lender_code_seed_complete",
        matched_lenders=result.matched_lenders,
        inserted=result.inserted,
        updated=result.updated,
        unchanged=result.unchanged,
        unclaimed_keys=list(result.unclaimed_keys),
    )
    verb = "applied changes" if result.changed() else "no changes (already in sync)"
    print(
        f"Lender code seed {verb}: {result.matched_lenders} lender(s) matched, "
        f"+{result.inserted} / ~{result.updated} / ={result.unchanged}"
    )
    if result.unclaimed_keys:
        print(
            "No lender claims these shipped keys: "
            + ", ".join(result.unclaimed_keys)
            + ". Set `lenders.canonical_lender_key` on the matching lender to seed them; until "
            "then those codes arrive as OBSERVED_UNMAPPED on first import, which is not an error."
        )


if __name__ == "__main__":
    main()
