"""The dormant tag-layer smoke test (LP-378) — do the income/asset producers PRODUCE?

The orchestrator materializes only the AI groups a LIVE rule consumes (``_required_ai_groups()``), so the
income and asset structuring groups have never been requested, never run, never produced a tag on a real
file. The ~15 dormant income/asset rules are believed "gated on calibration" — but calibration measures a
tag's ACCURACY, presupposing it MATERIALIZES. This probe forces the dormant groups to run ONCE on a real file
and reports what they actually produce, BEFORE Priya's calibration time is spent (LP-379).

WHAT THIS IS: a read-only diagnostic. It runs OFF the normal path (``run_verification`` never imports this
module, so it cannot leak into a real verification), uses the REAL model (no stub unless one is injected for a
test), and PERSISTS NOTHING — no findings, no ``snapshot_records``, no reconcile. It builds a snapshot, runs
only the dormant groups via :func:`materialize_tags`, reads the produced tags off the returned (discarded)
snapshot, and returns a report.

WHAT THIS IS NOT: it does NOT prove the tags are CORRECT — a tag that produces a VALUE is not a tag that
produces the RIGHT value. That is calibration (LP-379), which this does not measure. This proves the pipe
carries water, not that the water is clean. A uniform-``unknown`` result is a REAL finding (a producer /
applicability gap), not a pass — the report surfaces the distribution honestly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.loan_file import LoanFile
from app.services.verification_run import required_ai_groups
from app.verification.snapshot.builder import build_snapshot
from app.verification.snapshot.model import Snapshot
from app.verification.tag_materialization.ai import AI_CALL_FAILURE_REASONS, Reasoner
from app.verification.tag_materialization.declarations import load_ai_groups
from app.verification.tag_materialization.producer import materialize_tags

_UNKNOWN = "unknown"


def dormant_ai_groups() -> frozenset[str]:
    """The AI groups NOT exercised by any LIVE rule — every declared group minus ``_required_ai_groups()``.

    Derived from the SAME single source the normal run uses, so the dormant set is exactly the complement of
    what a real verification materializes (this probe can never disagree with the orchestrator about which
    groups are live)."""
    return frozenset(load_ai_groups()) - required_ai_groups()


@dataclass(frozen=True)
class TagObservation:
    """One (document, tag) the probe saw — the tag's value + the model's own words (LP-334: the evidence)."""

    content_id: str
    document_type: str | None
    tag_id: str
    value: str
    confidence: float | None
    reasoning: str
    produced_by: str

    @property
    def is_unknown(self) -> bool:
        return self.value == _UNKNOWN


@dataclass(frozen=True)
class GroupProbe:
    """One dormant group's real-data behaviour: what it produced, on which doc-types, or an AI-call failure."""

    key: str
    subject: str
    tag_ids: tuple[str, ...]
    observations: list[TagObservation] = field(default_factory=list)

    @property
    def real(self) -> list[TagObservation]:
        """Observations with a real (non-``unknown``) value — the "it produced usable data" set."""
        return [o for o in self.observations if not o.is_unknown]

    @property
    def ai_failures(self) -> list[TagObservation]:
        """Observations that are ``unknown`` because the AI CALL failed (transport / truncated), NOT a
        genuine model abstention. Surfaced separately so an outage is never misread as a producer gap —
        the misdiagnosis this probe exists to prevent (materialize_tags degrades a failed call to
        ``unknown`` rather than raising, so the reason string is the only signal)."""
        return [o for o in self.observations if o.reasoning in AI_CALL_FAILURE_REASONS]

    @property
    def abstentions(self) -> list[TagObservation]:
        """Genuine model abstentions (``unknown`` from a completed call) — excludes AI-call failures."""
        return [
            o
            for o in self.observations
            if o.is_unknown and o.reasoning not in AI_CALL_FAILURE_REASONS
        ]

    @property
    def doctypes_with_real_value(self) -> set[str | None]:
        """The document types on which this group produced a real value — LP-377-D's gating input."""
        return {o.document_type for o in self.real}

    @property
    def verdict(self) -> str:
        """✅ produces_usable · ⚠️ mostly_abstains · ❌ produces_nothing · 🔌 ai_failed (the AI call
        failed — re-run / fix infra, NOT a producer gap)."""
        if not self.observations:
            return "produces_nothing"
        if not self.real:
            # No usable value: an AI-call failure (unreliable, re-run) is NOT a genuine abstention (a real
            # producer/data finding) — the report must not conflate them.
            return "ai_failed" if self.ai_failures else "mostly_abstains"
        # produced a real value somewhere; "mostly abstains" if the abstentions dominate heavily.
        return (
            "produces_usable"
            if len(self.real) >= max(1, len(self.observations) // 5)
            else "mostly_abstains"
        )


@dataclass(frozen=True)
class DormantProbeReport:
    groups: list[GroupProbe]


async def probe_dormant_groups_on_snapshot(
    snapshot: Snapshot, *, ai_reasoners: dict[str, Reasoner] | None = None
) -> DormantProbeReport:
    """Run ONLY the dormant AI groups over ``snapshot`` and report what they produce — pure, no DB, no writes.

    ``ai_reasoners=None`` → the REAL model runs for every dormant group (``materialize_tags`` resolves a
    ``None`` per-group reasoner to the production ``reason_ai_group``); a test injects stubs. The returned
    snapshot is READ then DISCARDED — nothing is persisted."""
    dormant = dormant_ai_groups()
    groups = load_ai_groups()
    # Scope materialization to exactly the SUBJECTS the dormant groups declare (today all "document", but
    # derived — never hardcoded), so a dormant group on ANY subject actually runs and is reported honestly,
    # rather than being silently scoped out and misreported "produces_nothing".
    subjects = frozenset(groups[key].subject for key in dormant)
    materialized = await materialize_tags(
        snapshot,
        ai_reasoners=ai_reasoners,
        only_subjects=subjects,
        only_groups=dormant,
    )
    doc_type_by_cid = {
        entry.content_id: entry.document_type
        for entry in (materialized.documents.entries if materialized.documents.is_present else [])
    }
    by_subject = {} if materialized.tags.absent else materialized.tags.by_subject

    probes: list[GroupProbe] = []
    for key in sorted(dormant):
        group = groups[key]
        observations: list[TagObservation] = []
        for content_id, tags in by_subject.items():
            for tag_id in group.tag_ids:
                tag = tags.get(tag_id)
                if tag is None:
                    continue
                observations.append(
                    TagObservation(
                        content_id=content_id,
                        document_type=doc_type_by_cid.get(content_id),
                        tag_id=tag_id,
                        value=str(tag.value),
                        confidence=tag.confidence,
                        reasoning=tag.reasoning or "",
                        produced_by=tag.produced_by.value,
                    )
                )
        probes.append(
            GroupProbe(
                key=key, subject=group.subject, tag_ids=group.tag_ids, observations=observations
            )
        )
    return DormantProbeReport(groups=probes)


async def probe_dormant_groups(
    db: AsyncSession,
    loan_file: LoanFile,
    *,
    ai_reasoners: dict[str, Reasoner] | None = None,
    run_id: UUID | None = None,
) -> DormantProbeReport:
    """Build the raw snapshot for ``loan_file`` (a READ) and probe the dormant groups over it. Persists
    nothing — ``build_snapshot`` reads the file, and the probe never writes."""
    snapshot = await build_snapshot(
        db, loan_file_id=loan_file.id, run_id=run_id or uuid4(), company_id=loan_file.company_id
    )
    return await probe_dormant_groups_on_snapshot(snapshot, ai_reasoners=ai_reasoners)


__all__ = [
    "DormantProbeReport",
    "GroupProbe",
    "TagObservation",
    "dormant_ai_groups",
    "probe_dormant_groups",
    "probe_dormant_groups_on_snapshot",
]
