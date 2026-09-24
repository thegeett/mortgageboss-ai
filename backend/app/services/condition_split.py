"""Splitting an unstructured condition sheet with AI (LP-908, spec §LP-908).

⚠️ USED ONLY WHEN `needs_ai` IS SET, AND IT SPLITS RATHER THAN INTERPRETS. The rules read a layout we
know and give the lender's words exactly, every time, for nothing. This runs when the rules could not
find where one condition ends and the next begins — and even then the model's only job is to draw
those boundaries. It never decides what a condition MEANS, never fills a code the sheet does not
show, and never sees the loan file.

⚠️ EVERY RETURNED STRING IS CHECKED AGAINST THE INPUT BY CODE (spec §9.3). A `verbatim` that is not a
whitespace-normalised substring of the text is DROPPED with a warning, not stored. That check is what
makes "AI only splits" an enforced property rather than a prompt instruction — a model that
paraphrases, tidies or invents cannot get that text into `verbatim_text`, which is the field ADR-405
says carries the lender's own words.

⚠️ NO LOAN SNAPSHOT EVER REACHES THIS CALL (spec §9.4). The only input is the text the processor
pasted, or OCR of rasterized pages. Not the borrower, not the property, not the stated financials —
and not the PDF's raw text layer either, which can carry invisible text (the Phase 4 rasterize-first
decision).

NO NPI IN LOGS (spec §9.5): counts, ids and model names only. Never the pasted text, never a
condition, never a dropped string — a dropped string is by definition text the model produced, and
the safest place for it is the parse report the readonly layer already excludes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import structlog

from app.ai.client import AIClientError, complete
from app.ai.cost import estimate_cost
from app.ai.parsing import extract_json_object
from app.ai.prompt_loader import load_prompt
from app.conditions.readers.lines import normalise
from app.conditions.readers.model import AI_SPLIT_CONFIDENCE, ParsedRow, ParsedSheet
from app.core.config import settings
from app.models.condition import BucketKind, OwnerHint, OwnerHintSource
from app.models.condition_round import ConditionSheetFormat

logger = structlog.get_logger(__name__)

#: ⚠️ `.txt`, WHERE SPEC §LP-908 WRITES `split_v1.md`. Every one of the 125 prompts in the tree is
#: `.txt` and `load_prompt` takes whatever relative path it is given, so the extension carries no
#: meaning — which makes consistency with the repo the only thing at stake. Recorded as a deviation
#: in the ticket rather than taken silently.
PROMPT_PATH = "conditions/split_v1.txt"

#: The splitter's version, recorded in `parse_report` beside the reader's. A re-split months later
#: must be distinguishable from this one (spec §9.6), and the prompt is the thing that changes.
SPLIT_VERSION = "split_v1"

#: A sheet's worth of conditions, generously. The input is capped at 100,000 characters by the paste
#: schema, and the output is the same text re-emitted as JSON plus a little structure.
_MAX_TOKENS = 8192


class ConditionSplitUnavailable(Exception):
    """The model could not be reached, or returned nothing usable.

    ⚠️ TYPED, AND THE ROUND MUST NOT BE LEFT LOOKING SUCCESSFUL (spec §9.8). The caller records a
    failure a processor can act on; it never silently presents an empty split as a read sheet.
    """

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


@dataclass
class SplitOutcome:
    """What the split produced, and what it cost."""

    sheet: ParsedSheet
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_estimate: float = 0.0
    #: Rows the model returned that could not claim a stretch of the input — invented, paraphrased,
    #: assembled from fragments, or a duplicate of a span already taken. Counted, never stored or
    #: logged: the string is the model's own output and could contain anything.
    rejected: int = 0


def _collapse(text: str) -> str:
    """The form both sides of the check are compared in: whitespace collapsed, case preserved.

    ⚠️ COLLAPSED ON BOTH SIDES, because the model re-emits a wrapped condition as one line. The
    sheet prints "Final inspection is required\\n   to confirm..."; the model returns "Final
    inspection is required to confirm...". Those are the same words, and a check that compared them
    literally would call the correct answer an invention. Case is NOT folded: the lender's
    capitalisation is part of the wording, and ignoring it would admit a model that "tidied" a
    sentence into `verbatim_text`.
    """
    return " ".join(normalise(text).split())


class _Coverage:
    """Which stretches of the input have been accounted for, as a PARTITION.

    ⚠️ SPANS, NOT `in`, AND NOT A SET OF SEEN LINES. Both simplifications fail, in ways the substring
    idea alone cannot see, because substring-ness is a property of each row ALONE and says nothing
    about the relationships between rows:

    * **`"..." in text` accepts a row assembled from two distant fragments.** Every word is present
      somewhere, so the test passes while the row is a sentence the lender never wrote. Claiming a
      POSITION instead makes the check "this exact stretch of the sheet", which is what was meant.
    * **The same span returned twice** passes a per-row check twice over, and rule 6's duplicate
      dedup lives in the READER, not on this path — so two identical conditions would arrive at the
      review screen with nothing to remove them. A claimed span cannot be claimed again.
    * **A span crossing a real boundary** — the tail of one condition plus the head of the next — is
      a perfectly valid substring, reads as plausible prose, and is the AI's most natural error on
      exactly the unstructured input this module exists for. Line coverage would call it accounted
      for, because both lines ARE covered, just cut in the wrong place. A partition does not: the
      genuine rows can no longer claim their own spans, and whatever is left over is reported.

    So every character of the input is assigned to exactly one condition, heading or ignored entry,
    and what nothing claims goes to `unassigned_lines` (spec §LP-908, §9.2).
    """

    def __init__(self, text: str) -> None:
        self.haystack = _collapse(text)
        self._spans: list[tuple[int, int]] = []

    def claim(self, fragment: str) -> bool:
        """Claim the leftmost occurrence of this text that nothing else has taken."""
        needle = _collapse(fragment)
        if not needle:
            return False
        start = 0
        while (at := self.haystack.find(needle, start)) != -1:
            end = at + len(needle)
            if not any(at < e and s < end for s, e in self._spans):
                self._spans.append((at, end))
                return True
            # Overlapped something already claimed — try the next occurrence rather than giving up,
            # because a short condition can legitimately recur on a sheet.
            start = at + 1
        return False

    def unclaimed(self) -> list[str]:
        """Every stretch of the input nothing accounted for, in reading order."""
        out: list[str] = []
        cursor = 0
        for start, end in sorted(self._spans):
            if start > cursor and (gap := self.haystack[cursor:start].strip()):
                out.append(gap)
            cursor = max(cursor, end)
        if tail := self.haystack[cursor:].strip():
            out.append(tail)
        return out


def _rows_from(
    payload: dict[str, Any], *, coverage: _Coverage, outcome: SplitOutcome
) -> list[ParsedRow]:
    """Build rows, dropping any whose text the input does not actually contain.

    ⚠️ CLAIMING A SPAN, NOT TESTING MEMBERSHIP. A row is kept only when it can take a stretch of the
    sheet that nothing else has taken — so a row assembled from distant fragments, and a second copy
    of a row already returned, are both refused here rather than reaching a processor.
    """
    raw = payload.get("conditions")
    if not isinstance(raw, list):
        return []

    rows: list[ParsedRow] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        verbatim = entry.get("verbatim")
        if not isinstance(verbatim, str) or not verbatim.strip():
            continue
        if not coverage.claim(verbatim):
            # ⚠️ DROPPED, AND THE TEXT IS NOT LOGGED. It is a string the MODEL produced, so it is the
            # one thing here most likely to be wrong — and it could contain anything.
            outcome.rejected += 1
            continue

        code = entry.get("code")
        heading = entry.get("bucket_heading")
        text = normalise(verbatim).strip()
        if isinstance(heading, str) and heading.strip():
            # BEST EFFORT, AND A FAILURE IS NOT A REJECTION. A heading is printed ONCE and referenced
            # by every condition beneath it, so only the first claim can succeed — and a heading the
            # model echoed without the sheet showing one simply goes unclaimed, leaving whatever it
            # covers to be reported as unassigned rather than silently accounted for.
            coverage.claim(heading)
        rows.append(
            ParsedRow(
                sequence=len(rows) + 1,
                # Kept exactly as printed, leading zeros and all (ADR-407).
                lender_code=code.strip() if isinstance(code, str) and code.strip() else None,
                lender_category=None,
                bucket_heading=(
                    normalise(heading).strip()
                    if isinstance(heading, str) and heading.strip()
                    else ""
                ),
                # ⚠️ ALWAYS UNKNOWN. The heading is carried through as printed, but reading it as a
                # bucket is INTERPRETATION, and this module does not interpret. The review screen
                # asks the processor, and LP-906's mapping applies only to layouts we know.
                bucket_kind=BucketKind.UNKNOWN,
                verbatim_text=text,
                owner_hint=OwnerHint.UNKNOWN,
                owner_hint_source=OwnerHintSource.NONE,
                confidence=AI_SPLIT_CONFIDENCE,
            )
        )
    return rows


def _claim_ignored(payload: dict[str, Any], *, coverage: _Coverage) -> None:
    """Account for the page furniture the model set aside.

    Claimed AFTER the conditions, deliberately: a model that put a real condition in `ignored` as
    well as in `conditions` must not have the `ignored` copy consume the span the condition needs.
    """
    ignored = payload.get("ignored")
    if not isinstance(ignored, list):
        return
    for entry in ignored:
        if isinstance(entry, str) and entry.strip():
            coverage.claim(entry)


async def split_conditions(text: str) -> SplitOutcome:
    """Split unstructured condition text into rows. The model draws boundaries; code checks them.

    Raises `ConditionSplitUnavailable` rather than returning an empty sheet that would read as "this
    page had no conditions on it" — a distinction a processor has to be able to act on.
    """
    model = settings.anthropic_model_extraction
    try:
        result = await complete(
            model=model,
            system=load_prompt(PROMPT_PATH),
            messages=[{"role": "user", "content": text}],
            max_tokens=_MAX_TOKENS,
            # Splitting is not a creative task: the same sheet must split the same way twice, or a
            # re-parse could not be compared with the parse it replaced (spec §9.6).
            temperature=0.0,
        )
    except AIClientError as exc:
        raise ConditionSplitUnavailable(
            "The conditions could not be read automatically. Try again, or add them by hand."
        ) from exc

    snippet = extract_json_object(result.text)
    payload: Any = None
    if snippet is not None:
        try:
            payload = json.loads(snippet)
        except (json.JSONDecodeError, ValueError):
            payload = None
    if not isinstance(payload, dict):
        raise ConditionSplitUnavailable(
            "The conditions could not be read automatically. Try again, or add them by hand."
        )

    outcome = SplitOutcome(
        sheet=ParsedSheet(sheet_format=ConditionSheetFormat.PASTED_TEXT),
        model=result.model,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        cost_estimate=estimate_cost(
            model=result.model,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            cache_read_tokens=result.cache_read_tokens,
            cache_write_tokens=result.cache_write_tokens,
        ),
    )

    coverage = _Coverage(text)
    outcome.sheet.rows = _rows_from(payload, coverage=coverage, outcome=outcome)
    _claim_ignored(payload, coverage=coverage)
    outcome.sheet.unassigned_lines = coverage.unclaimed()
    if outcome.rejected:
        outcome.sheet.warnings.append(
            f"{outcome.rejected} AI row(s) were dropped: the wording was not found in the text you "
            f"pasted, and only the lender's own words are kept"
        )
    if not outcome.sheet.rows:
        outcome.sheet.warnings.append("the AI split found no conditions in this text")

    logger.info(
        "condition_split_done",
        model=result.model,
        rows=len(outcome.sheet.rows),
        rejected=outcome.rejected,
        unassigned=len(outcome.sheet.unassigned_lines),
        input_tokens=outcome.input_tokens,
        output_tokens=outcome.output_tokens,
    )
    return outcome


__all__ = [
    "PROMPT_PATH",
    "SPLIT_VERSION",
    "ConditionSplitUnavailable",
    "SplitOutcome",
    "split_conditions",
]
