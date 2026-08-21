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

from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, field
from functools import cache
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.finding import Finding, FindingCategory
from app.models.loan_file import LoanFile
from app.models.verification import Verification
from app.services.finding_prose import compose_findings
from app.services.rule_findings import ReconcileRunResult, reconcile_evaluation_findings
from app.services.snapshot_findings import Reasoner as SnapshotFindingsReasoner
from app.services.tag_correlation import (
    Reasoner as StageBReasoner,
)
from app.services.tag_correlation import (
    SourcingCache,
    produce_recurrence_tags,
    produce_stage_b_sourcing_tags,
)
from app.services.tag_production import (
    Reasoner as StageAReasoner,
)
from app.services.tag_production import (
    TransactionTagCache,
    produce_stage_a_transaction_tags,
)
from app.services.verification_progress import (
    SessionFactory as ProgressSessionFactory,
)
from app.services.verification_progress import clear_progress, report_phase
from app.verification.rule_engine.consistency import Reasoner as ConsistencyReasoner
from app.verification.rule_engine.engine import DEFAULT_CONFIDENCE_FLOOR
from app.verification.rule_engine.enumerators import (
    enumerate_subjects,
    per_liability_source_is_degraded,
)
from app.verification.rule_engine.judgment import Reasoner as Oc2Reasoner
from app.verification.rule_engine.registry import ACTIVE_RULE_IDS, evaluate_rules
from app.verification.rule_engine.result import RuleEvaluation
from app.verification.rules.specs import load_rule_spec
from app.verification.snapshot.builder import build_snapshot
from app.verification.snapshot.documents_section import document_id_by_content_id
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
# LP-483 review: ``liability`` was MISSING here while its declaration shipped, so the "first produced
# liab.* tag" materialized in tests (which omit ``only_subjects``) and NEVER on a real run. ⚠️ And the
# orphan guard could not catch it: that guard reads ``load_declarations()``, so DECLARING a tag makes it
# look produced no matter what this scope says. ``test_declared_subjects_are_all_materialized`` now pins
# the two together — a new subject family fails until it is added here.
_MATERIALIZED_SUBJECTS = frozenset({"document", "loan", "borrower", "liability"})


# Subject enumerations whose subjects are derived from the DOCUMENTS section (per-transaction /
# per-borrower / per-document). A rule on one of these that enumerated ZERO subjects this run did so
# for a DEGRADED reason (documents absent, or borrower/document resolution failed) — NOT "the subjects
# are gone" — so it must not retire a prior finding. ``loan`` is document-independent (always one
# subject) → always retire-eligible. Adding a new document-derived shape means adding its key here,
# and every rule that declares it is covered automatically (no per-rule-id list). LP-336 added
# ``per_account`` (accounts are grouped from the statement documents — zero accounts means no statements
# resolved, a degraded reason, not "the accounts are gone").
_DOCUMENT_DERIVED_ENUMERATIONS = frozenset(
    {"per_deposit", "per_borrower", "per_document", "per_account", "per_liability"}
)

# ⚠️ MIXED-SOURCE enumerations, where "zero subjects" is NOT a sufficient degradation signal (LP-480
# review). ``per_liability`` unions credit-report tradelines with MISMO stated liabilities, so a file with
# stated liabilities returns a NON-EMPTY union even when the credit report failed to build — the union
# looks healthy while the whole document-derived half is missing, and every prior tradeline finding would
# retire as "no longer applies". Each entry maps its enumeration to a predicate that answers "was the
# document-derived SOURCE degraded?", checked in ADDITION to the empty check. A future mixed-source shape
# adds its key here; a single-source shape needs nothing.
_MIXED_SOURCE_DEGRADATION: dict[str, Callable[[Snapshot], bool]] = {
    "per_liability": per_liability_source_is_degraded,
}


