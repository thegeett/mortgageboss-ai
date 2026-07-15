"""Stage-2 rule-SPEC loader (LP-303, ADR-249) — the data the evaluator prompt injects.

A rule SPEC is the version-controlled DATA that fills the Stage-2 evaluator prompt's
spine slots (``criteria`` / ``applicability`` / ``required_inputs`` / ``reference_values``
/ ``evidence_required`` / ``guideline_reference`` — see
``docs/stage2-evaluator-prompts.md``). This module reads one spec file and returns a
frozen, validated :class:`RuleSpec`. Nothing consumes it yet — the evaluator is LP-304;
this is the spec + loader only.

Sits alongside the LP-301 kinds loader (:mod:`app.verification.rules.kinds`) and
**composes with it**: :func:`load_rule_spec` cross-checks the spec's ``kind`` /
``numeric_check`` and the validation gate (``reference_values.priya_validated`` /
``threshold_needs_signoff``) against the rule's ``rule_kinds.csv`` row and raises on any
mismatch, so the CSV stays the single gate of record and a spec can never silently
diverge (e.g. mark a threshold "validated" when the CSV says it is not).

**The interface is swappable** — the evaluator will only ever call
``load_rule_spec(rule_id)``; today that reads a YAML file under ``specs/``, but the
signature does not reveal (or promise) a file. A DB-backed source later is a drop-in.

⚠️ **The spec FORMAT is provisional.** :class:`RuleSpec` was discovered from ONE real
rule (AS-1); it is generalized in LP-308. Do not treat the shape as final.
"""

from __future__ import annotations

import string
from functools import cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ValidationError, model_validator
from pydantic import Field as PydField

from app.verification.rules.kinds import RuleKind, RuleKindName, kind_for
from app.verification.rules.schema import Operator

# The spec files live co-located with the rules, one YAML per rule_id (AS-1.yaml).
_SPECS_DIR = Path(__file__).with_name("specs")

_FORMATTER = string.Formatter()


def _template_fields(template: str) -> set[str]:
    """The base operand names a ``str.format`` template references (raises on a malformed template)."""
    return {
        name.split(".")[0].split("[")[0]
        for _literal, name, _spec, _conv in _FORMATTER.parse(template)
        if name
    }


class RuleSpecError(Exception):
    """Base for every rule-spec load failure (all fail loud, never silent)."""


class RuleSpecNotFound(RuleSpecError):
    """No spec file exists for the requested rule_id."""


class RuleSpecInvalid(RuleSpecError):
    """The spec file is unparseable or missing/malformed required slots."""


class RuleSpecInconsistent(RuleSpecError):
    """The spec disagrees with the rule's ``rule_kinds.csv`` row (kind / gate)."""


class Applicability(BaseModel):
    """Scope + trigger (spine slot ``rule.applicability``)."""

    model_config = {"frozen": True, "extra": "forbid"}

    scope: str = PydField(min_length=1)
    trigger: str = PydField(min_length=1)


class RequiredInput(BaseModel):
    """One input the rule needs, POINTING AT THE SNAPSHOT (LP-302 Option A).

    ``snapshot_path`` is a human-readable pointer into the frozen snapshot shape (the
    evaluator formats it into the prompt); it is documentation of provenance, not an
    executable accessor. Kept structured (not a bare string) so tests can assert the
    paths are real post-LP-302a snapshot locations.
    """

    model_config = {"frozen": True, "extra": "forbid"}

    name: str = PydField(min_length=1)
    snapshot_path: str = PydField(min_length=1)
    description: str = PydField(min_length=1)


