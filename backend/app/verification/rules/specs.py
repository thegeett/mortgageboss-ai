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

from functools import cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ValidationError
from pydantic import Field as PydField

from app.verification.rules.kinds import RuleKind, RuleKindName, kind_for

# The spec files live co-located with the rules, one YAML per rule_id (AS-1.yaml).
_SPECS_DIR = Path(__file__).with_name("specs")


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

    large_deposit_threshold: str = PydField(min_length=1)
    priya_validated: bool
    threshold_needs_signoff: bool


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
    subject_enumeration: str = PydField(min_length=1)
    subject_key_fields: tuple[str, ...] = PydField(min_length=1)
    evidence_required: str = PydField(min_length=1)
    guideline_reference: str = PydField(min_length=1)
    spec_version: int = PydField(ge=1)


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
    _check_consistency(spec, rk)
    return spec


@cache
def load_rule_spec(rule_id: str) -> RuleSpec:
    """Load the validated, kinds-consistent :class:`RuleSpec` for ``rule_id``.

    The evaluator's ONLY entry point (LP-304 will call just this). Reads the co-located
    YAML today; a DB-backed source later is a drop-in — callers must not care where the
    spec lives. Cached (specs are immutable, version-controlled artifacts).
    """
    return _load_spec_from(_SPECS_DIR, rule_id)
