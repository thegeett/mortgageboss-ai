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

import re
import string
from decimal import Decimal, InvalidOperation
from functools import cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ValidationError, field_validator, model_validator
from pydantic import Field as PydField

from app.documents.catalog import is_cataloged
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


# The reserved structural tag carrying a document's intrinsic type (LP-329) — INJECTED by the
# ``per_document`` enumerator, so it exists ONLY for per_document subjects. Declared here (the schema
# layer) as the ONE source of the contract: the enumerator imports it, and RuleSpec validates that a
# spec scoping itself on this tag actually enumerates per_document (else its predicate is always
# absent → the rule silently never applies). Not a vocabulary tag (never in fact_tags.csv).
DOC_TYPE_TAG = "document.document_type"

_PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s*%")


def parse_reference_fraction(raw: str) -> Decimal | None:
    """A ``reference_values.values`` entry as a number: a trailing ``%`` → a fraction; else a plain
    Decimal; ``None`` when unusable.

    Lives HERE, beside the data it reads, and is used by BOTH the load-time validator and
    ``deterministic._reference_operand``. Two copies would be free to drift, and a load guard that
    accepts what the evaluator later rejects is worse than no guard: it certifies a threshold that
    silently never applies.
    """
    match = _PERCENT.search(raw)
    if match is not None:
        return Decimal(match.group(1)) / Decimal(100)
    try:
        return Decimal(raw)
    except (InvalidOperation, ValueError):
        return None


def reject_loan_tag(conditions: tuple[TagCondition, ...], field: str) -> None:
    """Fail loud if a `loan_tag` appears where the evaluator reads only the SUBJECT's tag map.

    `loan_tag` (LP-517) is resolved by ``applicability.resolve_applicability`` alone. Every other
    consumer of a :class:`TagCondition` — ``deterministic._tags_hold`` (``when_tags``),
    ``consistency._tag_holds`` (``gather_filter``), ``judgment._guideline_exempts`` (``exempt_when``) —
    does ``subject_tags.get(cond.tag_id)`` with no loan-map fallback. `tag_id` resolves the NAME either
    way, so such a predicate loads cleanly and is then ABSENT on every subject: an `eq` guard silently
    never holds and an `ne` guard always does.

    That is the same shape of trap the `op` comment above warns about, and an author copying LP-517's
    AS-2 applicability pattern into a `when_tags` would fall straight into it. Caught at LOAD until the
    loan map is threaded into those three sites.
    """
    offenders = sorted({c.loan_tag for c in conditions if c.loan_tag is not None})
    if offenders:
        raise ValueError(
            f"`{field}` does not resolve `loan_tag` — {offenders} would be absent on every subject "
            "(an `eq` guard would never hold, an `ne` guard always would). Use a subject `tag`, or "
            "scope the rule with `applicability`, which does read the loan map."
        )


class TagCondition(BaseModel):
    """One tag-value predicate: ``<tag> <eq|ne> <value>`` (applicability + outcome guards)."""

    model_config = {"frozen": True, "extra": "forbid"}

    # Exactly one of `tag` / `loan_tag` (LP-517). `loan_tag` reads the LOAN subject's tag map instead of
    # the current subject's, mirroring the operand DSL's `loan_tag` — a per-subject rule often scopes on a
    # LOAN-level fact (AS-2 is per-deposit but applies only on a PURCHASE). Without it the predicate is
    # absent on every transaction and the rule couldnt_checks all of them, which is worse than unscoped.
    tag: str | None = PydField(default=None, min_length=1)
    loan_tag: str | None = PydField(default=None, min_length=1)
    # eq | ne (string-value equality). ⚠️ Every evaluator spells this `x if op == "eq" else <ne>`, so a
    # THIRD operator added here without also giving those sites a shared comparator would be silently
    # evaluated as `ne` — wrong, and invisible. Widen the pattern and the four call sites together
    # (consistency.py, deterministic.py, judgment.py, applicability.py).
    op: str = PydField(pattern="^(eq|ne)$")
    value: str = PydField(min_length=1)

    @model_validator(mode="after")
    def _exactly_one_source(self) -> TagCondition:
        if (self.tag is None) == (self.loan_tag is None):
            raise ValueError("a TagCondition needs exactly one of `tag` or `loan_tag`")
        return self

    @property
    def tag_id(self) -> str:
        """The tag this condition reads, whichever subject it lives on."""
        return self.tag or self.loan_tag or ""


def _as_conditions(
    applic: TagCondition | tuple[TagCondition, ...] | None,
) -> tuple[TagCondition, ...]:
    """Normalise the one-or-many `applicability` shape to a tuple (LP-517).

    A single condition stays valid and unchanged — every pre-LP-517 spec is a single condition, and the
    YAML for one is still `applicability: {tag: ..., op: ..., value: ...}`. A LIST expresses a
    conjunction: a rule whose scope is two facts (AS-2 is money-IN *and* purchase-only) previously needed
    a bespoke combined tag, which merged two different abstentions and lost the per-predicate reason.
    """
    if applic is None:
        return ()
    return applic if isinstance(applic, tuple) else (applic,)


