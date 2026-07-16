"""The verification orchestrator (LP-321) — one full run over a loan file.

The single entry point that runs a FULL verification in dependency order:

    raw snapshot → Stage A tags → Stage B tags → (calculators) → (contradiction audit) → rules → findings

This is ASSEMBLY of the pieces already built (LP-312/313/314/315/316/318/319) — it owns ORDER,
DEGRADATION, and CACHING only, never tag/rule/calculator/finding logic. Two invariants:

* **Partial-snapshot semantics (§3D) — the system-level fail-closed.** A stage/step failure NEVER
  fails the whole run. A failed tag-production call degrades to absent/unknown-with-reason tags (the
  producers already fail-close per call); rules whose load-bearing tags are now degraded → the
  LP-315 gate routes them to couldnt_check; rules that do NOT depend on the failed tags STILL RUN.
  A wholesale stage exception is caught as a backstop (the pre-stage snapshot is kept). The
  SNAPSHOT/TAG/RULE pipeline always completes with a coherent result set, and what degraded is
  RECORDED (visible, not hidden). Two failures deliberately still PROPAGATE (they are not
  degradations): a rule producing an empty-reasoning verdict (§3D: a verdict must say WHY — fail
  loud), and finding persistence for a loan file that already has this run's findings (the LP-316
  unique index — a re-run of the SAME loan file collides until cross-run reconciliation lands).
  Snapshot persistence, by contrast, is best-effort (degrades). Cross-run reconciliation → LP-322.
* **Caching (§3D).** Tag production is cached by content fingerprint (LP-313/314): on a re-run, a
  tag whose source raw facts are unchanged is REUSED, not re-produced. The snapshot is rebuilt each
  run (stateless); only changed inputs trigger re-production. The run records the model + vocab
  version for reproducibility.

Deferred to LP-322: matching findings ACROSS runs (this ticket runs ONE verification).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from functools import cache
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.finding import Finding, FindingCategory
from app.services.rule_findings import ReconcileRunResult, reconcile_evaluation_findings
from app.services.tag_correlation import (
    Reasoner as StageBReasoner,
)
from app.services.tag_correlation import (
    SourcingCache,
    produce_stage_b_sourcing_tags,
)
from app.services.tag_production import (
    Reasoner as StageAReasoner,
)
from app.services.tag_production import (
    TransactionTagCache,
    produce_stage_a_transaction_tags,
)
from app.verification.rule_engine.consistency import Reasoner as ConsistencyReasoner
from app.verification.rule_engine.engine import DEFAULT_CONFIDENCE_FLOOR
from app.verification.rule_engine.enumerators import enumerate_subjects
from app.verification.rule_engine.judgment import Reasoner as Oc2Reasoner
from app.verification.rule_engine.registry import ACTIVE_RULE_IDS, evaluate_rules
from app.verification.rule_engine.result import RuleEvaluation
from app.verification.rules.specs import load_rule_spec
from app.verification.snapshot.builder import build_snapshot
from app.verification.snapshot.model import Snapshot, TagsSection
from app.verification.snapshot.persistence import persist_snapshot
from app.verification.snapshot.tag import Tag, TagProducedBy
from app.verification.tag_materialization.ai import AiTagCache
from app.verification.tag_materialization.ai import Reasoner as AiGroupReasoner
from app.verification.tag_materialization.declarations import ProductionMode, load_declarations
from app.verification.tag_materialization.producer import materialize_tags

# The subject families the generic materialization stage produces live (LP-326). The transaction
# Stage-A tags stay on their existing producer (their round-trip through the generic producer is
# proven separately) — this stage adds the id.* families keyed under the document / loan subjects, and
# (LP-332) the borrower subject (borrower-keyed citizenship + the per-borrower income shortfall), which
# activates ID-8 and IN-1 live.
_MATERIALIZED_SUBJECTS = frozenset({"document", "loan", "borrower"})


# Subject enumerations whose subjects are derived from the DOCUMENTS section (per-transaction /
# per-borrower / per-document). A rule on one of these that enumerated ZERO subjects this run did so
# for a DEGRADED reason (documents absent, or borrower/document resolution failed) — NOT "the subjects
# are gone" — so it must not retire a prior finding. ``loan`` is document-independent (always one
# subject) → always retire-eligible. Adding a new document-derived shape means adding its key here,
# and every rule that declares it is covered automatically (no per-rule-id list). LP-336 added
# ``per_account`` (accounts are grouped from the statement documents — zero accounts means no statements
# resolved, a degraded reason, not "the accounts are gone").
_DOCUMENT_DERIVED_ENUMERATIONS = frozenset(
    {"per_deposit", "per_borrower", "per_document", "per_account"}
)


def _load_bearing_tag_ids(rule_id: str) -> set[str]:
    """The tag ids a rule rests on — its evaluation block's load-bearing / gathered tags."""
    spec = load_rule_spec(rule_id)
    if spec.consistency is not None:
        tags = {spec.consistency.gather_tag}
        if spec.consistency.gather_filter is not None:
            tags.add(spec.consistency.gather_filter.tag)
        return tags
    if spec.deterministic is not None:
        return set(spec.deterministic.load_bearing_tags)
    if spec.judgment is not None:
        return set(spec.judgment.load_bearing_tags) | set(spec.judgment.reasoned_over)
    return set()