def _load_bearing_tag_ids(rule_id: str) -> set[str]:
    """The tag ids a rule rests on — its evaluation block's load-bearing / gathered tags."""
    spec = load_rule_spec(rule_id)
    if spec.consistency is not None:
        tags = {spec.consistency.gather_tag}
        if spec.consistency.gather_filter is not None:
            tags.add(spec.consistency.gather_filter.tag_id)
        # LP-618 — AND THE EXCLUSION'S TAG. Without it, an exclusion reading an AI-backed tag whose
        # group nothing else pulls in would find that tag ABSENT and be permanently inert — a filter
        # that silently never fires. ID-4 escapes only incidentally: `id.address_role` is derived and
        # its upstream AI group is already required by `gather_tag`.
        if spec.consistency.gather_exclude is not None:
            tags.add(spec.consistency.gather_exclude.tag_id)
        return tags
    if spec.deterministic is not None:
        return set(spec.deterministic.load_bearing_tags)
    if spec.judgment is not None:
        return set(spec.judgment.load_bearing_tags) | set(spec.judgment.reasoned_over)
    return set()


def _ai_groups_for_rules(rule_ids: Iterable[str]) -> frozenset[str]:
    """The AI groups a set of rules consumes (LP-326) — the shared derivation behind BOTH the live
    ``_required_ai_groups`` (active rules) and the pending ``_pending_check_ai_groups`` (blocked rules).

    Generic: each rule's load-bearing tags → their production declarations → the AI group each declares. A
    parsed/derived load-bearing tag contributes no AI group DIRECTLY — but a DERIVED load-bearing tag still
    rests on the AI tag(s) that feed it, and those must materialize or the rule couldnt_checks forever. The
    activation bar declares exactly those upstream AI tags (LP-380/389: IN-1 rests on
    income.documented_monthly via the derived shortfall), so a rule's bar AI tags are folded in too — the
    group runs, the derived input resolves, the verdict is real. A base-active rule has no bar (skipped).
    ``load_activation_bars`` is imported lazily to keep the registry → activation_bars → registry edge
    one-directional at module load.
    """
    from app.verification.rule_engine.activation_bars import load_activation_bars

    declarations = load_declarations()
    bars = load_activation_bars()
    needed: set[str] = set()
    for rule_id in rule_ids:
        tag_ids = set(_load_bearing_tag_ids(rule_id))
        bar = bars.get(rule_id)
        if bar is not None:
            tag_ids |= set(bar.load_bearing_ai_tags)
        for tag_id in tag_ids:
            decl = declarations.get(tag_id)
            if decl is not None and decl.mode is ProductionMode.AI:
                needed.add(decl.data)  # the AI group key
    return frozenset(needed)


@cache
def _required_ai_groups() -> frozenset[str]:
    """The AI groups the ACTIVE rule set actually consumes (LP-326) — so the materialization stage runs
    ONLY those, never an AI structuring pass for a family no live rule reads yet."""
    return _ai_groups_for_rules(ACTIVE_RULE_IDS)


# Public name for out-of-orchestrator callers (the dormant-probe diagnostic, LP-378) — the live AI-group
# set without depending on a private symbol. Same single source of truth as the orchestrator uses.
required_ai_groups = _required_ai_groups


@cache
def _pending_check_ai_groups() -> frozenset[str]:
    """LP-391 — the AI groups the BLOCKED candidate rules need, materialized IN ADDITION to the live set so a
    blocked-but-applicable rule can be evaluated (and surface a manual-review flag) instead of couldnt_checking
    for lack of its own tag. This is the deliberate extra AI cost of honest pending-check surfacing — the
    uncalibrated groups run so a qualifying file no longer reads as 'checked, clean'. Same derivation as
    ``_required_ai_groups`` (spec load-bearing tags + the bar's declared upstream AI tags), over blocked rules.
    """
    from app.verification.rule_engine.pending_checks import blocked_candidate_rule_ids

    return _ai_groups_for_rules(blocked_candidate_rule_ids())


logger = get_logger(__name__)


