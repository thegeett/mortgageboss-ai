"""The snapshot-based cross-source AI pass (LP-586) — the perceiver, over a frozen artifact.

Distinct from `app/ai/cross_source.py` in ONE way that decides everything else: its input is the
persisted SNAPSHOT rather than a context assembled from live tables. The snapshot is the same bytes
on every run until the file genuinely changes, which is what makes a stable answer possible at all.

WHAT IT LOOKS FOR: a fact in one source that can be checked against a fact in another. Not rule
verdicts — the rule engine already reasons over this same snapshot and says what it can prove. This
pass exists for the pairings NOBODY WROTE A RULE FOR: a tax bill's assessed value beside a stated
valuation with no appraisal; a tax bill naming two owners beside an application with one borrower;
W-2 totals beside a pay-stub run rate.

IT NOTICES; IT DOES NOT JUDGE. There is no rule spec here, no calibrated threshold, no guideline
citation — so a finding may never write to the loan. The processor's actions are sign-off, dismiss,
note and request-docs, and nothing that changes a number.

Temperature 0 and a fixed schema, but neither makes an LLM deterministic — stability comes from the
caller not asking again while the snapshot fingerprint holds (see `snapshot_findings/fingerprint.py`).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from app.ai.client import complete
from app.ai.parsing import extract_json_object
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_MAX_TOKENS = 8192

#: The ONLY kinds a finding may carry. Identity hashes this, so it must be a closed set — a
#: model-authored slug drifts between runs and takes every dismissal with it (LP-598).
_KINDS = frozenset(
    {
        "value_mismatch",
        "identity_mismatch",
        "date_inconsistency",
        "undisclosed_obligation",
        "calculation_blocked",
        "other",
    }
)

SNAPSHOT_CROSS_SOURCE_PROMPT = """\
You review a mortgage loan file for a PROCESSOR who is assembling it before underwriting. You are \
given one frozen snapshot of the file: what the application STATES, what the DOCUMENTS say, and the \
computed CALCULATIONS.

Your job is to find facts in one source that can be CHECKED AGAINST a fact in another source, and \
that nobody has reconciled. You are the second pair of eyes on pairings no single check covers.

Report a finding only when you can name BOTH sides and they can be compared. Good examples:
- a value stated on the application against an independent figure in a document
- a document naming parties the application does not
- an income figure against what the pay documents annualise to
- two documents that disagree about the same fact

Do NOT report:
- a missing document on its own (the needs list tracks those). This holds WHATEVER "kind" you would
  give it: "the appraisal is absent so the stated value cannot be verified" and "no credit report, so
  the tradelines cannot be checked" are missing documents, not blocked calculations, and must not be
  reported as calculation_blocked. Use that kind only when a COMPUTED figure — a ratio, a total — is
  named and cannot be produced.
- a ratio being high or low (the calculators judge those)
- anything you cannot point at two sources for
- a restatement of a single value with nothing to compare it to

- agreement. If two figures MATCH, that is not a finding and must not be reported. Where something \
looks inconsistent but is not — a balance declining across dated documents is amortization — the \
right response is SILENCE. A processor's time is the scarce resource, and a tab of confirmations \
costs them the same attention as a tab of problems.

"kind" MUST be exactly one of these — never invent another:
- value_mismatch          two sources state the same fact differently
- identity_mismatch       parties, names, addresses or ownership that do not line up
- date_inconsistency      dates that cannot both be true, or an out-of-sequence event
- undisclosed_obligation  a document shows something the application does not
- calculation_blocked     a computed figure cannot be produced, and you can name what is missing
- other                   a real cross-source pairing none of the above fits

Return ONLY a JSON object:
{"findings": [
  {"kind": "<one of the six above>",
   "title": "<one line, what the pairing is>",
   "detail": "<2-3 sentences: the two facts, and what a processor should confirm>",
   "sources": [{"label": "<where this came from>", "value": "<the figure or fact>"}, ...]}
]}