@cache
def _required_ai_groups() -> frozenset[str]:
    """The AI groups the ACTIVE rule set actually consumes (LP-326) — so the materialization stage
    runs ONLY those, never an AI structuring pass for a family no live rule reads yet.

    Derived generically from each active rule's load-bearing tags → their production declarations →
    the AI group each declares. A parsed/derived load-bearing tag contributes no AI group.
    """
    declarations = load_declarations()
    needed: set[str] = set()
    for rule_id in ACTIVE_RULE_IDS:
        for tag_id in _load_bearing_tag_ids(rule_id):
            decl = declarations.get(tag_id)
            if decl is not None and decl.mode is ProductionMode.AI:
                needed.add(decl.data)  # the AI group key
    return frozenset(needed)


logger = get_logger(__name__)

# The rule → finding-category map (which area of the file each rule concerns), a display lookup only.
# The set of rules that RAN is the registry's ACTIVE_RULE_IDS (the single source of truth) — NOT this
# map — so reconciliation's evaluated_rule_ids can never drift from what actually evaluated (a drift
# would drop a rule's priors and mint-collide on the uniqueness index). An unmapped rule falls back to
# a default category (cosmetic); a missing category never breaks reconciliation.
_RULE_CATEGORY: dict[str, FindingCategory] = {
    "AS-1": FindingCategory.ASSETS,
    "OC-2": FindingCategory.PROPERTY,
    "ID-2": FindingCategory.CROSS_SOURCE,  # identity facts compared across sources
    "ID-4": FindingCategory.CROSS_SOURCE,
    "ID-1": FindingCategory.CROSS_SOURCE,  # name across sources
    "ID-3": FindingCategory.CROSS_SOURCE,  # DOB across sources
    "ID-6": FindingCategory.DOCUMENTATION,  # 1003 completeness
    "ID-7": FindingCategory.DOCUMENTATION,  # marital/title vesting consistency
    "ID-9": FindingCategory.DOCUMENTATION,  # POA acceptability
}


@dataclass
class TagCaches:
    """The per-content-fingerprint tag caches (LP-313/314), threaded across runs for reuse.

    A caller reuses ONE bundle across re-runs: an unchanged input is a cache hit (the reasoner is
    not called again); only a changed document's entity re-produces. Mutated in place by the
    producers.
    """

    stage_a: TransactionTagCache = field(default_factory=dict)
    stage_b: SourcingCache = field(default_factory=dict)
    materialization: AiTagCache = field(default_factory=dict)  # LP-326 generic AI producer cache


@dataclass(frozen=True)
class Reasoners:
    """The injected AI reasoner seams (keyless tests supply stubs; None = the real model)."""

    stage_a: StageAReasoner | None = None
    stage_b: StageBReasoner | None = None
    oc2: Oc2Reasoner | None = None
    # LP-326: keyed by AI-GROUP for the generic materialization producer (e.g. "id_address").
    materialization: dict[str, AiGroupReasoner] | None = None
    # LP-325/326: keyed by RULE_ID for the consistency evaluators' fuzzy leg (e.g. "ID-4").
    consistency: dict[str, ConsistencyReasoner] | None = None


@dataclass(frozen=True)
class Degradation:
    """One recorded degradation — WHAT degraded and WHY (visibility, never hidden)."""

    stage: str  # "build" | "stage_a" | "stage_b" | "persist_snapshot"
    reason: str
    subject: str | None = None  # a content_id / tag_id when tag-level


