"""The uniform verification-rule structure (LP-74) — the two linchpins.

Every verification rule, whatever layer it comes from (regulatory / investor /
overlay), shares **one** structure. Two properties of that structure are the
linchpins that make the three-layer composition possible:

1. **A stable ``rule_id``** (e.g. ``"conv.dti.back_end_max"``). It is the rule's
   identity. A lender overlay overrides a rule *by this id*; without a stable id
   an overlay would have nothing to reference and overlays would be impossible to
   bolt on.

2. **The threshold is DATA, not code** (:class:`Condition` — an operator plus a
   value). The rule *logic* (:func:`satisfies`) is fixed; the *threshold* lives
   in the rule record as data the logic reads. Because the threshold is data, an
   overlay can supply a different value and the **same** logic evaluates against
   it. This is what lets an overlay deviate from an investor default without
   re-implementing the check.

Rules are **definitions**, not per-file rows: config-like, declared in code
(:mod:`app.verification.rules.samples`) and seedable. A verification *run* is
per-file (it reads one file's typed values); the rule *definitions* are shared.

This module is pure (no DB, no AI). It is the structure plus the deterministic
comparison primitive. The real ~60 Conventional + ~50 FHA rules are LP-82..85;
LP-74 ships a few SAMPLE rules to exercise the engine.
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, model_validator

from app.models.finding import FindingCategory
from app.models.lender import LoanProgram


class RuleLayer(StrEnum):
    """Which of the three composing layers a rule belongs to.

    ``REGULATORY`` applies to all loans (TRID / AML / fair-lending);
    ``INVESTOR`` is per-program (Fannie for Conventional, HUD for FHA) and is the
    **default**; ``OVERLAY`` is a per-lender custom rule added on top.
    """

    REGULATORY = "regulatory"
    INVESTOR = "investor"
    OVERLAY = "overlay"


class RuleSeverity(StrEnum):
    """The finding severity a rule emits *on failure* (maps to FindingStatus).

    A passing rule emits a green finding regardless; this is the colour used when
    the condition is **not** satisfied.
    """

    RED = "red"  # blocking
    YELLOW = "yellow"  # review / compensating factor


class Operator(StrEnum):
    """The comparison a rule's condition applies (observed ``op`` threshold)."""

    LE = "<="
    LT = "<"
    GE = ">="
    GT = ">"
    EQ = "=="
    NE = "!="


class ApplicabilityScope(StrEnum):
    """How a rule's applicability is decided when resolving a file's rule set."""

    ALL_LOANS = "all_loans"  # regulatory — every file
    PROGRAM = "program"  # investor — Conventional OR FHA
    LENDER = "lender"  # overlay custom rule — one lender


class Applicability(BaseModel):
    """Which files a rule applies to (drives composition / rule selection)."""

    model_config = ConfigDict(frozen=True)

    scope: ApplicabilityScope
    # Set when scope is PROGRAM — the investor program this rule belongs to.
    program: LoanProgram | None = None
    # Set when scope is LENDER — the lender slug a custom overlay rule targets.
    lender: str | None = None

    @model_validator(mode="after")
    def _check_scope(self) -> Applicability:
        if self.scope is ApplicabilityScope.PROGRAM and self.program is None:
            raise ValueError("program applicability requires a program")
        if self.scope is ApplicabilityScope.LENDER and self.lender is None:
            raise ValueError("lender applicability requires a lender slug")
        return self


class Condition(BaseModel):
    """THE THRESHOLD-AS-DATA — an operator plus a value the rule logic reads.

    The rule *logic* (:func:`satisfies`) is fixed; the *threshold* is this data.
    An overlay overrides a rule by swapping this :class:`Condition` for a
    different value, and the same :func:`satisfies` evaluates against the new
    threshold. ``unit`` is descriptive metadata (``"percent"`` / ``"days"`` /
    ``"usd"``), not part of the comparison.
    """

    model_config = ConfigDict(frozen=True)

    op: Operator
    value: Decimal
    unit: str | None = None