def _check_applicability_expected(
    expected: bool, applic: TagCondition | tuple[TagCondition, ...] | None
) -> None:
    """Shared validation (LP-330) for ``applicability_expected`` on DeterministicEval / JudgmentEval,
    so they can never diverge. ``applicability_expected`` declares that a MISSING DOCUMENT is a gap, so
    it requires an `applicability` predicate AND that predicate must be the document-type predicate
    (``DOC_TYPE_TAG``): the missing-document resolver names a document type, so scoping the expectation
    on any other tag would emit a document-framed reason for a non-document concern."""
    if not expected:
        return
    conditions = _as_conditions(applic)
    if not conditions:
        raise ValueError(
            "applicability_expected=true requires an `applicability` predicate (it declares WHICH "
            "document is expected)"
        )
    if len(conditions) != 1:
        raise ValueError(
            "applicability_expected=true requires exactly ONE applicability predicate — the "
            "missing-document resolver names a single document type, so a conjunction has no one "
            f"document to report as missing (got {len(conditions)})"
        )
    applic = conditions[0]
    if applic.tag != DOC_TYPE_TAG:
        raise ValueError(
            f"applicability_expected=true requires a document-type applicability (tag {DOC_TYPE_TAG!r})"
            f" — the expectation is that a DOCUMENT is missing; got applicability on {applic.tag!r}"
        )


# The operand TYPES the deterministic evaluator can coerce + compare (LP-328). ``decimal`` is the
# DEFAULT (every pre-LP-328 spec is unchanged); ``date`` unblocks date rules (ID-5, IN-2, PR-6, CL-1,
# CR-6, CR-13). Declaring the KEY SET here (data, no evaluator import) lets a spec be validated at
# LOAD — a typo'd type fails loud rather than as an uncaught KeyError mid-run; the evaluator asserts
# its coercer registry covers exactly this set. Adding a type later = one registry entry + one key.
KNOWN_OPERAND_TYPES = frozenset({"decimal", "date"})


class Operand(BaseModel):
    """A declared OPERAND SOURCE — where a comparison value comes from (tag / reference / calc /
    a product of operands). Exactly one source key is set (validated).

    * ``tag`` — a SUBJECT tag's value, coerced per ``type`` (Decimal / date).
    * ``loan_tag`` (LP-366-A) — a LOAN-subject tag's value, coerced per ``type``. The ONLY operand that
      lets a per-subject rule (AS-1 is per-deposit) read a loan-level fact WITHOUT routing through a
      calculator. Fail-closed: absent/unknown → None → couldnt_check (never 0, never a fallback). Unlike a
      ``calc``'s opaque number, a loan_tag is a GOVERNED FACT — a materialized tag carrying provenance
      (source_facts, reasoning). NOTE: the operand resolves only the tag's VALUE (like every operand); its
      CONFIDENCE is NOT propagated into the comparison — put the tag in ``load_bearing_tags`` if the verdict
      must weigh its confidence (a loan_tag operand's tag need not be load-bearing).
    * ``reference`` — a ``reference_values.values`` key; a trailing ``%`` is parsed to a fraction.
    * ``calc`` — ``[calculator_name, value_key]`` from ``snapshot.calculations`` (a GATED calc → None
      → couldnt_check, LP-318).
    * ``product`` — the product of its operands (AS-1's ``multiplier x qualifying_income``).

    ``type`` (LP-328) declares how a ``tag`` / ``loan_tag`` operand's value is coerced + compared. It
    defaults to ``decimal`` (so every existing spec is unchanged) and a non-decimal type is only valid on
    a ``tag`` / ``loan_tag`` operand — ``reference`` / ``calc`` / ``product`` are decimal by construction.
    """

    model_config = {"frozen": True, "extra": "forbid"}

    tag: str | None = None
    loan_tag: str | None = None
    reference: str | None = None
    calc: tuple[str, str] | None = None
    product: tuple[Operand, ...] | None = None
    type: str = PydField(
        default="decimal"
    )  # decimal (default) | date — the operand's typed coercion

    @model_validator(mode="after")
    def _exactly_one_source_and_valid_type(self) -> Operand:
        set_count = sum(
            x is not None
            for x in (self.tag, self.loan_tag, self.reference, self.calc, self.product)
        )
        if set_count != 1:
            raise ValueError(
                "an Operand sets EXACTLY one of tag / loan_tag / reference / calc / product"
            )
        if self.type not in KNOWN_OPERAND_TYPES:
            raise ValueError(
                f"operand type {self.type!r} is not one of {sorted(KNOWN_OPERAND_TYPES)}"
            )
        if self.type != "decimal" and self.tag is None and self.loan_tag is None:
            raise ValueError(
                f"a non-decimal operand type ({self.type!r}) is only valid on a `tag`/`loan_tag` operand "
                "(reference / calc / product are decimal by construction)"
            )
        # A product MULTIPLIES numbers — every factor must be decimal. A non-decimal factor (e.g. a
        # date tag) would raise `Decimal * date` at eval; catch it at LOAD. Nested products are covered
        # transitively (a sub-product's own type is decimal, and its factors run this same validator).
        if self.product is not None and any(factor.type != "decimal" for factor in self.product):
            raise ValueError(
                "a `product` operand's factors must all be `decimal` — a product multiplies numbers, "
                "so a non-decimal factor (e.g. a `date`) is a category error"
            )
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

    @model_validator(mode="after")
    def _when_tags_are_subject_tags(self) -> OutcomeRule:
        reject_loan_tag(self.when_tags, "when_tags")
        return self


