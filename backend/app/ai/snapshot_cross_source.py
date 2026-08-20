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
from dataclasses import dataclass, field
from typing import Any

from app.ai.client import complete
from app.ai.parsing import extract_json_object
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_MAX_TOKENS = 8192

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
- a missing document on its own (the needs list tracks those)
- a ratio being high or low (the calculators judge those)
- anything you cannot point at two sources for
- a restatement of a single value with nothing to compare it to

Also say when figures that LOOK inconsistent are actually consistent — a balance declining across \
dated documents is amortization, not a discrepancy. A processor's time is the scarce resource.

Return ONLY a JSON object:
{"findings": [
  {"kind": "<short_snake_case_category>",
   "title": "<one line, what the pairing is>",
   "detail": "<2-3 sentences: the two facts, and what a processor should confirm>",
   "sources": [{"label": "<where this came from>", "value": "<the figure or fact>"}, ...]}
]}

Write for a processor. Name documents the way the file names them. No markdown, no preamble."""


@dataclass(frozen=True)
class SnapshotFindingDraft:
    """One observation, before persistence."""

    kind: str
    title: str
    detail: str
    sources: list[dict[str, str]] = field(default_factory=list)

    @property
    def finding_key(self) -> str:
        """CONTENT IDENTITY — the same observation on a later run hashes the same.

        Over the kind and the SOURCES, never the title or detail: those are the model's wording and
        will drift between calls even at temperature 0. Hashing them would mint a new finding for a
        reworded sentence, and a processor's dismissal would evaporate — the failure that would make
        this tab worse than useless.
        """
        material = json.dumps(
            {
                "kind": self.kind,
                "sources": sorted(json.dumps(s, sort_keys=True) for s in self.sources),
            },
            sort_keys=True,
        )
        return hashlib.sha256(material.encode()).hexdigest()


def _parse(text: str) -> list[SnapshotFindingDraft]:
    """Defensive parse — a malformed response yields NO findings, never a raise and never a guess."""
    payload = extract_json_object(text)
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