class ReferenceValues(BaseModel):
    """The rule's threshold DATA + its validation-gate status (spine slot
    ``rule.reference_values``).

    ``large_deposit_threshold`` is AS-1's threshold recorded as DATA — the number lives
    in the spec, never in the AI's memory. ``priya_validated`` / ``threshold_needs_signoff``
    mirror ``rule_kinds.csv`` and are CROSS-CHECKED by :func:`load_rule_spec`; they are
    recorded honestly (AS-1's 50% threshold is not yet Priya-confirmed). Provisional
    (AS-1-shaped) — LP-308 generalizes reference-value carriage.
    """

    model_config = {"frozen": True, "extra": "forbid"}

    # AS-1's threshold prose (the prompt spine slot) — OPTIONAL: a threshold-free rule (e.g. a
    # judgment rule) omits it. The machine threshold DATA lives in ``values`` (LP-324).
    large_deposit_threshold: str | None = None
    priya_validated: bool
    threshold_needs_signoff: bool
    # LP-324: generically-keyed threshold DATA the generic evaluator reads (e.g.
    # ``{"large_deposit_threshold_pct": "50%"}``) — no rule-named field. ``large_deposit_threshold``
    # above is retained as the human/prompt prose (the AS-1 spine slot). ``guideline_text`` is the
    # encoded guideline authority a finding cites (never AI-recalled).
    values: dict[str, str] = PydField(default_factory=dict)
    guideline_text: str | None = None


# --------------------------------------------------------------------------- #
# LP-324 — the machine-readable EVALUATION blocks (a rule is now DATA an evaluator runs)
# --------------------------------------------------------------------------- #


class TagCondition(BaseModel):
    """One tag-value predicate: ``<tag> <eq|ne> <value>`` (applicability + outcome guards)."""

    model_config = {"frozen": True, "extra": "forbid"}

    tag: str = PydField(min_length=1)
    op: str = PydField(pattern="^(eq|ne)$")  # eq | ne (string-value equality)
    value: str = PydField(min_length=1)


class Operand(BaseModel):
    """A declared OPERAND SOURCE — where a comparison value comes from (tag / reference / calc /
    a product of operands). Exactly one source key is set (validated).

    * ``tag`` — a subject tag's value, coerced to Decimal.
    * ``reference`` — a ``reference_values.values`` key; a trailing ``%`` is parsed to a fraction.
    * ``calc`` — ``[calculator_name, value_key]`` from ``snapshot.calculations`` (a GATED calc → None
      → couldnt_check, LP-318).
    * ``product`` — the product of its operands (AS-1's ``multiplier x qualifying_income``).
    """

    model_config = {"frozen": True, "extra": "forbid"}

    tag: str | None = None
    reference: str | None = None
    calc: tuple[str, str] | None = None
    product: tuple[Operand, ...] | None = None

    @model_validator(mode="after")
    def _exactly_one_source(self) -> Operand:
        set_count = sum(x is not None for x in (self.tag, self.reference, self.calc, self.product))
        if set_count != 1:
            raise ValueError("an Operand sets EXACTLY one of tag / reference / calc / product")
        return self


class Comparison(BaseModel):
    """A declared numeric comparison between two named operands (reuses :class:`Operator`)."""

    model_config = {"frozen": True, "extra": "forbid"}

    op: Operator
    left: str = PydField(min_length=1)  # operand name (e.g. "observed")
    right: str = PydField(min_length=1)  # operand name (e.g. "threshold")


class OutcomeRule(BaseModel):
    """One ordered outcome branch: when its guards hold, it fires its verdict (first match wins).

    ``when_tags`` (all must hold) + optional ``when_compare`` are the guard; ``default=True`` is the
    catch-all (no guard). ``reasoning`` is a ``str.format`` template over the resolved operands +
    subject tag values.
    """

    model_config = {"frozen": True, "extra": "forbid"}

    verdict: str = PydField(pattern="^(fired|satisfied|needs_review|couldnt_check)$")
    when_tags: tuple[TagCondition, ...] = ()
    when_compare: Comparison | None = None
    default: bool = False
    reasoning: str = PydField(min_length=1)
    how_to_fix: str | None = None


