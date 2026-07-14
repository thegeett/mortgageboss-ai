"""The observation channel + graduation service (LP-320).

The channel: record a structured Observation for a document/fact OUTSIDE the tag vocabulary — never
inventing a formal tag, never dropping the info — and, in the same step, bump the graduation tally
so recurring unknowns rank for a human to formalize. The INFORM-not-RESOLVE boundary is STRUCTURAL:
nothing here touches the rule engine, so an observation can never flip a finding's verdict. It can
only ATTACH to a finding (fail-closed to human review) and be surfaced by a query.

``record_observation`` is the pure channel (persist + graduation). ``observe_unmapped`` wraps the AI
step (:mod:`app.ai.observation`, injected Reasoner seam) and GUARANTEES an observation even when the
AI fails — a novel document is never silently dropped.
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.observation import AIClientError, ObservationResult, reason_observation
from app.core.logging import get_logger
from app.models.base import utcnow
from app.models.observation import GraduationCandidate, Observation
from app.models.types import MEDIUM_STRING, SHORT_STRING

logger = get_logger(__name__)

# Injected so a keyless test supplies a deterministic stub (the same seam as Stage A/B / the judges).
Reasoner = Callable[[str], Awaitable[ObservationResult]]

# Fold separators (spaces / hyphens) to the snake separator, then drop anything not [a-z0-9_].
_SIGNATURE_SEP = re.compile(r"[\s\-]+")
_SIGNATURE_STRIP = re.compile(r"[^a-z0-9_]+")
_SIGNATURE_UNDERSCORES = re.compile(r"_+")

# The observation_type column is String(SHORT_STRING); relates_to_subject is String(MEDIUM_STRING).
# The AI chooses these as FREE TEXT, so they must be clamped to the column widths before persist —
# an over-long label must never raise a DataError and drop the observation (the channel's whole
# guarantee is that a novel document is captured, never dropped).
_TYPE_MAX = SHORT_STRING
_SUBJECT_MAX = MEDIUM_STRING

# The fallback observation for a novel document the AI could not structure — the info is STILL
# captured (never dropped) and flagged for a human.
_FALLBACK_TYPE = "unclassified_document"


def graduation_signature(observation_type: str) -> str:
    """Canonical ``[a-z0-9_]`` signature for an observation type — lowercase, fold spaces/hyphens to
    ``_``, drop other characters, collapse ``_`` runs.

    Unifies underscore/space/hyphen variants of ONE concept so the cross-run tally doesn't fragment
    (``gift-letter`` / ``gift letter`` / ``gift_letter`` → one signature), and bounds the cross-tenant
    signature to a snake_case-ish shape (it drops free-form punctuation but, being a model-chosen
    label, is not a hard PII guarantee — the prompt steers toward generic categories).
    """
    lowered = observation_type.strip().lower()
    folded = _SIGNATURE_SEP.sub("_", lowered)
    cleaned = _SIGNATURE_STRIP.sub("", folded)
    return _SIGNATURE_UNDERSCORES.sub("_", cleaned).strip("_")


async def _bump_graduation(db: AsyncSession, observation_type: str) -> None:
    """Increment the graduation tally for this observation TYPE (PII-safe — type + count only).

    Atomic upsert on the unique signature: first sighting inserts (occurrences=1), a recurrence
    increments and bumps ``updated_at`` (= last seen). Core insert bypasses ORM defaults, so id +
    timestamps are set explicitly.
    """
    signature = graduation_signature(observation_type)
    now = utcnow()
    stmt = (
        pg_insert(GraduationCandidate)
        .values(
            id=uuid4(),
            signature=signature,
            observation_type=observation_type,
            occurrences=1,
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_update(
            index_elements=["signature"],
            set_={
                "occurrences": GraduationCandidate.occurrences + 1,
                "updated_at": now,  # last seen
            },
        )
    )
    await db.execute(stmt)


async def record_observation(
    db: AsyncSession,
    *,
    loan_file_id: UUID,
    run_id: UUID,
    about: str,
    observation_type: str,
    value: str,
    structured: dict[str, Any] | None = None,
    relates_to_finding_id: UUID | None = None,
    relates_to_subject: str | None = None,
    confidence: float | None = None,
    reasoning: str | None = None,
    produced_by: str = "ai",
    needs_tag: bool = False,
) -> Observation:
    """Record ONE structured observation + bump its graduation tally (flush-only).

    This is the channel: the info is captured (never dropped) and never becomes a formal tag or a
    finding resolution. ``relates_to_finding_id`` attaches it to a finding for human review — but the
    rule engine does not read observations, so it cannot change that finding's verdict.

    The AI-chosen ``observation_type`` / ``relates_to_subject`` are clamped to their column widths so
    an over-long model label degrades to a truncated-but-recorded observation, never a DataError that
    would drop the novel document.
    """
    observation_type = observation_type[:_TYPE_MAX]
    if relates_to_subject is not None:
        relates_to_subject = relates_to_subject[:_SUBJECT_MAX]
    observation = Observation(
        loan_file_id=loan_file_id,
        run_id=run_id,
        about=about,
        observation_type=observation_type,
        value=value,
        structured=structured or {},
        relates_to_finding_id=relates_to_finding_id,
        relates_to_subject=relates_to_subject,
        confidence=confidence,
        reasoning=reasoning,
        produced_by=produced_by,
        needs_tag=needs_tag,
    )
    db.add(observation)
    await _bump_graduation(db, observation_type)
    await db.flush()
    return observation


async def observe_unmapped(
    db: AsyncSession,
    *,
    loan_file_id: UUID,
    run_id: UUID,
    about: str,
    context: dict[str, Any],
    relates_to_finding_id: UUID | None = None,
    reasoner: Reasoner | None = None,
) -> Observation:
    """Structure an unmapped document/fact into an observation (ALWAYS records one).

    Calls the AI to structure the unknown; on ANY failure (transport, truncation, malformed) it still
    records a minimal fallback observation flagged ``needs_tag`` — a novel document is NEVER silently
    dropped (§7 discovery output). Returns the recorded observation.
    """
    reason_fn = reasoner if reasoner is not None else reason_observation
    read = None
    try:
        result = await reason_fn(json.dumps(context))
        if not result.truncated:
            read = result.read
    except AIClientError:
        logger.warning("observe_unmapped_ai_failed", about=about)

    if read is None:
        # Fail-closed: capture the novel document anyway, flagged for a human.
        return await record_observation(
            db,
            loan_file_id=loan_file_id,
            run_id=run_id,
            about=about,
            observation_type=_FALLBACK_TYPE,
            value="a novel/unclassified document was found but could not be structured — human review needed",
            structured={},
            relates_to_finding_id=relates_to_finding_id,
            needs_tag=True,
        )
    return await record_observation(
        db,
        loan_file_id=loan_file_id,
        run_id=run_id,
        about=about,
        observation_type=read.observation_type,
        value=read.value,
        structured=read.structured,
        relates_to_finding_id=relates_to_finding_id,
        relates_to_subject=read.relates_to_subject,
        confidence=read.confidence,
        reasoning=read.reasoning,
        needs_tag=read.needs_tag,
    )


async def top_graduation_candidates(
    db: AsyncSession, *, limit: int = 20
) -> list[GraduationCandidate]:
    """The recurring unknowns ranked by frequency — what the vocabulary is missing most.

    This is the human/Priya review input: the most-frequent candidates are the next tags+rules to
    formalize. Ranked by occurrences (desc), then most-recently-seen.
    """
    result = await db.execute(
        select(GraduationCandidate)
        .order_by(GraduationCandidate.occurrences.desc(), GraduationCandidate.updated_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def observations_for_finding(db: AsyncSession, finding_id: UUID) -> list[Observation]:
    """The observations attached to a finding (fail-closed review context for the processor)."""
    result = await db.execute(
        select(Observation)
        .where(Observation.relates_to_finding_id == finding_id)
        .order_by(Observation.created_at)
    )
    return list(result.scalars().all())


async def pending_review_observations(db: AsyncSession, *, loan_file_id: UUID) -> list[Observation]:
    """A file's observations that FAIL CLOSED to human review — needs_tag, or attached to a finding.

    These are the structured contexts a human must see even though no formal tag/rule handles them
    yet: the observation channel surfacing to the processor, day one.
    """
    result = await db.execute(
        select(Observation)
        .where(
            Observation.loan_file_id == loan_file_id,
            (Observation.needs_tag.is_(True)) | (Observation.relates_to_finding_id.isnot(None)),
        )
        .order_by(Observation.created_at)
    )
    return list(result.scalars().all())


__all__ = [
    "Reasoner",
    "graduation_signature",
    "observations_for_finding",
    "observe_unmapped",
    "pending_review_observations",
    "record_observation",
    "top_graduation_candidates",
]