# The rule → finding-category map (which area of the file each rule concerns), a display lookup only.
# The set of rules that RAN is the registry's ACTIVE_RULE_IDS (the single source of truth) — NOT this
# map — so reconciliation's evaluated_rule_ids can never drift from what actually evaluated (a drift
# would drop a rule's priors and mint-collide on the uniqueness index). An unmapped rule falls back to
# a default category (cosmetic); a missing category never breaks reconciliation.
# LP-527 — rule_id -> the rule's human NAME, for the composer's fact summary. Read from the catalogue
# (rule_kinds.csv, the single gate of record) rather than restated here: a finding that named a rule
# differently from the catalogue would be a second source of truth for what a check is called.
def _rule_names() -> dict[str, str]:
    from app.verification.rules.kinds import load_rule_kinds

    return {rule_id: rk.name for rule_id, rk in load_rule_kinds().items()}


# LP-595 — the category a finding is FILED under, resolved per rule and then per FAMILY.
#
# THE BUG THIS REPLACES. There were nine entries here and a `default_category=ASSETS` fallback, so the
# other sixty-nine active rules were all filed as ASSETS: the appraisal rules, every income rule, the
# rate-lock rule, the mortgage-insurance rules. On LF-3CVT that was twenty-eight of thirty findings in
# one category, which makes grouping or filtering by category actively misleading rather than merely
# incomplete. Nothing failed — a wrong category is silent, which is why it survived.
#
# The family table is derived from what each family ASKS (its spec titles), not from the prefix letters:
# CO is condo-project docs, IH is hazard insurance on the property, RE-1 is an undisclosed MORTGAGE
# (a debt), LO-2 is letter-of-explanation completeness. A rule whose family answer is wrong for it gets
# an entry in `_RULE_CATEGORY`, which always wins — that is what the ID split below is.
_FAMILY_CATEGORY: dict[str, FindingCategory] = {
    "AS": FindingCategory.ASSETS,  # deposits, statements, reserves
    "AU": FindingCategory.REGULATORY,  # AUS recommendation status
    "CL": FindingCategory.REGULATORY,  # rate-lock expiry
    "CO": FindingCategory.PROPERTY,  # condo project: questionnaire, master policy, HOA budget
    "CR": FindingCategory.CREDIT,  # tradelines, collections, disputes
    "DT": FindingCategory.CREDIT,  # debt obligations and the ratios built from them
    "FR": FindingCategory.CROSS_SOURCE,  # undisclosed arrangements, found by comparing sources
    "ID": FindingCategory.CROSS_SOURCE,  # identity facts across sources (ID-6/7/9 override below)
    "IH": FindingCategory.PROPERTY,  # hazard insurance ON the property
    "IN": FindingCategory.INCOME,
    "LO": FindingCategory.DOCUMENTATION,  # letter-of-explanation completeness
    "MI": FindingCategory.REGULATORY,  # PMI / FHA MIP requirements
    "OC": FindingCategory.PROPERTY,  # occupancy
    "PC": FindingCategory.PROPERTY,  # purchase price, address, closing date
    "PE": FindingCategory.REGULATORY,  # program eligibility
    "PR": FindingCategory.PROPERTY,  # appraisal and property condition
    "RE": FindingCategory.CREDIT,  # RE-1 is an undisclosed MORTGAGE — a debt, not a property fact
    "TI": FindingCategory.PROPERTY,  # title
}

# Per-rule overrides. These WIN over the family. Only for a rule the family answer is wrong for.
_RULE_CATEGORY: dict[str, FindingCategory] = {
    # The ID family splits: 1/2/3/4 compare a fact ACROSS sources; 6/7/9 are about a document.
    "ID-6": FindingCategory.DOCUMENTATION,  # 1003 completeness
    "ID-7": FindingCategory.DOCUMENTATION,  # marital/title vesting consistency
    "ID-9": FindingCategory.DOCUMENTATION,  # POA acceptability
    # ATR is a regulatory obligation (Dodd-Frank), not a reading of the borrower's debts.
    "DT-7": FindingCategory.REGULATORY,
}