class DeterministicEval(BaseModel):
    """The machine-readable body of a deterministic (calculative/structural) rule (LP-324)."""

    model_config = {"frozen": True, "extra": "forbid"}

    load_bearing_tags: tuple[str, ...] = PydField(min_length=1)
    gated_tags: tuple[str, ...] = PydField(min_length=1)  # the gate-required subset
    applicability: TagCondition | None = None  # a pre-gate per-subject applicability filter
    operands: dict[str, Operand] = PydField(default_factory=dict)
    outcomes: tuple[OutcomeRule, ...] = PydField(min_length=1)
    confidence_floor: float = 0.5

    @model_validator(mode="after")
    def _outcomes_are_exhaustive_and_reference_real_operands(self) -> DeterministicEval:
        # A `default: true` catch-all LAST guarantees EVERY subject reaches a verdict — otherwise a
        # subject that matches no branch is silently dropped (no finding = false green). Only the LAST
        # outcome may be default (an earlier default shadows the branches after it).
        if not self.outcomes[-1].default:
            raise ValueError(
                "deterministic outcomes must end with a `default: true` catch-all, else a subject "
                "can match no branch and be silently dropped"
            )
        if any(o.default for o in self.outcomes[:-1]):
            raise ValueError(
                "only the LAST outcome may be `default: true` (an earlier default shadows the "
                "branches after it)"
            )
        operand_names = set(self.operands)
        for outcome in self.outcomes:
            if outcome.when_compare is not None:
                for ref in (outcome.when_compare.left, outcome.when_compare.right):
                    if ref not in operand_names:
                        raise ValueError(
                            f"when_compare references unknown operand {ref!r} "
                            f"(operands: {sorted(operand_names)})"
                        )
            # reasoning is `str.format(**operands)` at eval time — a stray brace or an unknown
            # placeholder would crash the run, so both are caught at load.
            try:
                fields = _template_fields(outcome.reasoning)
            except ValueError as exc:
                raise ValueError(f"outcome reasoning template is malformed: {exc}") from exc
            unknown = fields - operand_names
            if unknown:
                raise ValueError(
                    f"outcome reasoning references unknown operand(s) {sorted(unknown)} "
                    f"(operands: {sorted(operand_names)})"
                )
        return self


class JudgmentEval(BaseModel):
    """The machine-readable body of an AI-at-rule-time judgment rule (LP-324 / LP-319 armor)."""

    model_config = {"frozen": True, "extra": "forbid"}

    subject: str = PydField(min_length=1)  # the subject key the loan-level tags live under
    load_bearing_tags: tuple[str, ...] = PydField(min_length=1)  # gated structural inputs
    reasoned_over: tuple[str, ...] = PydField(min_length=1)  # the tags the AI reasons over
    output_tag: str = PydField(min_length=1)  # the rule_judgment tag produced
    value_domain: tuple[str, ...] = PydField(
        min_length=1
    )  # allowed judgment values (incl "unknown")
    system_prompt: str = PydField(min_length=1)  # the underwriter question, as DATA
    confidence_floor: float = 0.5


# --------------------------------------------------------------------------- #
# LP-325 — the CROSS-SOURCE CONSISTENCY block (the third rule shape): gather a
# fact across sources, exact-compare, AI-judge only the differing residue.
# --------------------------------------------------------------------------- #

# The placeholders a consistency outcome reasoning template may reference (formatted at eval time
# over the gathered set) — validated at LOAD so a stray/unknown placeholder never crashes a run.
_CONSISTENCY_TEMPLATE_FIELDS = frozenset({"values", "sources", "count"})


class ConsistencyOutcome(BaseModel):
    """One terminal outcome of a consistency compare (agree / disagree / cannot-tell → a verdict).

    ``reasoning`` is a ``str.format`` template over ``{values}`` / ``{sources}`` / ``{count}`` (the
    gathered values, their source ids, and the instance count).
    """

    model_config = {"frozen": True, "extra": "forbid"}

    verdict: str = PydField(pattern="^(fired|satisfied|needs_review|couldnt_check)$")
    reasoning: str = PydField(min_length=1)
    how_to_fix: str | None = None