@dataclass(frozen=True)
class VerificationRun:
    """The result of one full verification run."""

    run_id: UUID
    snapshot: Snapshot
    findings: list[Finding]  # the findings THIS run DETECTED (retired ones are on `reconciliation`)
    reconciliation: ReconcileRunResult  # the full cross-run lifecycle breakdown (minted/…/retired)
    degradations: tuple[Degradation, ...]
    model: str  # reproducibility (§3D) — the model that produced the AI tags
    vocab_version: int  # the snapshot/vocabulary version

    @property
    def degraded(self) -> bool:
        return bool(self.degradations)


async def _run_stage(
    stage: str,
    produce: Callable[[Snapshot], Awaitable[Snapshot]],
    snapshot: Snapshot,
    degradations: list[Degradation],
) -> Snapshot:
    """Run one production stage with a backstop: a wholesale exception degrades, never crashes.

    The tag producers already fail-close per call (a bad AI response → unknown-with-reason tags).
    This catches only an UNEXPECTED wholesale failure of the stage — the pre-stage snapshot is kept
    (that stage's tags simply absent), the degradation is recorded, and the run continues.

    Logged at ERROR (not warning): a wholesale stage failure is never normal — it is a transport
    outage or, since the per-call path already fail-closes, quite possibly a code defect. Keeping the
    run alive must not bury it; the ERROR + recorded degradation make it alert-worthy.
    """
    try:
        return await produce(snapshot)
    except Exception as exc:
        logger.error("verification_stage_failed", stage=stage, error=type(exc).__name__)
        degradations.append(Degradation(stage, f"stage failed: {type(exc).__name__}"))
        return snapshot


def _scan_section_degradations(snapshot: Snapshot) -> list[Degradation]:
    """Absent-with-reason RAW sections (the build already degrades per section) → visible."""
    degradations: list[Degradation] = []
    for name, section in (
        ("mismo", snapshot.mismo),
        ("documents", snapshot.documents),
        ("calculations", snapshot.calculations),
    ):
        if section.absent and section.reason is not None:
            degradations.append(Degradation("build", f"{name} absent: {section.reason}", name))
    return degradations


def _scan_tag_degradations(snapshot: Snapshot) -> list[Degradation]:
    """Fail-closed (unknown-with-reason) AI production tags in the tags layer → visible.

    A producer that could not judge a tag falls back to an ``"unknown"`` AI tag with a null
    confidence and a reason naming WHY (failed / truncated / malformed / omitted / off-vocabulary).
    A GENUINE AI "unknown" instead carries the model's own confidence, and a parsed passthrough is
    ``produced_by != AI`` — so the fail-closed marker is STRUCTURAL: ``value=="unknown"`` +
    ``produced_by==AI`` + ``confidence is None``. This surfaces every fallback (including the
    "not returned" omission that a reason-string match would miss) without coupling the orchestrator
    to the exact wording of another module's reason text.
    """
    degradations: list[Degradation] = []
    for content_id, tags in snapshot.tags.by_subject.items():
        for tag_id, tag in tags.items():
            if (
                tag.value == "unknown"
                and tag.produced_by == TagProducedBy.AI
                and tag.confidence is None
            ):
                degradations.append(
                    Degradation(
                        "tag_production", tag.reasoning or "unknown", f"{content_id}:{tag_id}"
                    )
                )
    return degradations


async def _evaluate_rules(
    snapshot: Snapshot,
    *,
    oc2_reasoner: Oc2Reasoner | None,
    consistency_reasoners: dict[str, ConsistencyReasoner] | None,
    confidence_floor: float,
) -> tuple[list[RuleEvaluation], dict[str, dict[str, Tag]]]:
    """Run every rule over the tagged snapshot — deterministic (AS-1), judgment (OC-2), and
    cross-source consistency (ID-2 exact / ID-4 fuzzy, LP-326).

    Each rule runs and GATES itself (LP-315/319): a rule whose load-bearing tags are degraded returns
    couldnt_check; a rule that does not depend on them evaluates normally. The orchestrator lets them
    all run — it never skips a rule silently.

    Returns the evaluations plus any ``rule_judgment`` tags a judgment rule produced (OC-2's
    ``occupancy.reasonable``), keyed ``{subject_id: {tag_id: Tag}}`` (LP-327 — per subject), for the
    caller to write back into the tags layer — the judgment rule's §3D output must not be discarded.

    Generic dispatch (LP-324): the registry runs the active rule SET by KIND from their specs — no
    hardcoded per-rule calls. Adding a rule is a spec + a registry entry, never new Python here.
    """
    return await evaluate_rules(
        snapshot,
        judgment_reasoners={"OC-2": oc2_reasoner} if oc2_reasoner is not None else {},
        consistency_reasoners=consistency_reasoners or {},
        confidence_floor=confidence_floor,
    )