class DeterministicEval(BaseModel):
    """The machine-readable body of a deterministic (calculative/structural) rule (LP-324)."""

    model_config = {"frozen": True, "extra": "forbid"}

    load_bearing_tags: tuple[str, ...] = PydField(min_length=1)
    gated_tags: tuple[str, ...] = PydField(min_length=1)  # the gate-required subset
    applicability: TagCondition | tuple[TagCondition, ...] | None = None  # pre-gate scope filter(s)
    # LP-330: whether the applicability-scoped document is EXPECTED for this file. False (default,
    # LP-329's behavior) → a file with no in-scope subject is not_applicable (§8 Tab 4). True → the
    # document SHOULD exist, so its confident absence is a GAP → couldnt_check (§8 Tab 1, BLOCKS). Only
    # meaningful with `applicability` (validated). Fixes ID-7's live false-green (missing title on a
    # purchase).
    applicability_expected: bool = False
    operands: dict[str, Operand] = PydField(default_factory=dict)
    outcomes: tuple[OutcomeRule, ...] = PydField(min_length=1)
    # LP-524 — the fix for a COULDN'T-CHECK, which no rule could carry before.
    #
    # `how_to_fix` lives on an OUTCOME, and the gate short-circuits before any outcome runs — so every
    # "we could not check this" finding reached a processor with no action at all. On the first real
    # file that was 15 of 25 items in the queue: each one names a missing fact and none says which
    # document would supply it. Declared here rather than per-outcome because the gate has no outcome to
    # attach it to, and the ask is the same whichever gated tag was missing: get the document.
    couldnt_check_fix: str | None = None
    # LP-525 — facts from the subject's own document, for the WORDING only. See :class:`SubjectFact`.
    subject_facts: dict[str, SubjectFact] = PydField(default_factory=dict)
    confidence_floor: float = 0.5

    @model_validator(mode="after")
    def _couldnt_check_fix_placeholders_resolve(self) -> DeterministicEval:
        """A stray placeholder raises at format time — mid-run, inside a Celery task. Caught at LOAD."""
        if self.couldnt_check_fix is None:
            return self
        try:
            fields = _template_fields(self.couldnt_check_fix)
        except ValueError as exc:
            raise ValueError(f"couldnt_check_fix is malformed: {exc}") from exc
        if unknown := sorted(fields - set(self.subject_facts)):
            raise ValueError(
                f"couldnt_check_fix references unknown placeholder(s) {unknown} — declare them in "
                f"`subject_facts` (declared: {sorted(self.subject_facts)})"
            )
        return self

    @model_validator(mode="after")
    def _applicability_expected_needs_document_applicability(self) -> DeterministicEval:
        _check_applicability_expected(self.applicability_expected, self.applicability)
        return self

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
                # A comparison's two operands must be the SAME type (LP-328): comparing a date to a
                # Decimal is a category error that would raise/mis-compare at runtime — catch at LOAD.
                left_t = self.operands[outcome.when_compare.left].type
                right_t = self.operands[outcome.when_compare.right].type
                if left_t != right_t:
                    raise ValueError(
                        f"when_compare compares operands of different types "
                        f"({outcome.when_compare.left!r}:{left_t} vs "
                        f"{outcome.when_compare.right!r}:{right_t}) — they must match"
                    )
            # reasoning is `str.format(**operands)` at eval time — a stray brace or an unknown
            # placeholder would crash the run, so both are caught at load.
            try:
                fields = _template_fields(outcome.reasoning)
            except ValueError as exc:
                raise ValueError(f"outcome reasoning template is malformed: {exc}") from exc
            # LP-511: `{name}_percent` is a PRESENTATION companion the evaluator supplies for every
            # DECIMAL operand (deterministic._reason_fields) — a ratio interpolated raw prints at full
            # Decimal precision, which is unreadable and (on the read-only query path) gets mangled by
            # the identifier scrub. It resolves to a real operand, so it is accepted here; the suffix
            # is stripped before the membership test rather than added to `operand_names`, so a
            # genuinely unknown `{foo_percent}` still fails loud.
            referenced = {f.removesuffix("_percent") for f in fields}
            unknown = referenced - operand_names
            if unknown:
                raise ValueError(
                    f"outcome reasoning references unknown operand(s) {sorted(unknown)} "
                    f"(operands: {sorted(operand_names)})"
                )
        return self