class ConsistencyJudge(BaseModel):
    """The AI-fuzzy leg (LP-314/319) — invoked ONLY on the small DIFFERING residue, never the file.

    The judge answers with a value in ``value_domain``; ``consistent_value`` maps to AGREE (a benign
    variance — the same fact written differently) and ``inconsistent_value`` maps to DISAGREE (a real
    discrepancy). Any other value (incl. an "unknown") → cannot-tell (honest couldnt_check).
    """

    model_config = {"frozen": True, "extra": "forbid"}

    system_prompt: str = PydField(min_length=1)  # the tolerant-match question, as DATA
    value_domain: tuple[str, ...] = PydField(min_length=1)  # allowed judge values (incl "unknown")
    consistent_value: str = PydField(min_length=1)  # the domain value that means AGREE
    inconsistent_value: str = PydField(min_length=1)  # the domain value that means DISAGREE

    @model_validator(mode="after")
    def _agree_disagree_are_in_domain_and_distinct(self) -> ConsistencyJudge:
        for role, val in (
            ("consistent", self.consistent_value),
            ("inconsistent", self.inconsistent_value),
        ):
            if val not in self.value_domain:
                raise ValueError(
                    f"judge {role}_value {val!r} is not in value_domain {list(self.value_domain)}"
                )
        if self.consistent_value == self.inconsistent_value:
            raise ValueError("judge consistent_value and inconsistent_value must differ")
        return self


class ConsistencyEval(BaseModel):
    """The machine-readable body of a CROSS-SOURCE consistency rule (LP-325, the third shape).

    Gather ``gather_tag`` for the subject across ``source_scope`` (applying ``gather_filter``),
    exact-compare after ``normalization``; if they differ, ``exact`` mode calls it a discrepancy and
    ``fuzzy`` mode asks the ``judge`` about the differing residue only. The registry keys (``subject`` /
    ``source_scope`` / ``normalization``) are resolved by the evaluator (which raises on an unknown
    key), keeping this schema decoupled from the enumerator/gather/normalizer registries.
    """

    model_config = {"frozen": True, "extra": "forbid"}

    subject: str = PydField(min_length=1)  # the enumerator key (per_borrower / loan / property)
    gather_tag: str = PydField(
        min_length=1
    )  # the tag gathered across sources (the load-bearing fact)
    source_scope: str = PydField(min_length=1)  # the gather-registry key (which sources to collect)
    gather_filter: TagCondition | None = None  # which instances count (residence-vs-mailing trap)
    compare_mode: str = PydField(pattern="^(exact|fuzzy)$")
    normalization: tuple[str, ...] = ()  # declared normalizer keys for the exact compare
    judge: ConsistencyJudge | None = None  # required iff fuzzy (the AI residue leg)
    confidence_floor: float = 0.5
    on_agree: ConsistencyOutcome
    on_disagree: ConsistencyOutcome
    # cannot-tell is only REACHABLE on the fuzzy path (the AI answered "unknown"); an exact rule can
    # never hit it (it lands on_agree / on_disagree / a gate verdict), so it is fuzzy-only, mirroring
    # `judge` — an exact rule must not carry dead config.
    on_cannot_tell: ConsistencyOutcome | None = None

    @model_validator(mode="after")
    def _judge_matches_mode_and_templates_are_valid(self) -> ConsistencyEval:
        if self.compare_mode == "fuzzy" and self.judge is None:
            raise ValueError("a fuzzy consistency rule needs a `judge` block")
        if self.compare_mode == "exact" and self.judge is not None:
            raise ValueError(
                "an exact consistency rule must not declare a `judge` (no AI is called)"
            )
        if self.compare_mode == "fuzzy" and self.on_cannot_tell is None:
            raise ValueError("a fuzzy consistency rule needs an `on_cannot_tell` outcome")
        if self.compare_mode == "exact" and self.on_cannot_tell is not None:
            raise ValueError(
                "an exact consistency rule must not declare `on_cannot_tell` (it is never reached)"
            )
        for name, outcome in (
            ("on_agree", self.on_agree),
            ("on_disagree", self.on_disagree),
            ("on_cannot_tell", self.on_cannot_tell),
        ):
            if outcome is None:
                continue
            try:
                fields = _template_fields(outcome.reasoning)
            except ValueError as exc:
                raise ValueError(f"{name} reasoning template is malformed: {exc}") from exc
            unknown = fields - _CONSISTENCY_TEMPLATE_FIELDS
            if unknown:
                raise ValueError(
                    f"{name} reasoning references unknown placeholder(s) {sorted(unknown)} "
                    f"(allowed: {sorted(_CONSISTENCY_TEMPLATE_FIELDS)})"
                )
        return self