def _merge_judgment_tags(snapshot: Snapshot, judgment_tags: dict[str, dict[str, Tag]]) -> Snapshot:
    """Write the rule_judgment tags into the tags layer, each under ITS subject (frozen-safe copy).

    A judgment rule's produced tag belongs in the tags layer keyed to the subject it judged (LP-327):
    OC-2's ``occupancy.reasonable`` under the loan subject; a per-document verdict under that
    document. Not dropped — a ratifier / downstream reads it there. No-op when none were produced
    (e.g. OC-2 couldnt_check when its structural inputs are absent).
    """
    if not judgment_tags:
        return snapshot
    by_subject = {cid: dict(tags) for cid, tags in snapshot.tags.by_subject.items()}
    for subject_id, tags in judgment_tags.items():
        by_subject.setdefault(subject_id, {}).update(tags)
    return snapshot.model_copy(update={"tags": TagsSection.present(by_subject)})


def _retire_eligible_rules(snapshot: Snapshot) -> frozenset[str]:
    """The evaluated rules whose subject domain was HEALTHILY enumerated this run — only these may
    retire a non-detected prior finding.

    A degraded run must NOT be read as "the subject is gone" (that would flip real open findings to
    green — false-closed). Derived generically PER RULE from its ``subject_enumeration``: a rule whose
    subjects come from the documents section (per-transaction / per-borrower / per-document) is
    retire-eligible ONLY if it actually enumerated ≥1 subject this run. Documents absent (a build
    degradation) or unresolved borrowers/documents → zero subjects for a DEGRADED reason, so the rule
    does not retire. ``loan`` rules (OC-2, ID-6) are document-independent — always one subject, always
    eligible. No hardcoded rule-id or per-shape list, so a new per-document / per-borrower rule is
    covered automatically (LP-327).
    """
    eligible = set(ACTIVE_RULE_IDS)
    enumerated_empty: dict[str, bool] = {}  # memoize per enumeration key (rules share enumerations)
    for rule_id in ACTIVE_RULE_IDS:
        enumeration = load_rule_spec(rule_id).subject_enumeration
        if enumeration not in _DOCUMENT_DERIVED_ENUMERATIONS:
            continue
        if enumeration not in enumerated_empty:
            enumerated_empty[enumeration] = not enumerate_subjects(enumeration, snapshot)
        if enumerated_empty[enumeration]:
            eligible.discard(rule_id)
    return frozenset(eligible)


async def _persist(
    db: AsyncSession,
    *,
    loan_file_id: UUID,
    verification_id: UUID | None,
    run_id: UUID,
    results: list[RuleEvaluation],
    retire_eligible_rule_ids: frozenset[str],
) -> ReconcileRunResult:
    """Reconcile this run's results into findings across runs (LP-322).

    Matches against the loan file's prior findings by (rule_id, subject_key): carry-forward / mint /
    retire / resolve / revive. Replaces the single-run insert that collided on the uniqueness index
    when the same loan file was re-run (LP-321). Retirement is gated on ``retire_eligible_rule_ids``
    (a degraded run must not retire). Returns the full reconcile breakdown (retired ones stay on the
    surface, labeled no_longer_applies — immortality).
    """
    return await reconcile_evaluation_findings(
        db,
        loan_file_id=loan_file_id,
        verification_id=verification_id,
        run_id=run_id,
        results=results,
        # The rules that RAN — the registry, the single source of truth — never the category map.
        evaluated_rule_ids=frozenset(ACTIVE_RULE_IDS),
        category_by_rule=_RULE_CATEGORY,
        retire_eligible_rule_ids=retire_eligible_rule_ids,
    )