class Materiality(BaseModel):
    """LP-518 — a SIZE floor scoping a judgment rule's subjects, sized per LOAN PURPOSE.

    AS-12 asked its borrowed-funds question of every money-in deposit at any amount, so a $0.03 interest
    posting produced the same review item as a $20,000 wire. This scopes the rule to deposits big enough
    for the question to be meaningful, with the floor computed (never hard-coded) as
    ``fraction x basis`` — e.g. 50% of monthly qualifying income.

    ⚠️ WHY THIS SCOPES BEFORE ASKING, WHERE ``exempt_when`` DELIBERATELY DOES NOT. The two gates sit
    adjacent on the same rule and resolve opposite ways, so the distinction is load-bearing:

    * ``exempt_when`` is about the deposit's SOURCE. Fannie B3-4.2-02 exempts a readily-identifiable
      source and then adds "however, if ... the lender still has questions as to whether the funds may
      have been borrowed, the lender should obtain additional documentation" — so the model must still
      be ASKED, and only a negative answer is suppressed (LP-516's ask-then-suppress).
    * ``materiality`` is about the deposit's SIZE, and the guideline's own definition is a SCOPE test:
      "a large deposit is defined as a single deposit that exceeds 50% of the total monthly qualifying
      income for the loan." Below the floor it is not a large deposit at all, so there is no obligation
      to have questions about it and nothing for an escape hatch to preserve. Scoping BEFORE the call is
      therefore both correct and the entire cost saving.

    §8 HONESTY — the floor must never absorb a data gap, and equally must never MANUFACTURE one. It has
    exactly two outcomes; couldnt_check is deliberately not among them:

    * observed <= floor, every input resolved (STRICT — the guide says "exceeds") -> not_applicable
    * observed  > floor                                                           -> in scope
    * any input unresolved (no purpose, no basis, unreadable amount)              -> in scope, with the
      finding text saying the floor could not be sized

    The last line is the load-bearing one. A floor is a TRIAGE FILTER this rule adds, not an input its
    question depends on — "does this deposit suggest borrowed funds?" stays answerable from the
    transaction tags when nobody can say what 50% of income is. Failing those subjects to couldnt_check
    would stop asking the model and deliver LESS than before the gate existed.

    The comparison is fixed at strict ``>`` rather than declared, matching the guideline's "exceeds" and
    AS-1's own hard-fire branch. There is deliberately no ``op`` knob: a spec declaring ``<`` here would
    invert the gate's meaning while still reading like a floor.
    """

    model_config = {"frozen": True, "extra": "forbid"}

    observed: Operand  # the subject's size (AS-12: the deposit amount)
    basis: Operand  # what the floor is a fraction OF (AS-12: monthly qualifying income)
    # loan.purpose value -> a `reference_values.values` key holding the fraction ("50%"). Keys, not
    # literals, so every threshold on a rule stays in the one place the spec declares thresholds.
    fraction_by_loan_purpose: dict[str, str] = PydField(min_length=1)
    purpose_tag: str = "loan.purpose"

    @model_validator(mode="after")
    def _fractions_are_reference_keys(self) -> Materiality:
        if any(not key for key in self.fraction_by_loan_purpose.values()):
            raise ValueError("every fraction_by_loan_purpose entry names a reference_values key")
        return self

    @model_validator(mode="after")
    def _operands_are_decimal_tags(self) -> Materiality:
        """`observed`/`basis` may only be decimal `tag`/`loan_tag` operands.

        The judgment evaluator resolves these WITHOUT a snapshot, so a `calc` operand (which must gate
        on the snapshot's calculations) or a `reference` one has nowhere to resolve from and would
        silently read None -> couldnt_check on every subject. A `date` operand is a category error: a
        floor multiplies a fraction by a magnitude.
        """
        for name, operand in (("observed", self.observed), ("basis", self.basis)):
            if operand.tag is None and operand.loan_tag is None:
                raise ValueError(
                    f"materiality `{name}` must be a `tag` or `loan_tag` operand (the judgment "
                    "evaluator resolves it from the subject/loan tag maps, with no snapshot)"
                )
            if operand.type != "decimal":
                raise ValueError(
                    f"materiality `{name}` must be a `decimal` operand, got {operand.type!r} "
                    "(a floor is a fraction of a magnitude)"
                )
        return self