class RuleSpec(BaseModel):
    """A frozen, validated Stage-2 rule spec — every prompt-spine slot populated.

    Frozen + ``extra="forbid"``: an unknown key or a missing slot fails loudly at LOAD
    time (not deep in an evaluation). Provisional shape (discovered from AS-1; LP-308).
    """

    model_config = {"frozen": True, "extra": "forbid"}

    rule_id: str = PydField(min_length=1)
    name: str = PydField(min_length=1)
    category: str = PydField(min_length=1)
    kind: RuleKindName
    numeric_check: bool
    criteria: str = PydField(min_length=1)
    applicability: Applicability
    required_inputs: tuple[RequiredInput, ...] = PydField(min_length=1)
    reference_values: ReferenceValues
    subject_enumeration: str = PydField(min_length=1)  # an EXECUTABLE enumerator key (LP-324)
    subject_key_fields: tuple[str, ...] = PydField(min_length=1)
    evidence_required: str = PydField(min_length=1)
    guideline_reference: str = PydField(min_length=1)
    spec_version: int = PydField(ge=1)
    # LP-324/325 — the machine-readable evaluation body. Exactly one matches the kind: deterministic
    # for calculative/(structural), judgment for judgmental, consistency for a cross-source structural
    # rule, NEITHER for out_of_scope (nothing evaluates).
    deterministic: DeterministicEval | None = None
    judgment: JudgmentEval | None = None
    consistency: ConsistencyEval | None = None

    @model_validator(mode="after")
    def _at_most_one_evaluation_body(self) -> RuleSpec:
        # A pure structural invariant, safe to check early. The kind↔body match is checked at LOAD
        # time (after the CSV consistency cross-check), so a kind-vs-CSV mismatch is reported first.
        set_count = sum(
            body is not None for body in (self.deterministic, self.judgment, self.consistency)
        )
        if set_count > 1:
            raise ValueError(
                f"spec {self.rule_id}: set exactly one of deterministic / judgment / consistency"
            )
        return self


def _check_consistency(spec: RuleSpec, rk: RuleKind) -> None:
    """Assert the spec agrees with the rule's ``rule_kinds.csv`` row (fail loud).

    The CSV (LP-301) is the single gate of record; the spec must not diverge on the
    classification (``kind`` / ``numeric_check``) or the validation gate
    (``priya_validated`` / ``threshold_needs_signoff``).
    """
    mismatches: list[str] = []
    if spec.kind is not rk.kind:
        mismatches.append(f"kind: spec={spec.kind!r} vs rule_kinds.csv={rk.kind!r}")
    if spec.numeric_check != rk.numeric_check:
        mismatches.append(
            f"numeric_check: spec={spec.numeric_check} vs rule_kinds.csv={rk.numeric_check}"
        )
    if spec.reference_values.priya_validated != rk.priya_validated:
        mismatches.append(
            f"priya_validated: spec={spec.reference_values.priya_validated} vs "
            f"rule_kinds.csv={rk.priya_validated}"
        )
    if spec.reference_values.threshold_needs_signoff != rk.threshold_needs_signoff:
        mismatches.append(
            f"threshold_needs_signoff: spec={spec.reference_values.threshold_needs_signoff} vs "
            f"rule_kinds.csv={rk.threshold_needs_signoff}"
        )
    if mismatches:
        raise RuleSpecInconsistent(
            f"spec {spec.rule_id} disagrees with rule_kinds.csv: " + "; ".join(mismatches)
        )