class RuleSource(BaseModel):
    """A structured, durable citation for a rule (auditability).

    Prefer the durable :attr:`section` reference (e.g. ``"B1-1-03"``) over a deep
    :attr:`url` — Selling Guide URLs rot, section numbers persist. :attr:`retrieved`
    records when the value was researched (the Guide changes frequently). Set
    :attr:`to_verify` when the section is uncertain — never fabricate one.
    """

    model_config = ConfigDict(frozen=True)

    type: str  # e.g. "investor_guide" / "regulation" / "documentation_standard"
    citation: str  # e.g. "Fannie Mae Selling Guide B3-6-02"
    section: str | None = None  # the durable section reference, e.g. "B1-1-03"
    url: str | None = None
    retrieved: str | None = None  # when the value was researched, e.g. "2026-06"
    to_verify: bool = False  # the section/value is uncertain — verify, don't trust


class VerificationRule(BaseModel):
    """One verification rule — the uniform structure shared by all three layers.

    Carries a **stable** :attr:`rule_id`, the :attr:`layer`, its
    :attr:`applicability`, the typed field(s) it :attr:`reads`, the
    :attr:`condition` (threshold-as-data), the :attr:`severity` it emits on
    failure, the finding :attr:`category`, a human :attr:`description`, and a
    structured :attr:`source` citation.

    :attr:`overlay_applied` is *provenance*: ``None`` for a base rule, and the
    lender slug when an overlay has patched this rule's threshold during
    composition. The rule's identity (``rule_id``) and logic are unchanged — only
    the threshold differs — so this records *that* a patch happened for the audit
    trail without changing what the rule *is*.
    """

    model_config = ConfigDict(frozen=True)

    rule_id: str
    layer: RuleLayer
    applicability: Applicability
    reads: tuple[str, ...]  # typed field path(s) — never prose
    condition: Condition  # threshold-as-data
    severity: RuleSeverity
    category: FindingCategory
    description: str
    source: RuleSource
    overlay_applied: str | None = None
    # STARTER content (LP-82+): grounded in research but pending the domain expert's
    # validation against the live guide for her lenders/scenarios — NOT authoritative.
    starter: bool = False
    # Free-text caveats: "recently changed", "DU-message-driven", "typed-core promotion
    # pending: <fact>", etc. — the validate-with-Priya / promotion notes.
    notes: str | None = None

    def with_condition(self, condition: Condition, *, overlay: str) -> VerificationRule:
        """Return a copy with the threshold replaced (identity/logic unchanged).

        Used by overlay application: only :attr:`condition` changes and
        :attr:`overlay_applied` records which lender patched it. ``rule_id``,
        ``reads``, ``layer`` and the comparison logic are all preserved.
        """
        return self.model_copy(update={"condition": condition, "overlay_applied": overlay})


# --- The deterministic comparison primitive (the rule LOGIC, fixed) ----------

_COMPARATORS: dict[Operator, Callable[[Decimal, Decimal], bool]] = {
    Operator.LE: lambda observed, threshold: observed <= threshold,
    Operator.LT: lambda observed, threshold: observed < threshold,
    Operator.GE: lambda observed, threshold: observed >= threshold,
    Operator.GT: lambda observed, threshold: observed > threshold,
    Operator.EQ: lambda observed, threshold: observed == threshold,
    Operator.NE: lambda observed, threshold: observed != threshold,
}


def satisfies(condition: Condition, observed: Decimal) -> bool:
    """Evaluate ``observed <op> condition.value`` — the fixed rule logic.

    This is the *only* place a threshold comparison happens. It reads the
    threshold from the :class:`Condition` data, so the identical call evaluates a
    base rule and an overlay-patched rule alike. Pure and deterministic.
    """
    return _COMPARATORS[condition.op](observed, condition.value)