def category_for_rule(rule_id: str) -> FindingCategory | None:
    """The category a rule's findings are filed under, or None if the rule is unclassified.

    Returns None rather than guessing: ``test_every_active_rule_has_a_category`` turns an
    unclassified rule into a CI failure, so a new rule cannot quietly inherit someone else's
    category the way all sixty-nine did before LP-595.
    """
    if rule_id in _RULE_CATEGORY:
        return _RULE_CATEGORY[rule_id]
    return _FAMILY_CATEGORY.get(rule_id.split("-")[0])


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
    # LP-586: the snapshot cross-source pass. Injected through the SAME seam as every other reasoner
    # rather than reaching for the real client directly — a keyless test would otherwise degrade every
    # run on an AuthenticationError, which is exactly how this omission was caught.
    snapshot_findings: SnapshotFindingsReasoner | None = None
    # LP-590: the progress reporter's session factory. `task_session()` builds an engine from the DEV
    # database URL, so a test exercising the run would write progress rows into dev — silently, since
    # the reporter swallows its errors. Injected here like every other seam.
    progress_session: ProgressSessionFactory | None = None


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


async def _recurrence_stage(snapshot: Snapshot) -> Snapshot:
    """LP-546 — the recurrence pass is PURE and SYNCHRONOUS; this only meets `_run_stage`'s awaitable
    contract. Kept sync in its own module so it is testable without an event loop, and so nothing about
    it suggests it does I/O — it reads the snapshot it was handed and returns a new one."""
    result: Snapshot = produce_recurrence_tags(snapshot)
    return result


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