Write for a processor. Name documents the way the file names them. No markdown, no preamble."""


def _normalise(value: str) -> str:
    """Reduce a model-authored source string to what it MEANS, for identity purposes.

    An essentially-numeric value keeps only its digits, so "551,923", "551923" and "$551,923.00"
    agree. Text is lowercased and punctuation collapsed, so "Tax Bill," and "tax bill" agree while
    "property tax bill" and "tax bill" still differ — those are different claims about provenance.
    """
    text = value.strip().casefold()
    # Numeric: PARSE it, do not just keep the digits. Keeping digits made "$578,000.00" normalise to
    # "57800000" while "578000" gave "578000" — the same amount, two keys, and the dismissal lost.
    candidate = re.sub(r"[,$\s]", "", text)
    if re.fullmatch(r"-?\d+(\.\d+)?", candidate):
        try:
            return str(Decimal(candidate).normalize())
        except InvalidOperation:  # pragma: no cover — the regex already guarantees a valid decimal
            pass
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


@dataclass(frozen=True)
class SnapshotFindingDraft:
    """One observation, before persistence."""

    kind: str
    title: str
    detail: str
    sources: list[dict[str, str]] = field(default_factory=list)

    @property
    def normalised_kind(self) -> str:
        """The kind, forced into the fixed vocabulary (LP-598).

        A model-authored slug is FREE TEXT and drifts exactly as much as the title does. Anything
        outside the six categories collapses to "other" rather than being kept verbatim, because a
        verbatim slug is the thing that broke identity in the first place.
        """
        candidate = self.kind.strip().casefold().replace("-", "_").replace(" ", "_")
        return candidate if candidate in _KINDS else "other"

    @property
    def finding_key(self) -> str:
        """CONTENT IDENTITY — the same observation on a later run hashes the same.

        Over the kind and the SOURCES, never the title or detail: those are the model's wording and
        will drift between calls even at temperature 0. Hashing them would mint a new finding for a
        reworded sentence, and a processor's dismissal would evaporate.

        The SOURCE strings are model-authored too, which the first version missed: it hashed them
        verbatim, so "tax bill"/"551,923" and "property tax bill"/"551923" — the same two facts
        described twice — produced different keys and the dismissal was lost anyway. They are
        normalised first, so identity survives the model's phrasing of its own evidence.

        LP-598 — AND SO IS THE KIND, which was the half of this the first version missed. It hashed
        `kind` VERBATIM while carefully normalising the sources beside it, and `kind` is model-authored
        free text subject to exactly the same drift. Observed on LF-3CVT: one snapshot change renamed
        SEVEN findings at once — `citizenship_documentation` became
        `citizenship_status_no_supporting_documents`, `credit_report_absent` became
        `liability_balances_no_credit_report` — so all seven read as "resolved by a file change" and
        eight identical ones opened beside them. Nothing had resolved. The kind is now drawn from a
        FIXED vocabulary, so it can only change when the model genuinely re-categorises.
        """
        material = json.dumps(
            {
                "kind": self.normalised_kind,
                "sources": sorted(
                    f"{_normalise(s.get('label', ''))}={_normalise(s.get('value', ''))}"
                    for s in self.sources
                ),
            },
            sort_keys=True,
        )
        return hashlib.sha256(material.encode()).hexdigest()


#: Words a TITLE uses to announce a discrepancy, and words a DETAIL uses to report agreement. Kept
#: deliberately small: this pair exists to catch a headline that contradicts its own body, not to
#: police vocabulary. A phrase in one list and nothing from the other is not a contradiction.
_MISMATCH_WORDS = (
    "mismatch",
    "differs",
    "discrepancy",
    "inconsistent",
    "conflict",
    "does not match",
)
_AGREEMENT_WORDS = (
    "figures match",
    "these match",
    "all three agree",
    "figures agree",
    "amounts match",
)


def _claims_mismatch(title: str) -> bool:
    lowered = title.casefold()
    return any(word in lowered for word in _MISMATCH_WORDS)


def _states_agreement(detail: str) -> bool:
    lowered = detail.casefold()
    return any(word in lowered for word in _AGREEMENT_WORDS)


def _parse(text: str) -> list[SnapshotFindingDraft]:
    """Defensive parse — a malformed response yields NO findings, never a raise and never a guess.

    `extract_json_object` returns the JSON SUBSTRING, not a parsed object. The first version checked
    `isinstance(payload, dict)` on that string, which is never true — so every response was
    discarded, the pass produced nothing on any file, and the tab reported "the last run found
    nothing to reconcile" while the model was called and paid for on every run. Every test injected a
    stub reasoner, so nothing exercised this path.
    """
    raw = extract_json_object(text)
    if raw is None:
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, dict):
        return []
    raw = payload.get("findings")
    if not isinstance(raw, list):
        return []
    drafts: list[SnapshotFindingDraft] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        kind, title, detail = item.get("kind"), item.get("title"), item.get("detail")
        if not (isinstance(kind, str) and isinstance(title, str) and isinstance(detail, str)):
            continue
        if not (kind.strip() and title.strip() and detail.strip()):
            continue
        sources = [
            {"label": str(s.get("label", "")), "value": str(s.get("value", ""))}
            for s in item.get("sources", [])
            if isinstance(s, dict)
        ]
        # LP-602 — A MISMATCH WHOSE OWN SOURCES ARE EQUAL. This is the check LP-598 should have
        # written: it compares the VALUES the model cited rather than hunting for a phrase in its
        # prose. Verbatim from staging, titled "Existing mortgage balance differs between application
        # and owned property schedule", kind `value_mismatch`, sources:
        #
        #     owned_property.1.lien_upb                        = "$451,829"
        #     liability.3.unpaid_balance (UNITED WHSLE MORT)   = "$451,829"
        #
        # ...and a detail ending "so they match. No mismatch exists here." LP-598's phrase list held
        # "these match" and the model wrote "they match", so it sailed through — which is the lesson:
        # a wording check is a guess about phrasing, and the numbers are right there.
        #
        # Normalised through `_normalise`, so "$451,829" and "451829.00" count as equal — the same
        # comparison identity already uses.
        values = {_normalise(str(s.get("value", ""))) for s in sources if isinstance(s, dict)}
        claims_a_difference = _claims_mismatch(title) or kind.strip().casefold() == "value_mismatch"
        if claims_a_difference and len(values) == 1:
            continue

        # LP-598 — A FINDING THAT CONTRADICTS ITSELF. The prompt used to invite the model to "say when
        # figures that LOOK inconsistent are actually consistent", and it obliged: LF-3CVT carried
        # `existing_mortgage_balance_mismatch` whose own detail read "These figures match, confirming
        # consistency". The title is what a processor scans, so a mismatch headline over a body that
        # says the figures agree sends them after nothing. The invitation is gone from the prompt; this
        # is the check behind it, narrow on purpose — it fires only on the CONTRADICTION, never on a
        # finding that merely mentions agreement somewhere in its reasoning.
        if _claims_mismatch(title) and _states_agreement(detail):
            continue

        # A finding with fewer than two sources is not CROSS-source — it is an observation about one
        # value, which the rules already cover and which this pass is explicitly told not to report.
        if len(sources) < 2:
            continue
        drafts.append(
            SnapshotFindingDraft(
                kind=kind.strip()[:64],
                title=title.strip(),
                detail=detail.strip(),
                sources=sources,
            )
        )
    return drafts


async def reason_over_snapshot(snapshot_json: str) -> list[SnapshotFindingDraft]:
    """One pass over the snapshot. Never logs the snapshot or the response — counts only (PII)."""
    result = await complete(
        model=settings.anthropic_model_reasoning,
        system=SNAPSHOT_CROSS_SOURCE_PROMPT,
        messages=[{"role": "user", "content": snapshot_json}],
        max_tokens=_MAX_TOKENS,
        temperature=0.0,
    )
    if result.stop_reason == "max_tokens":
        # A cut response leaves the JSON unbalanced and the parser drops EVERYTHING — say so loudly
        # rather than serving an empty tab that looks like a clean file.
        logger.warning(
            "snapshot_cross_source_truncated",
            output_tokens=result.output_tokens,
            max_tokens=_MAX_TOKENS,
        )
    drafts = _parse(result.text)
    logger.info(
        "snapshot_cross_source_done",
        findings=len(drafts),
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
    )
    return drafts


def snapshot_payload(snapshot: Any) -> str:
    """The snapshot as the model sees it — the same object the fingerprint hashes."""
    return json.dumps(snapshot.model_dump(mode="json"), sort_keys=True, default=str)