async def run_verification(
    db: AsyncSession,
    *,
    run_id: UUID,
    loan_file_id: UUID,
    company_id: UUID | None = None,
    base_snapshot: Snapshot | None = None,
    verification_id: UUID | None = None,
    caches: TagCaches | None = None,
    reasoners: Reasoners | None = None,
    produce_tags: bool = True,
    confidence_floor: float = DEFAULT_CONFIDENCE_FLOOR,
) -> VerificationRun:
    """Run ONE full verification over a loan file, in dependency order, degrading gracefully.

    Order: raw snapshot (+ calculators, built in the snapshot) → Stage A → Stage B → rules (gate +
    deterministic + judgment) → findings. ``caches`` (reused across runs) makes unchanged inputs
    cache hits. ``reasoners`` inject stubs for keyless runs. ``base_snapshot`` supplies a pre-built
    raw snapshot (else it is built from the loan file); ``produce_tags=False`` runs the rules over an
    already-tagged snapshot (reproducibility / a frozen trace). Always completes; what degraded is
    recorded on the result.
    """
    caches = caches or TagCaches()
    reasoners = reasoners or Reasoners()
    degradations: list[Degradation] = []

    # 1. RAW snapshot (+ calculators-as-tags, built inside build_snapshot; each section degrades on
    #    its own — LP-318/builder). Calculators read stated financials, not Stage-A/B tags, so they
    #    do not depend on the tag stages.
    if base_snapshot is not None:
        snapshot = base_snapshot
    else:
        if company_id is None:
            raise ValueError("company_id is required when building the snapshot from the loan file")
        snapshot = await build_snapshot(
            db, loan_file_id=loan_file_id, run_id=run_id, company_id=company_id
        )
    degradations.extend(_scan_section_degradations(snapshot))

    if produce_tags:
        # 2. Stage A — per-transaction atomic tags.
        snapshot = await _run_stage(
            "stage_a",
            lambda s: produce_stage_a_transaction_tags(
                s, reasoner=reasoners.stage_a, cache=caches.stage_a
            ),
            snapshot,
            degradations,
        )
        # 3. Stage B — cross-entity sourcing (consumes A's is_money_in; follows the tag DAG).
        snapshot = await _run_stage(
            "stage_b",
            lambda s: produce_stage_b_sourcing_tags(
                s, reasoner=reasoners.stage_b, cache=caches.stage_b
            ),
            snapshot,
            degradations,
        )
        # 3b. Generic vocabulary-driven materialization (LP-326) — the declared id.* families
        #     (parsed / derived / ai) keyed under the document / loan subjects. Each producer
        #     fail-closes per call; a wholesale failure degrades (the stage backstop), never crashes.
        snapshot = await _run_stage(
            "materialization",
            lambda s: materialize_tags(
                s,
                ai_reasoners=reasoners.materialization,
                ai_cache=caches.materialization,
                only_subjects=_MATERIALIZED_SUBJECTS,
                # Run ONLY the AI groups a live rule consumes — no dead structuring pass (Opus cost)
                # for an id.* family whose rule has not activated yet. Parsed/derived tags always run.
                only_groups=_required_ai_groups(),
            ),
            snapshot,
            degradations,
        )
    # 4. Calculators — already present (built in step 1). 5. Contradiction audit — no deterministic
    #    cross-checks are wired yet; the slot exists (the LP-315 gate takes a contradiction flag),
    #    so this is a no-op today (contradiction defaults to False).
    degradations.extend(_scan_tag_degradations(snapshot))

    # 6. Rules — the fail-closed gate + deterministic + judgment rules. Any rule_judgment tag a
    #    judgment rule produced is written back into the tags layer (not discarded). 7. Findings.
    results, judgment_tags = await _evaluate_rules(
        snapshot,
        oc2_reasoner=reasoners.oc2,
        consistency_reasoners=reasoners.consistency,
        confidence_floor=confidence_floor,
    )
    snapshot = _merge_judgment_tags(snapshot, judgment_tags)
    reconciliation = await _persist(
        db,
        loan_file_id=loan_file_id,
        verification_id=verification_id,
        run_id=run_id,
        results=results,
        # A degraded run must not RETIRE findings it could not re-evaluate (false-closed) — gate
        # retirement on the rules whose subject domain was healthily enumerated.
        retire_eligible_rule_ids=_retire_eligible_rules(snapshot),
    )
    findings = reconciliation.detected

    # Reproducibility: persist the frozen snapshot (best-effort — a persistence hiccup degrades, it
    # does not fail the run). Idempotent by run_id.
    try:
        await persist_snapshot(db, snapshot)
    except Exception as exc:
        logger.warning("verification_persist_snapshot_failed", error=type(exc).__name__)
        degradations.append(Degradation("persist_snapshot", f"not persisted: {type(exc).__name__}"))

    logger.info(
        "verification_run_done",
        run_id=str(run_id),
        findings=len(findings),
        degradations=len(degradations),
    )
    return VerificationRun(
        run_id=run_id,
        snapshot=snapshot,
        findings=findings,
        reconciliation=reconciliation,
        degradations=tuple(degradations),
        model=settings.anthropic_model_extraction,
        vocab_version=snapshot.snapshot_version,
    )


__all__ = [
    "Degradation",
    "Reasoners",
    "TagCaches",
    "VerificationRun",
    "run_verification",
]
