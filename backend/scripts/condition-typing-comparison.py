"""LP-962 — would the AI type each condition the way the hand-written lender code maps do?

The question the owner asked (2026-10-04): why look a condition's type up in a per-lender YAML
(`app/conditions/lender_codes/uwm.yaml`, `champions.yaml`) when the reading's AI already reads every
condition? This measures it before anything changes.

For every condition on the committed sample sheets, the reading's real prompt (`read_v3`) is called
with the condition's text and NO type, the way an unmapped condition is read today, so the model
proposes `library_type` from the library list. The proposal is compared with the code map's
`canonical_type_id` for that (lender, code).

THE CORPUS IS SYNTHETIC, AND THE RESULT SAYS SO. The sheets are the test fixtures, cut from the build
spec (`tests/conditions/fixture_helpers.py`), written by us in the lenders' layouts. Agreement here is
evidence the AI can do the job on text like ours; it is not evidence on real lenders' wording. Real
sheets are the next measurement.

Prints codes, type ids and counts only: no condition text, no names.

    cd backend && uv run python scripts/condition-typing-comparison.py [--yes]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.conditions.lender_codes.loader import load_seed
from app.conditions.readers import read_champions, read_uwm
from app.conditions.readers.lines import lines_from_pdf
from app.services import condition_reading
from tests.conditions.champions_fixture import build_champions_pdf
from tests.conditions.fixture_helpers import sheet_lines

BATCH = 6

UWM_SHEETS = (
    "uwm_round1_2026-08-28.txt",
    "uwm_round2_2026-09-10.txt",
    "uwm_round3_2026-09-18.txt",
    "uwm_master_pagebreak.txt",
)


def _corpus() -> list[tuple[str, str, str]]:
    """`(lender, code, text)` for every distinct (lender, code) on the sample sheets."""
    seen: dict[tuple[str, str], str] = {}
    for name in UWM_SHEETS:
        for row in read_uwm(sheet_lines(name)).rows:
            if row.lender_code:
                seen.setdefault(("uwm", row.lender_code), row.verbatim_text)
    for row in read_champions(lines_from_pdf(build_champions_pdf())).rows:
        if row.lender_code:
            seen.setdefault(("champions", row.lender_code), row.verbatim_text)
    return [(lender, code, text) for (lender, code), text in sorted(seen.items())]


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--yes", action="store_true", help="call the model without asking")
    args = parser.parse_args()

    maps = {lender: {row.code: row for row in load_seed(lender)} for lender in ("uwm", "champions")}
    corpus = _corpus()
    print(
        f"corpus: {len(corpus)} distinct (lender, code) conditions from {len(UWM_SHEETS)} UWM "
        "sample sheets and 1 Champions sample sheet (SYNTHETIC: the test fixtures)"
    )
    if not args.yes and input("Call the model once per lender? [y/N] ").strip().lower() != "y":
        return 1

    results: list[dict[str, Any]] = []
    # BATCHES OF 6. The first run sent each lender's sheet in one call, as `read_round` does, and the
    # 21-condition UWM answer hit the reading's 8192-token output cap and came back cut off.
    batches = []
    for lender in ("uwm", "champions"):
        rows = [(code, text) for each_lender, code, text in corpus if each_lender == lender]
        batches += [(lender, rows[i : i + BATCH]) for i in range(0, len(rows), BATCH)]
    for lender, rows in batches:
        pending = [
            (ref, SimpleNamespace(lender_code=code, verbatim_text=text, underwriter_notes=[]), None)
            for ref, (code, text) in enumerate(rows, start=1)
        ]
        summary = {
            "borrowers": [],
            "lender": lender,
            "must_not_close_before": None,
            "earnest_money": None,
            "loan_purpose": None,
        }
        outcome = condition_reading.RoundReading()
        answers = await condition_reading._ask_model(
            condition_reading._ai_input(pending, summary),  # type: ignore[arg-type]
            outcome,
        )
        for _attempt in range(2):  # one retry: the service answered 503s on the first run
            if answers is not None:
                break
            outcome = condition_reading.RoundReading()
            answers = await condition_reading._ask_model(
                condition_reading._ai_input(pending, summary),  # type: ignore[arg-type]
                outcome,
            )
        print(
            f"{lender}: {len(rows)} conditions, model {outcome.model}, "
            f"{outcome.input_tokens}+{outcome.output_tokens} tokens, ${outcome.cost_estimate:.3f}"
            + (f", FAILED ({outcome.error})" if answers is None else "")
        )
        for ref, (code, _text) in enumerate(rows, start=1):
            entry = (answers or {}).get(str(ref)) or {}
            mapped = maps[lender].get(code)
            results.append(
                {
                    "lender": lender,
                    "code": code,
                    "map": mapped.canonical_type_id if mapped else None,
                    "ai": entry.get("library_type"),
                    "confidence": entry.get("confidence"),
                    "failed": answers is None,
                }
            )

    def verdict(r: dict[str, Any]) -> str:
        if r["failed"]:
            return "CALL FAILED (no answer)"
        if r["map"] is None and r["ai"] is None:
            return "both none"
        if r["map"] is None:
            return "AI typed, map has no row/type"
        if r["ai"] is None:
            return "AI declined (null)"
        return "agree" if r["ai"] == r["map"] else "DISAGREE"

    print()
    print(f"{'lender':10} {'code':6} {'code map':9} {'AI':9} {'conf':5}  verdict")
    for r in results:
        conf = f"{r['confidence']:.2f}" if isinstance(r["confidence"], (int, float)) else "-"
        print(f"{r['lender']:10} {r['code']:6} {r['map']!s:9} {r['ai']!s:9} {conf:5}  {verdict(r)}")
    print()
    counts = Counter(verdict(r) for r in results)
    for key, n in counts.most_common():
        print(f"  {key}: {n} of {len(results)}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
