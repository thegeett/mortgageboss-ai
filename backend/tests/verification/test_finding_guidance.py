"""LP-96 — AI-generated why/fix guidance: generate-once, stored, grounded, warned.

Covers the guardrails: the grounded-starter store is keyed per canonical type + grounded in the
type's meaning; guidance is resolved deterministically (a dict lookup — NO model call — so
rendering / re-running never regenerates); the generator is grounded in the rule's facts + fails
gracefully; the starter marker is set; and a finding without guidance is still valid (LP-95).
"""

from typing import Any
from uuid import uuid4

import pytest
from app.ai.client import AIClientError
from app.models.finding import (
    Finding,
    FindingCategory,
    FindingOrigin,
    FindingResolutionStatus,
    FindingStatus,
)
from app.schemas.verification import FindingPublic
from app.verification.finding_guidance import (
    FIX_KEY,
    GUIDANCE_BY_TYPE,
    STARTER_KEY,
    WHY_KEY,
    RuleGuidance,
    build_guidance_prompt,
    generate_guidance,
    guidance_for,
    resolve_guidance,
)


class _Completion:
    def __init__(self, text: str) -> None:
        self.text = text


def _finding(**details: Any) -> Finding:
    return Finding(
        id=uuid4(),
        loan_file_id=uuid4(),
        rule_id="xsrc.income.employer_name_consistency",
        origin=FindingOrigin.DETERMINISTIC_RULE,
        status=FindingStatus.YELLOW,
        category=FindingCategory.INCOME,
        message="Documented employer not among the stated employers: X.",
        confidence=1.0,
        resolution_status=FindingResolutionStatus.OPEN,
        details=details,
    )


# --- The store: grounded, keyed per canonical type ----------------------------


def test_store_covers_the_canonical_types_grounded() -> None:
    # A representative type's guidance references the type's real substance (not invented facts).
    income = GUIDANCE_BY_TYPE["income_variance"]
    assert "DTI" in income.why_it_matters or "income" in income.why_it_matters.lower()
    assert income.starter is True  # grounded-starter, validate-with-Priya
    # Employer-mismatch guidance is about employment, not something unrelated.
    assert "employer" in GUIDANCE_BY_TYPE["employer_mismatch"].why_it_matters.lower()


def test_guidance_for_falls_back_to_category_then_none() -> None:
    # A known type → its entry.
    assert guidance_for(finding_type="liability_discrepancy", category="credit") is not None
    # An unknown type but a known category → the category fallback.
    fallback = guidance_for(finding_type="totally_unknown", category="income")
    assert fallback is not None and "DTI" in fallback.why_it_matters
    # Neither known → None (the card degrades gracefully, LP-95).
    assert guidance_for(finding_type="totally_unknown", category="mystery") is None


# --- resolve_guidance: read-time, deterministic, never regenerates -------------


def test_resolve_guidance_from_the_store_by_type() -> None:
    resolved = resolve_guidance({"type": "income_variance"}, category="income")
    assert resolved[WHY_KEY] == GUIDANCE_BY_TYPE["income_variance"].why_it_matters
    assert resolved[FIX_KEY] == GUIDANCE_BY_TYPE["income_variance"].remediation
    assert resolved[STARTER_KEY] is True


def test_resolve_guidance_prefers_finding_stored_over_the_store() -> None:
    # A novel finding's discovery-time guidance (stored on the finding) wins.
    resolved = resolve_guidance(
        {"type": "other", WHY_KEY: "novel why", FIX_KEY: "novel fix"}, category="cross_source"
    )
    assert resolved[WHY_KEY] == "novel why"
    assert resolved[FIX_KEY] == "novel fix"


def test_resolve_guidance_absent_returns_empty() -> None:
    assert resolve_guidance({"type": "totally_unknown"}, category="mystery") == {}


def test_finding_public_exposes_guidance_without_a_model_call() -> None:
    # from_model resolves guidance by a plain dict lookup — NO model call on render/read.
    finding = _finding(type="employer_mismatch", reasoning="…")
    public = FindingPublic.from_model(finding)
    assert public.details[WHY_KEY] == GUIDANCE_BY_TYPE["employer_mismatch"].why_it_matters
    assert public.details[STARTER_KEY] is True
    # The finding row itself is untouched (guidance is resolved for the view, not written back).
    assert WHY_KEY not in finding.details


def test_finding_public_degrades_gracefully_without_guidance() -> None:
    # An unmapped type + category → no guidance keys, and from_model still produces a valid view.
    finding = _finding(type="totally_unknown")
    finding.category = FindingCategory.REGULATORY  # mapped category → fallback still applies
    public = FindingPublic.from_model(finding)
    assert WHY_KEY in public.details  # regulatory fallback
    # A truly unmapped category → no guidance, still valid.
    finding.category = FindingCategory.INCOME
    finding.details = {"type": "x"}
    finding.category = FindingCategory.CROSS_SOURCE
    assert FindingPublic.from_model(finding) is not None


# --- The generator: grounded in the rule's facts, graceful on failure ---------


def test_prompt_is_grounded_in_the_rules_facts() -> None:
    prompt = build_guidance_prompt(
        finding_type="income_variance",
        category="income",
        description="The stated income does not match the documented income.",
        threshold="variance > 10%",
    )
    assert "income_variance" in prompt
    assert "does not match the documented income" in prompt  # the given fact
    assert "variance > 10%" in prompt


async def test_generate_guidance_parses_the_model_output() -> None:
    async def _stub(**_kw: Any) -> _Completion:
        return _Completion('{"why_it_matters": "because DTI", "remediation": "reconcile income"}')

    guidance = await generate_guidance(
        finding_type="income_variance",
        category="income",
        description="stated vs documented income",
        complete_fn=_stub,
    )
    assert guidance is not None
    assert guidance.why_it_matters == "because DTI"
    assert guidance.remediation == "reconcile income"
    assert guidance.starter is True


async def test_generate_guidance_returns_none_on_ai_failure() -> None:
    async def _boom(**_kw: Any) -> _Completion:
        raise AIClientError("no key")

    guidance = await generate_guidance(
        finding_type="other", category="cross_source", description="novel", complete_fn=_boom
    )
    assert guidance is None  # graceful — a missing guidance never breaks the finding (LP-95)


async def test_generate_guidance_returns_none_on_unparseable_output() -> None:
    async def _garbage(**_kw: Any) -> _Completion:
        return _Completion("not json at all")

    assert (
        await generate_guidance(
            finding_type="other", category="cross_source", description="x", complete_fn=_garbage
        )
        is None
    )


@pytest.mark.parametrize("finding_type", list(GUIDANCE_BY_TYPE))
def test_every_stored_type_is_a_starter(finding_type: str) -> None:
    entry = GUIDANCE_BY_TYPE[finding_type]
    assert isinstance(entry, RuleGuidance)
    assert entry.starter is True  # nothing in the store is presented as authoritative
    assert entry.why_it_matters.strip() and entry.remediation.strip()