class SubjectFact(BaseModel):
    """One fact from the SUBJECT'S OWN DOCUMENT, named for a message template (LP-525).

    A rule sees only its tags, which is why IH-1's finding could say "the binder does not state a
    dwelling loss-settlement basis" and NOT "…on a policy with Coverage A of $577,000 and a Specified
    Additional Amount for Coverage A endorsement". Those facts are in the snapshot, one step away from
    the rule that most needs them: the tag layer deliberately narrows a document to the few values a
    rule DECIDES on, and everything else — the context that makes a finding legible — is dropped.

    This is the narrow channel back: a spec names the extra facts it wants for its WORDING, and they
    reach the template only. ⚠️ They are NOT inputs — no verdict may turn on them. A fact declared here
    is never gated, never compared, never part of `load_bearing_tags`; if a rule needs to DECIDE on a
    value it must be a tag, with the gate and the distrust layer behind it.

    Exactly one source:

    * ``field`` — a scalar from ``DocumentEntry.fields`` (an extracted typed value).
    * ``list`` + ``item`` — the named LP-437 list, taking ``item`` from each row.
    """

    model_config = {"frozen": True, "extra": "forbid"}

    field: str | None = None
    list: str | None = None
    item: str | None = None  # the row field to take, required with `list`
    limit: int = PydField(default=4, ge=1)  # rows to name before "and N more"
    money: bool = False  # render as $1,234.56

    @model_validator(mode="after")
    def _exactly_one_source(self) -> SubjectFact:
        if (self.field is None) == (self.list is None):
            raise ValueError("a SubjectFact sets exactly one of `field` or `list`")
        if (self.list is None) != (self.item is None):
            raise ValueError("`list` requires `item` (which row field to take), and vice versa")
        return self


class ExplainCase(BaseModel):
    """The WHY and the FIX for one value of a rule's explanatory tag (LP-522)."""

    model_config = {"frozen": True, "extra": "forbid"}

    why: str = PydField(min_length=1)
    how_to_fix: str = PydField(min_length=1)