def _load_spec_from(specs_dir: Path, rule_id: str) -> RuleSpec:
    """Read + validate ``<specs_dir>/<rule_id>.yaml`` and cross-check it vs the kinds
    table. Uncached and directory-parameterized so tests can point it at a temp dir.

    Raises :class:`RuleSpecNotFound` (no file), :class:`RuleSpecInvalid` (unparseable /
    missing slots / rule_id-filename mismatch / not in the kinds table), or
    :class:`RuleSpecInconsistent` (disagrees with ``rule_kinds.csv``).
    """
    path = specs_dir / f"{rule_id}.yaml"
    if not path.is_file():
        raise RuleSpecNotFound(f"no rule spec for {rule_id!r} at {path}")

    try:
        raw = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        raise RuleSpecInvalid(f"spec {rule_id} is not valid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise RuleSpecInvalid(f"spec {rule_id} must be a YAML mapping, got {type(raw).__name__}")

    try:
        spec = RuleSpec.model_validate(raw)
    except ValidationError as exc:
        raise RuleSpecInvalid(f"spec {rule_id} is missing/has invalid slots: {exc}") from exc

    if spec.rule_id != rule_id:
        raise RuleSpecInvalid(f"spec rule_id {spec.rule_id!r} does not match filename {rule_id!r}")

    rk = kind_for(rule_id)
    if rk is None:
        # A spec without a kinds-table row cannot be consistency-checked — fail loud
        # rather than ship an unclassified, un-gated rule.
        raise RuleSpecInvalid(f"spec {rule_id} has no row in rule_kinds.csv (LP-301)")
    _check_consistency(spec, rk)  # CSV cross-check FIRST (a kind mismatch surfaces here)
    _check_evaluation_body(spec)  # then the LP-324 kind↔evaluation-body match
    return spec


def _check_evaluation_body(spec: RuleSpec) -> None:
    """The kind must carry its matching machine-readable body (LP-324/325): deterministic for
    calculative, deterministic OR consistency for structural (a structural rule can be a per-subject
    check OR a cross-source consistency check), judgment for judgmental, NEITHER for out_of_scope."""
    det = spec.deterministic is not None
    jud = spec.judgment is not None
    con = spec.consistency is not None
    if spec.kind is RuleKindName.CALCULATIVE and not det:
        raise RuleSpecInvalid(
            f"spec {spec.rule_id}: calculative rule needs a `deterministic` block"
        )
    if spec.kind is RuleKindName.STRUCTURAL and not (det or con):
        raise RuleSpecInvalid(
            f"spec {spec.rule_id}: structural rule needs a `deterministic` or `consistency` block"
        )
    if spec.kind is RuleKindName.JUDGMENTAL and not jud:
        raise RuleSpecInvalid(f"spec {spec.rule_id}: judgmental rule needs a `judgment` block")
    if spec.kind is RuleKindName.OUT_OF_SCOPE and (det or jud or con):
        raise RuleSpecInvalid(f"spec {spec.rule_id}: out_of_scope rule carries no evaluation body")


@cache
def load_rule_spec(rule_id: str) -> RuleSpec:
    """Load the validated, kinds-consistent :class:`RuleSpec` for ``rule_id``.

    The evaluator's ONLY entry point (LP-304 will call just this). Reads the co-located
    YAML today; a DB-backed source later is a drop-in — callers must not care where the
    spec lives. Cached (specs are immutable, version-controlled artifacts).
    """
    return _load_spec_from(_SPECS_DIR, rule_id)