async def _evaluate_pending_checks(
    snapshot: Snapshot,
    *,
    materialization_reasoners: dict[str, AiGroupReasoner] | None,
    materialization_cache: AiTagCache | None,
    consistency_reasoners: dict[str, ConsistencyReasoner] | None,
    confidence_floor: float,
) -> list[RuleEvaluation]:
    """LP-391 — evaluate the BLOCKED candidate rules and surface a manual-review flag where each is
    applicable-with-data. Returns only ``PENDING_AUTOMATION`` evaluations (never an uncalibrated verdict);
    a DISJOINT rule set from the live pass, so the live results are untouched.

    BEST-EFFORT + ISOLATED: the blocked rules' AI groups are materialized on a THROWAWAY snapshot copy — never
    the persisted one — and any failure yields no pending flags rather than degrading the main run. So a
    blocked/uncalibrated group can never flip ``run.degraded`` or leak its tags into the stored snapshot."""
    from app.verification.rule_engine.pending_checks import evaluate_pending_checks

    pending_groups = _pending_check_ai_groups()
    try:
        pending_snapshot = (
            await materialize_tags(
                snapshot,
                ai_reasoners=materialization_reasoners,
                ai_cache=materialization_cache,
                only_subjects=_MATERIALIZED_SUBJECTS,
                only_groups=pending_groups,
            )
            if pending_groups
            else snapshot
        )
        # No judgment_reasoners: every blocked JUDGMENT rule is stubbed inside evaluate_pending_checks (it
        # always reaches needs_review when applicable, so a real model call would be spent on a discarded
        # verdict). No base-active rule (e.g. OC-2) is ever a blocked candidate, so none needs a real reasoner.
        return await evaluate_pending_checks(
            pending_snapshot,
            consistency_reasoners=consistency_reasoners or {},
            confidence_floor=confidence_floor,
        )
    except Exception as exc:
        logger.warning("pending_check_surfacing_failed", error=str(exc))
        return []


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
    degraded: dict[str, bool] = {}  # memoize per enumeration key (rules share enumerations)
    for rule_id in ACTIVE_RULE_IDS:
        enumeration = load_rule_spec(rule_id).subject_enumeration
        if enumeration not in _DOCUMENT_DERIVED_ENUMERATIONS:
            continue
        if enumeration not in degraded:
            source_degraded = _MIXED_SOURCE_DEGRADATION.get(enumeration)
            degraded[enumeration] = not enumerate_subjects(enumeration, snapshot) or (
                source_degraded is not None and source_degraded(snapshot)
            )
        if degraded[enumeration]:
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
    document_id_by_content_id: Mapping[str, UUID],  # LP-617
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
        document_id_by_content_id=document_id_by_content_id,
        loan_file_id=loan_file_id,
        verification_id=verification_id,
        run_id=run_id,
        results=results,
        # The rules that RAN — the registry, the single source of truth — never the category map.
        evaluated_rule_ids=frozenset(ACTIVE_RULE_IDS),
        # LP-595 — RESOLVED for every active rule (per-rule override, then family), not the nine-entry
        # map that left the other sixty-nine falling through to ASSETS.
        category_by_rule={
            rule_id: category
            for rule_id in ACTIVE_RULE_IDS
            if (category := category_for_rule(rule_id)) is not None
        },
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
    # LP-590 — PROGRESS. Each call opens its own short-lived session and commits immediately: this
    # run is one transaction that commits at the very end, so anything written on `db` would be
    # invisible to a poller until the run was already over. Best-effort by construction — the
    # reporter swallows its own errors, because failing a verification to describe it would be a
    # grotesque trade.
    await report_phase(run_id, "build", session_factory=reasoners.progress_session)
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
        await report_phase(run_id, "stage_a", session_factory=reasoners.progress_session)
        snapshot = await _run_stage(
            "stage_a",
            lambda s: produce_stage_a_transaction_tags(
                s, reasoner=reasoners.stage_a, cache=caches.stage_a
            ),
            snapshot,
            degradations,
        )
        # 2b. LP-546 — recurrence, DETERMINISTIC and model-free. Sits with the transaction tags because
        #     the generic pass skips the `transaction` subject; see produce_recurrence_tags for why a
        #     declaration alone would materialize in tests and never on a real run.
        snapshot = await _run_stage(
            "recurrence",
            _recurrence_stage,
            snapshot,
            degradations,
        )
        # 3. Stage B — cross-entity sourcing (consumes A's is_money_in; follows the tag DAG).
        await report_phase(run_id, "stage_b", session_factory=reasoners.progress_session)
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
                # (LP-391's pending-check groups materialize SEPARATELY, best-effort, so a blocked group
                # never degrades this run or enters the persisted snapshot.)
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
    await report_phase(run_id, "rules", session_factory=reasoners.progress_session)
    results, judgment_tags = await _evaluate_rules(
        snapshot,
        oc2_reasoner=reasoners.oc2,
        consistency_reasoners=reasoners.consistency,
        confidence_floor=confidence_floor,
    )
    snapshot = _merge_judgment_tags(snapshot, judgment_tags)
    # 6b. LP-391 — pending-check surfacing (ADDITIVE, a DISJOINT rule set): a blocked-but-applicable rule
    #     emits a manual-review flag to Tab 1 instead of silence. Never ships an uncalibrated verdict; the
    #     live results above are untouched (blocked ≠ active). Gated (settings.pending_checks_enabled) because
    #     it materializes the BLOCKED rules' uncalibrated AI groups every run — real extra cost a
    #     cost-sensitive deployment can turn off; ON by default (the honest-surfacing behavior).
    if settings.pending_checks_enabled:
        results = results + await _evaluate_pending_checks(
            snapshot,
            materialization_reasoners=reasoners.materialization,
            materialization_cache=caches.materialization,
            consistency_reasoners=reasoners.consistency,
            confidence_floor=confidence_floor,
        )
    # LP-617 — resolve each finding's snapshot content ids back to real document ids, so a finding can
    # point a processor AT the documents it is about instead of naming their categories. Built here,
    # next to its one consumer, rather than threaded from the snapshot build minutes earlier. Mirrors
    # `document_filenames_by_content_id` (LP-377-B), which resolves the same keys for the read path.
    loan_file_row = await db.get(LoanFile, loan_file_id)
    document_ids = (
        await document_id_by_content_id(db, loan_file_row) if loan_file_row is not None else {}
    )
    reconciliation = await _persist(
        db,
        document_id_by_content_id=document_ids,
        loan_file_id=loan_file_id,
        verification_id=verification_id,
        run_id=run_id,
        results=results,
        # A degraded run must not RETIRE findings it could not re-evaluate (false-closed) — gate
        # retirement on the rules whose subject domain was healthily enumerated.
        retire_eligible_rule_ids=_retire_eligible_rules(snapshot),
    )
    findings = reconciliation.detected

    # LP-527 — the composer: rewrite the findings' TEXT from a fixed fact summary. Deliberately here,
    # after the verdicts are decided and persisted: it touches `message` and nothing else, so a total
    # failure of this pass leaves a fully correct run whose findings read as the templates wrote them.
    # Off unless `finding_prose_enabled`.
    if settings.finding_prose_enabled and findings:
        try:
            await compose_findings(
                db,
                findings,
                rule_names=_rule_names(),
                loan_file_id=loan_file_id,
            )
        except Exception as exc:
            logger.warning("finding_prose_pass_failed", error=type(exc).__name__)

    # Reproducibility: persist the frozen snapshot (best-effort — a persistence hiccup degrades, it
    # does not fail the run). Idempotent by run_id.
    try:
        await persist_snapshot(db, snapshot)
    except Exception as exc:
        # LP-565 — LOG THE REASON, not just the class name. `_assert_no_raw_pii` was rewritten by
        # LP-509-C1 specifically so its message NAMES THE FIELD, and this call site then threw that
        # away — so the at-rest guard refused every write on staging for six days (22 completed runs,
        # 0 snapshots) while the only trace was `error=RawPiiAtRestError`, which says nothing anyone
        # can act on.
        #
        # The message is safe to log BY CONSTRUCTION: it reports the path and the SHAPE of what was
        # found ("a 12-digit run"), never the value — a guard against logging raw PII must not log raw
        # PII itself, and it does not.
        logger.warning(
            "verification_persist_snapshot_failed",
            error=type(exc).__name__,
            detail=str(exc),
        )
        degradations.append(Degradation("persist_snapshot", f"not persisted: {exc}"))

    # LP-586 — the snapshot-based AI cross-source pass. Best-effort for the same reason the persist
    # above is: an AI hiccup degrades the run, it does not fail one whose rules already completed.
    #
    # Runs AFTER the snapshot is persisted and reads the SAME in-memory object, so what the model
    # saw is exactly what is on disk. On an unchanged file this does not call the model at all — the
    # fingerprint decides, and that is what keeps the tab from moving under a processor's feet.
    await report_phase(run_id, "cross_source", session_factory=reasoners.progress_session)
    try:
        from app.services.snapshot_findings import refresh_snapshot_findings

        # SAVEPOINT — "best-effort" was only true for non-DB exceptions. A DB error inside this call
        # poisons the session, so the `except` below would record a degradation while the caller's
        # own commit then raised PendingRollbackError, rolling back the rule findings, the persisted
        # snapshot and the COMPLETED status with it. `begin_nested()` contains it: the outer
        # transaction survives, and the pass degrades the way the comment above always claimed.
        async with db.begin_nested():
            cross_checks = await refresh_snapshot_findings(
                db,
                loan_file_id=snapshot.loan_file_id,
                snapshot=snapshot,
                reasoner=reasoners.snapshot_findings,
            )
            # LP-592 — record the OPEN count on this run. It cannot be derived later: snapshot
            # findings are keyed by loan file and persist across runs by design, so nothing
            # afterwards can answer "how many did this run see". Open only — a badge that counted
            # signed-off ones would keep advertising work a processor had already cleared.
            run_row = await db.get(Verification, run_id)
            if run_row is not None:
                run_row.cross_check_count = sum(1 for f in cross_checks if f.disposition == "open")
    except Exception as exc:
        logger.warning(
            "snapshot_findings_failed",
            error=type(exc).__name__,
            detail=str(exc),
        )
        degradations.append(Degradation("snapshot_findings", f"not refreshed: {exc}"))

    # Cleared rather than left on the last phase: "Cross-source review" still showing after a run
    # finished is exactly what a hung run looks like.
    await clear_progress(run_id, session_factory=reasoners.progress_session)

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
        model=settings.anthropic_model_reasoning,
        vocab_version=snapshot.snapshot_version,
    )


__all__ = [
    "Degradation",
    "Reasoners",
    "TagCaches",
    "VerificationRun",
    "run_verification",
]