class Guidance(BaseModel):
    """LP-522 — what a processor should DO, said in their language.

    A judgment finding used to read "the AI judged 'no' — an AI verdict a human must ratify (it never
    auto-ships); $2,000.00 is above the $1,316.67 (10% of $13,166.67 qualifying income) materiality
    floor". That explains our engine, not the loan: it never says what to do, and it says the deposit
    looks fine while sitting in Needs Attention, so a processor cannot tell why it is on their list.

    THREE PARTS, action first:

    * ``action``   — an imperative headline, keyed by the model's VERDICT. "Document the source of …"
      when the answer was no; "Confirm … is not borrowed funds" when it was yes. The verdict shapes the
      WORDING rather than being displayed as a bare `yes`/`no` chip beside it (see below).
    * ``why``      — why this item is in the queue, keyed by an EXPLANATORY TAG rather than the verdict,
      because the reason varies with the evidence, not the answer.
    * ``how_to_fix`` — the concrete step, keyed the same way. Carried on the finding's own
      ``how_to_fix`` field, which judgment rules previously hard-coded to None.

    ⚠️ WHY `why`/`how_to_fix` ARE KEYED ON A TAG AND NOT ON THE VERDICT. A single template has to assume
    a situation, and assumes wrong. "The statement describes it as …, but no matching withdrawal appears
    on file" is right for a self-asserted source and FALSE for a deposit with no description at all.
    Keying on ``explain_by`` (AS-12: `txn.source_strength`, whose four values are derived
    deterministically) gives one correct sentence per situation instead of one sentence that is wrong in
    some of them.

    ⚠️ THIS REVERSES LP-376-B ("the message states the VERDICT"), deliberately and at the product owner's
    direction. For a processor the verdict is the least useful part — especially when it reads "no" and
    the item is still in their queue. It is not hidden: it selects the action, so a `yes` and a `no`
    differ in the first six words and in the fix.
    """

    model_config = {"frozen": True, "extra": "forbid"}

    action: dict[str, str] = PydField(min_length=1)  # verdict value -> imperative headline
    # OPTIONAL (LP-522 phase 2). `action` is keyed on the VERDICT and `explain` on a TAG, so a rule
    # whose distinction already lives in its verdicts has no second axis to key on: CR-8's six values
    # (`one_30_day_late`, `excessive_60_plus`, `not_interpretable`, …) say more than any of the four
    # tags it reasons over would. Omit it and every finding takes `default`, which is the honest shape
    # there — not a degenerate one.
    explain_by: str | None = None
    explain: dict[str, ExplainCase] = PydField(min_length=1)  # tag value -> why + fix

    @model_validator(mode="after")
    def _explain_has_a_fallback(self) -> Guidance:
        """`default` is REQUIRED. The explanatory tag can be absent or carry a value nobody anticipated,
        and a finding with no `why` at all is worse than a generic one — it is the wordless card this
        ticket exists to remove."""
        if "default" not in self.explain:
            named = f"`{self.explain_by}`" if self.explain_by else "the explanatory tag"
            raise ValueError(
                f"guidance.explain needs a `default` case — {named} may be absent or carry an "
                "unanticipated value, and a finding with no explanation is the defect being fixed"
            )
        if self.explain_by is None and set(self.explain) != {"default"}:
            raise ValueError(
                f"guidance.explain has case(s) {sorted(set(self.explain) - {'default'})} but no "
                "`explain_by` tag to select them — they could never be reached"
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
    # LP-329 (GAP-C): a declared document-type / subject predicate. A subject the predicate rules OUT
    # → not_applicable (no gate, no AI, no tag — §8 Tab 4); an ABSENT/"unknown" predicate tag →
    # couldnt_check (cannot tell if it applies). Scopes a per_document judgment (e.g. ID-9 → POA docs)
    # so it does not flood couldnt_check across every non-matching document.
    applicability: TagCondition | tuple[TagCondition, ...] | None = None
    # LP-330: whether the applicability-scoped document is EXPECTED for this file (see DeterministicEval).
    # False (default) → confidently absent = not_applicable (ID-9's POA: irrelevant when none used).
    # True → confidently absent = couldnt_check (§8 Tab 1). Only meaningful with `applicability`.
    applicability_expected: bool = False
    # LP-516 — THE GUIDE'S OWN EXEMPTION, WITH ITS OWN ESCAPE HATCH.
    #
    # `exempt_when` names a predicate under which the guideline says no further review is required, and
    # `exempt_unless_judgment_in` names the judgment values that OVERRIDE the exemption. Both are needed
    # together: Fannie B3-4.2-02 exempts a readily-identifiable source, then adds "however, if ... the
    # lender still has questions as to whether the funds may have been borrowed, the lender should
    # obtain additional documentation". The AI is therefore still ASKED (ask-then-suppress), and only a
    # NEGATIVE answer is suppressed — a positive one still reaches a human.
    #
    # ⚠️ This is NOT "auto-clear a confident no". The clearing is done by the GUIDELINE predicate, which
    # is deterministic; the model's answer can only ever ADD a review, never remove one. A rule that
    # declares neither field behaves exactly as before — every verdict ratification-pending.
    # LP-518 — a LIST is ANY-HOLDS (alternatives), deliberately the opposite of `applicability` above,
    # where a list is ALL-HOLD (a conjunction). That asymmetry mirrors the two concepts: a rule's SCOPE
    # narrows with each added predicate, while an exemption list WIDENS — the guideline itself reads as
    # alternatives ("a direct deposit from an employer (payroll), the Social Security Administration, or
    # IRS or state income tax refund, or a transfer of funds between verified accounts"). Fail-closed is
    # unchanged: a condition whose tag is absent or "unknown" simply does not hold, so an undetermined
    # category still cannot clear a finding.
    exempt_when: TagCondition | tuple[TagCondition, ...] | None = None
    exempt_unless_judgment_in: tuple[str, ...] = ()
    # LP-518 — a per-loan-purpose SIZE floor, applied AFTER `applicability` and BEFORE the gate/AI.
    # See :class:`Materiality` for why this scopes before asking where `exempt_when` does not.
    materiality: Materiality | None = None
    # LP-520 — what each answer in `value_domain` MEANS, in words, for the finding text.
    #
    # A judgment finding read "the AI judged 'yes'", which never states the QUESTION — and on AS-12 the
    # polarity is the counterintuitive one ("yes" = this may be borrowed funds, the BAD answer), while
    # another rule could invert it. The evaluator is generic and has nothing rule-specific to say, so
    # the spec says it. ADDITIVE: a rule declaring none keeps the raw-value text exactly as before.
    verdict_labels: dict[str, str] = PydField(default_factory=dict)
    # LP-522 — action-first finding text. See :class:`Guidance`. Absent → the LP-520 wording, unchanged.
    guidance: Guidance | None = None

    @model_validator(mode="after")
    def _applicability_expected_needs_document_applicability(self) -> JudgmentEval:
        _check_applicability_expected(self.applicability_expected, self.applicability)
        return self

    @model_validator(mode="after")
    def _exempt_override_requires_a_predicate(self) -> JudgmentEval:
        """An override list without a predicate exempts nothing and would read as if it did."""
        if self.exempt_unless_judgment_in and not _as_conditions(self.exempt_when):
            raise ValueError(
                "exempt_unless_judgment_in requires an `exempt_when` predicate (it names the judgment "
                "values that OVERRIDE an exemption; with no exemption there is nothing to override)"
            )
        # An EMPTY list is not None, so it would read as "this rule has an exemption" everywhere while
        # exempting nothing — the LP-516 failure mode (a gate that looks wired and does nothing).
        if self.exempt_when is not None and not _as_conditions(self.exempt_when):
            raise ValueError(
                "`exempt_when` is an empty list — declare at least one condition, or omit the field"
            )
        reject_loan_tag(_as_conditions(self.exempt_when), "exempt_when")
        if outside := sorted(set(self.exempt_unless_judgment_in) - set(self.value_domain)):
            raise ValueError(
                f"exempt_unless_judgment_in references value(s) outside value_domain: {outside}"
            )
        return self

    @model_validator(mode="after")
    def _guidance_is_total_and_its_templates_resolve(self) -> JudgmentEval:
        """Three ways guidance can be silently wrong, all caught here.

        A missing verdict falls back to unlabelled text for exactly that answer; an `explain_by` tag the
        rule never reasons over is absent on every subject, so every finding takes the default; and a
        stray placeholder raises mid-run, in a Celery task, six minutes into an AI pipeline.
        """
        guidance = self.guidance
        if guidance is None:
            return self
        if missing := sorted(set(self.value_domain) - set(guidance.action)):
            raise ValueError(
                f"guidance.action is missing verdict(s) {missing} — a partial map leaves those findings "
                "with no headline, which is the defect this field exists to remove"
            )
        if extra := sorted(set(guidance.action) - set(self.value_domain)):
            raise ValueError(f"guidance.action has verdict(s) outside value_domain: {extra}")
        if guidance.explain_by is not None and guidance.explain_by not in self.reasoned_over:
            raise ValueError(
                f"guidance.explain_by `{guidance.explain_by}` is not in `reasoned_over` — the evaluator "
                "reads the subject's tags through that list, so the tag would be absent on every "
                "subject and every finding would silently take the `default` case"
            )
        # Placeholders resolve against the SHORT name of each reasoned-over tag (txn.amount -> {amount}),
        # because a dot inside a format field means attribute access, not a tag id.
        allowed = {tag_id.split(".")[-1] for tag_id in self.reasoned_over}
        # `{statement_line}` is not a tag — it is the transaction's description, quoted exactly as the
        # statement prints it, so a processor can string-match it against the document. Available only
        # on a per-deposit rule, since nothing else has a transaction to quote.
        if self.subject == "per_deposit":
            allowed.add("statement_line")
        for label, template in (
            *((f"action[{k}]", v) for k, v in guidance.action.items()),
            *(
                (f"explain[{k}].{part}", getattr(case, part))
                for k, case in guidance.explain.items()
                for part in ("why", "how_to_fix")
            ),
        ):
            try:
                fields = _template_fields(template)
            except ValueError as exc:
                raise ValueError(f"guidance.{label} is malformed: {exc}") from exc
            if unknown := sorted(fields - allowed):
                raise ValueError(
                    f"guidance.{label} references unknown placeholder(s) {unknown} — available: "
                    f"{sorted(allowed)} (the short name of each `reasoned_over` tag)"
                )
        return self

    @model_validator(mode="after")
    def _verdict_labels_are_total_over_the_domain(self) -> JudgmentEval:
        """A declared label map must cover EVERY value in `value_domain`.

        A partial map falls back to the raw value for whatever it omits — which is the exact defect
        this field exists to remove, reappearing on the rarest verdict, where nobody would notice. An
        EMPTY map is fine and means "not adopted yet" (the additive default); a partial one is a bug.
        """
        if not self.verdict_labels:
            return self
        declared, domain = set(self.verdict_labels), set(self.value_domain)
        if unknown := sorted(declared - domain):
            raise ValueError(f"verdict_labels has value(s) outside value_domain: {unknown}")
        if missing := sorted(domain - declared):
            raise ValueError(
                f"verdict_labels is missing value(s) {missing} — a partial map silently falls back to "
                "the raw verdict for those, which is the defect it exists to remove"
            )
        return self


# --------------------------------------------------------------------------- #
# LP-325 — the CROSS-SOURCE CONSISTENCY block (the third rule shape): gather a
# fact across sources, exact-compare, AI-judge only the differing residue.
# --------------------------------------------------------------------------- #

# The placeholders a consistency outcome reasoning template may reference (formatted at eval time
# over the gathered set) — validated at LOAD so a stray/unknown placeholder never crashes a run.
_CONSISTENCY_TEMPLATE_FIELDS = frozenset({"values", "sources", "count"})

# The normalizer keys a consistency `normalization` chain may reference. The evaluator maps each key
# to a function; declaring the KEY SET here (data, no evaluator import) lets a spec be validated at
# LOAD — a typo'd key fails loud rather than as an uncaught KeyError mid-run (the rules step is not
# stage-backstopped). The evaluator asserts its function registry covers exactly this set.
KNOWN_NORMALIZERS = frozenset(
    {"strip", "casefold", "collapse_ws", "drop_punct", "date", "drop_entity_suffix"}
)


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
    ``fuzzy`` mode asks the ``judge`` about the differing residue only. ``normalization`` keys are
    validated at LOAD (against :data:`KNOWN_NORMALIZERS`); ``subject`` / ``source_scope`` are resolved
    by the evaluator (which raises on an unknown key), keeping this schema decoupled from the
    enumerator / gather registries.
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
    def _gather_filter_is_a_subject_tag(self) -> ConsistencyEval:
        reject_loan_tag(_as_conditions(self.gather_filter), "gather_filter")
        return self

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
        unknown_norm = set(self.normalization) - KNOWN_NORMALIZERS
        if unknown_norm:
            raise ValueError(
                f"normalization references unknown normalizer(s) {sorted(unknown_norm)} "
                f"(known: {sorted(KNOWN_NORMALIZERS)})"
            )
        # LP-340: drop_entity_suffix matches bare lowercase, punctuation-free tokens ("inc", not "Inc."),
        # so casefold + drop_punct MUST run before it — else it silently under-strips ("Inc."/"INC" survive).
        # Enforce the ordering at LOAD so a misordered chain fails loud, not as a quiet non-match mid-run.
        if "drop_entity_suffix" in self.normalization:
            idx = self.normalization.index("drop_entity_suffix")
            before = self.normalization[:idx]
            missing = [k for k in ("casefold", "drop_punct") if k not in before]
            if missing:
                raise ValueError(
                    f"normalization: `drop_entity_suffix` requires {missing} to run before it "
                    f"(it matches lowercase, punctuation-free tokens); chain was {list(self.normalization)}"
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
    # LP-541 — the document TYPES this rule's inputs come from, so a `couldnt_check` can be sorted into
    # "request this document" versus "read the document you already have". Those are different jobs for
    # a processor: one becomes an outbound request to the borrower, the other is desk work.
    #
    # READ-TIME CLASSIFICATION ONLY. Nothing in evaluation reads this — no verdict, gate, outcome or tag
    # depends on it, so a wrong entry mis-sorts a card and can never change a conclusion. That is the
    # whole reason it is safe to author by hand.
    #
    # `None` means NOT YET DECLARED and is distinct from `[]`, which means "this rule reads no document"
    # (a computed LTV, a MISMO-only field). Without that distinction an un-annotated rule would be
    # indistinguishable from one that needs nothing, and the grouping would silently under-report —
    # the same failure as a badge that only covers the cases we happen to know.
    #
    # ⚠️ A LIST OF ALTERNATIVE GROUPS, not a flat list, and the first version got this wrong. Each inner
    # group is "ANY ONE of these will do"; every group must be satisfied. IN-8 accepts a written OR a
    # verbal VOE, while CR-6 needs the credit report AND a closing date — flattened, both read the same,
    # and CR-6 classified as "read what is here" on a file whose credit report is absent, purely because
    # the Closing Disclosure was present. The distinction is the whole point of the field.
    requires_documents: tuple[tuple[str, ...], ...] | None = None
    spec_version: int = PydField(ge=1)

    @field_validator("requires_documents")
    @classmethod
    def _known_document_types(
        cls, value: tuple[tuple[str, ...], ...] | None
    ) -> tuple[tuple[str, ...], ...] | None:
        """Every slug must be in the document catalog — a typo fails at LOAD, not as a card that
        quietly never matches a document and reports the file as missing something it holds."""
        if value is None:
            return None
        unknown = [slug for group in value for slug in group if not is_cataloged(slug)]
        if unknown:
            raise ValueError(f"requires_documents names uncataloged document type(s): {unknown}")
        if any(not group for group in value):
            raise ValueError("an empty alternative group can never be satisfied — omit it instead")
        return value

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

    @model_validator(mode="after")
    def _materiality_fractions_resolve(self) -> RuleSpec:
        """LP-518 — every fraction key must name a real `reference_values.values` entry AND parse.

        Either failure resolves to None at eval time, which degrades EVERY subject to "reviewed at any
        amount" — the rule would look wired while filtering nothing. Existence is not enough: a value of
        "fifty percent" is present and unreadable, and disables the floor just as silently as a typo'd
        key. Both are caught at LOAD.
        """
        materiality = self.judgment.materiality if self.judgment is not None else None
        if materiality is None:
            return self
        missing, unparseable = [], []
        for key in sorted(set(materiality.fraction_by_loan_purpose.values())):
            raw = self.reference_values.values.get(key)
            if raw is None:
                missing.append(key)
            elif parse_reference_fraction(raw) is None:
                unparseable.append(f"{key}={raw!r}")
        if missing:
            raise ValueError(
                f"spec {self.rule_id}: materiality references reference_values key(s) {missing} "
                f"that are not declared (declared: {sorted(self.reference_values.values)})"
            )
        if unparseable:
            raise ValueError(
                f"spec {self.rule_id}: materiality fraction(s) {unparseable} cannot be read as a "
                "percentage or decimal — the floor would silently never apply"
            )
        return self

    @model_validator(mode="after")
    def _document_type_applicability_requires_per_document(self) -> RuleSpec:
        # DOC_TYPE_TAG is injected ONLY by the per_document enumerator (LP-329). A rule scoping its
        # applicability on it under any other enumeration would find the predicate ABSENT for every
        # subject → couldnt_check for all of them → the rule silently NEVER applies. Catch that (and a
        # typo'd reserved tag) at LOAD rather than as an invisible all-yellow rule.
        applic = None
        if self.deterministic is not None:
            applic = self.deterministic.applicability
        elif self.judgment is not None:
            applic = self.judgment.applicability
        if (
            any(c.tag == DOC_TYPE_TAG for c in _as_conditions(applic))
            and self.subject_enumeration != "per_document"
        ):
            raise ValueError(
                f"spec {self.rule_id}: applicability on {DOC_TYPE_TAG!r} requires "
                f"subject_enumeration: per_document (the tag is injected only for per_document "
                f"subjects), got {self.subject_enumeration!r}"
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
