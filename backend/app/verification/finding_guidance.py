"""AI-generated finding guidance — "why it matters" + "suggested fix" (LP-96).

This is the ONE deliberate, guard-railed relaxation of the project's "AI never touches
authoritative output" principle: every finding carries an AI-authored **why it matters** (the
consequence) + **suggested fix** (the remediation), so it explains not just WHAT fired + WHY-it-
fired (deterministic, already stored) but WHY-it-matters + HOW-to-fix (AI help). It is
decision-SUPPORT, not automation — the processor reads it and overrides the finding if they
disagree; the deterministic core (what + source + citation) and human judgment still decide.

The guardrails that make this safe:

* **Generated once, stored, NEVER per-run.** Guidance is keyed **per canonical finding type**
  (``income_variance``, ``employer_mismatch``, …) — the key both the deterministic ``xsrc.*``
  rules and the AI cross-source findings share — so one authored entry serves every finding of a
  type. It is resolved by a plain dict lookup at read time (or stored on a novel finding at
  discovery); rendering a card / re-running verification makes **no model call** and yields the
  identical text every time (no flicker, no per-view cost).
* **Grounded in the rule's facts.** The generator is given the rule/type + its category +
  description + threshold and asked to EXPLAIN those in plain English — not to invent facts or
  cite regulations it wasn't given.
* **Grounded-starter, validate-with-Priya.** ``starter=True`` — the content is researched-and-
  grounded but NOT authoritative; the domain expert confirms/corrects it, exactly like the rule
  thresholds.
* **Warned + visually distinct + overrideable** — enforced at the display (the frontend).

The committed :data:`GUIDANCE_BY_TYPE` is the **grounded-starter** content (authored deterministically
from each type's meaning). :func:`generate_guidance` is the AI-authoring mechanism — the one-time,
idempotent generation pass (``scripts/generate_finding_guidance.py``) and the novel-finding
discovery path call it to produce richer, lender-specific prose (validate-with-Priya). It reuses
the app's LLM path at low temperature and degrades gracefully on failure (no guidance → the card
still renders, LP-95).
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from app.ai.client import AIClientError, complete
from app.ai.parsing import extract_json_object
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# Keys the frontend reads (LP-95's slots + the grounded-starter marker).
WHY_KEY = "why_it_matters"
FIX_KEY = "suggested_fix"
STARTER_KEY = "guidance_starter"


@dataclass(frozen=True)
class RuleGuidance:
    """One finding type's guidance — the AI help shown in LP-95's why/fix slots."""

    why_it_matters: str  # the consequence — why the processor should care
    remediation: str  # the suggested fix — how to resolve it
    starter: bool = True  # grounded-starter (validate-with-Priya), never authoritative


# The grounded-starter store, keyed by canonical finding TYPE — the key shared by the
# deterministic xsrc.* rules (``rule.canonical_type``) and the AI findings (``raw.type``). One
# entry serves every finding of a type. Regenerate via scripts/generate_finding_guidance.py.
GUIDANCE_BY_TYPE: dict[str, RuleGuidance] = {
    "income_variance": RuleGuidance(
        why_it_matters=(
            "The income used to qualify comes from the documents. A gap between the stated and "
            "documented income means the DTI (and the max-loan) may be computed on the wrong "
            "figure — usually overstated income, which understates the DTI the file must pass."
        ),
        remediation=(
            "Reconcile the stated income against the pay stubs / W-2 / VOE, correct the stated "
            "figure (or document the variance — e.g. variable income averaged per the guide), and "
            "re-run so the DTI recomputes."
        ),
    ),
    "employer_mismatch": RuleGuidance(
        why_it_matters=(
            "A documented employer that isn't among the stated employers can signal undisclosed "
            "employment, a recent job change, or a data-entry error — each changes the "
            "employment/income picture underwriting relies on."
        ),
        remediation=(
            "Confirm the employer against the pay stub / VOE and the 1003; add or correct the "
            "employer, or document the difference (e.g. a DBA vs. the legal name)."
        ),
    ),
    "gift_discrepancy": RuleGuidance(
        why_it_matters=(
            "Gift funds need a signed gift letter and a paper trail. An unsupported or mismatched "
            "gift can make the funds ineligible for the down payment / reserves and is a common "
            "audit finding."
        ),
        remediation=(
            "Obtain the signed gift letter + donor-ability / transfer evidence, or reclassify the "
            "funds; make the stated gift match the documented amount."
        ),
    ),
    "asset_discrepancy": RuleGuidance(
        why_it_matters=(
            "Reserves and funds-to-close are verified from the asset statements. A gap between "
            "stated and documented assets can leave the file short of required reserves or mask a "
            "large deposit that must be sourced."
        ),
        remediation=(
            "Reconcile the stated assets to the statements, source any large / unsourced deposits, "
            "and correct the stated figure."
        ),
    ),
    "liability_discrepancy": RuleGuidance(
        why_it_matters=(
            "An obligation on the credit report but not disclosed raises the DTI once it's counted. "
            "Missing it understates the DTI and risks a condition — or a denial — at underwriting."
        ),
        remediation=(
            "Add the documented obligation (or document why it's excluded — paid-by-other, "
            "deferred, < 10 payments), then re-run so the DTI recomputes with it."
        ),
    ),
    "property_address_discrepancy": RuleGuidance(
        why_it_matters=(
            "The subject property drives the appraisal, the LTV, and occupancy. An address mismatch "
            "across documents can mean the wrong property, an occupancy misstatement, or a typo "
            "that breaks the file's identity."
        ),
        remediation=(
            "Confirm the subject address against the appraisal / contract / title and correct the "
            "mismatched source; if it's a borrower's other address, label it as such."
        ),
    ),
    "co_borrower_discrepancy": RuleGuidance(
        why_it_matters=(
            "Co-borrower details flow into the credit pull, the qualifying income, and vesting. An "
            "inconsistency can mean a missing party, an identity mismatch, or a vesting error."
        ),
        remediation=(
            "Confirm each borrower across the application and the documents; add or correct the "
            "party, or document the difference."
        ),
    ),
    "identity_discrepancy": RuleGuidance(
        why_it_matters=(
            "Name, SSN, and date of birth must be consistent across sources. A mismatch is a "
            "data-integrity — and potential fraud / identity — flag that underwriting will condition "
            "on."
        ),
        remediation=(
            "Verify the identity fields against the government ID / credit / 1003; correct the typo, "
            "or escalate if it isn't a clerical difference."
        ),
    ),
    "missing_documentation": RuleGuidance(
        why_it_matters=(
            "A stated item without supporting documentation can't be verified. It may be excluded at "
            "underwriting or become a condition that stalls the file."
        ),
        remediation=(
            "Request the supporting document (or document why it isn't needed), then attach it so "
            "the item can be verified."
        ),
    ),
    "other": RuleGuidance(
        why_it_matters=(
            "This is a novel cross-source discrepancy the AI surfaced — it isn't mapped to a known "
            "rule, so treat it as a lead to verify, not a confirmed defect."
        ),
        remediation=(
            "Verify the discrepancy against the underlying documents; correct the data, or "
            "document / override with a reason."
        ),
    ),
}

# A per-category fallback so a finding of an unmapped type still gets grounded guidance.
_CATEGORY_FALLBACK: dict[str, RuleGuidance] = {
    "income": RuleGuidance(
        why_it_matters="Income feeds the DTI and the max-loan — an error here moves the ratios the file must pass.",
        remediation="Reconcile the stated income against the documents and correct or document it, then re-run.",
    ),
    "assets": RuleGuidance(
        why_it_matters="Assets verify reserves and funds-to-close — a gap can leave the file short or mask an unsourced deposit.",
        remediation="Reconcile the stated assets to the statements, source large deposits, and correct the figure.",
    ),
    "credit": RuleGuidance(
        why_it_matters="Credit obligations drive the DTI — a missing or wrong one mis-states the ratio underwriting checks.",
        remediation="Reconcile against the credit report; add, correct, or document the obligation, then re-run.",
    ),
    "property": RuleGuidance(
        why_it_matters="The subject property drives the appraisal, LTV, and occupancy — a discrepancy can misidentify the file.",
        remediation="Confirm against the appraisal / contract / title and correct the mismatched source.",
    ),
    "documentation": RuleGuidance(
        why_it_matters="An unverified item may be excluded at underwriting or become a condition that stalls the file.",
        remediation="Request the supporting document (or document why it isn't needed) and attach it.",
    ),
    "cross_source": RuleGuidance(
        why_it_matters="A stated-vs-documented discrepancy can mean an error or an undisclosed fact underwriting relies on.",
        remediation="Verify against the underlying documents; correct the data, or document / override with a reason.",
    ),
    "regulatory": RuleGuidance(
        why_it_matters="A regulatory check protects compliance — an unresolved one can block the loan or draw an audit.",
        remediation="Address the requirement per the applicable rule, or document the basis for an exception.",
    ),
}


def guidance_for(*, finding_type: str | None, category: str | None) -> RuleGuidance | None:
    """The stored grounded-starter guidance for a finding — by canonical type, else category.

    Deterministic dict lookups only — NO model call. Returns ``None`` when neither the type nor
    the category is known, so the card degrades gracefully (LP-95).
    """
    if finding_type and finding_type in GUIDANCE_BY_TYPE:
        return GUIDANCE_BY_TYPE[finding_type]
    if category and category in _CATEGORY_FALLBACK:
        return _CATEGORY_FALLBACK[category]
    return None


def resolve_guidance(details: dict[str, Any], *, category: str | None) -> dict[str, Any]:
    """The guidance fields to expose on a finding (LP-96), merged for the frontend's slots.

    Prefers guidance stored ON the finding (a novel finding's discovery-time guidance in
    ``details``); otherwise resolves the grounded-starter store by the finding's canonical type
    (``details["type"]``) or category. Returns ``{}`` when there's none — the card then shows just
    the deterministic content (LP-95's graceful degradation). Deterministic; no model call.
    """
    stored_why = details.get(WHY_KEY)
    stored_fix = details.get(FIX_KEY)
    if stored_why or stored_fix:
        return {
            WHY_KEY: stored_why,
            FIX_KEY: stored_fix,
            STARTER_KEY: details.get(STARTER_KEY, True),
        }
    guidance = guidance_for(finding_type=details.get("type"), category=category)
    if guidance is None:
        return {}
    return {
        WHY_KEY: guidance.why_it_matters,
        FIX_KEY: guidance.remediation,
        STARTER_KEY: guidance.starter,
    }


# --------------------------------------------------------------------------- #
# The AI-authoring mechanism — the one-time generation pass + novel discovery
# --------------------------------------------------------------------------- #

CompleteFn = Callable[..., Awaitable[Any]]

_GUIDANCE_SYSTEM_PROMPT = (
    "You help a mortgage loan processor understand a verification finding. You are given the "
    "finding TYPE, its category, the rule's plain description, and its threshold. Explain, in "
    "plain English grounded ONLY in those facts: (1) why_it_matters — the consequence for the "
    "loan file; (2) remediation — the concrete next step to resolve it. Do NOT invent facts, do "
    "NOT cite regulations you were not given, and do NOT restate the finding. Two to three "
    "sentences each. Respond ONLY with a JSON object: "
    '{"why_it_matters": "...", "remediation": "..."}'
)


def build_guidance_prompt(
    *,
    finding_type: str,
    category: str,
    description: str,
    threshold: str | None = None,
) -> str:
    """The grounded user prompt — the rule's FACTS the AI must explain (and nothing more)."""
    lines = [
        f"type: {finding_type}",
        f"category: {category}",
        f"description: {description}",
    ]
    if threshold:
        lines.append(f"threshold: {threshold}")
    return "\n".join(lines)


def _parse_guidance(text: str) -> RuleGuidance | None:
    """Parse the model's JSON into a :class:`RuleGuidance` — never raises."""
    raw = extract_json_object(text)
    if raw is None:
        return None
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None
    why = data.get(WHY_KEY)
    fix = data.get("remediation")
    if not isinstance(why, str) or not isinstance(fix, str) or not why.strip() or not fix.strip():
        return None
    return RuleGuidance(why_it_matters=why.strip(), remediation=fix.strip(), starter=True)


async def generate_guidance(
    *,
    finding_type: str,
    category: str,
    description: str,
    threshold: str | None = None,
    complete_fn: CompleteFn = complete,
) -> RuleGuidance | None:
    """Generate grounded guidance via the AI (the one-time pass + novel discovery) — best-effort.

    Grounds the model in the rule's facts (:func:`build_guidance_prompt`) at low temperature and
    parses defensively. Returns ``None`` on any failure (transport, truncation, unparseable) so
    the caller degrades gracefully — a missing guidance never breaks a finding (LP-95).
    """
    try:
        result = await complete_fn(
            model=settings.anthropic_model_extraction,
            system=_GUIDANCE_SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": build_guidance_prompt(
                        finding_type=finding_type,
                        category=category,
                        description=description,
                        threshold=threshold,
                    ),
                }
            ],
            max_tokens=400,
            temperature=0.0,  # explanatory but STABLE — the same finding reads the same way
        )
    except AIClientError:
        logger.warning("finding_guidance_generation_failed", finding_type=finding_type)
        return None
    return _parse_guidance(result.text)
