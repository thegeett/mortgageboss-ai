#!/usr/bin/env python
"""The real-model trial of the condition reading (LP-939). LOCAL ONLY; the owner runs it.

Reads every lender condition sheet (PDF) in a folder OUTSIDE the repository with the configured model,
exactly as `condition_reading.read_round` does (one call per sheet, the same prompt, the same
composition), and writes a NUMBERS-ONLY summary:

- per condition: code, library type, item count, performers, confidence, fallback flag;
- per sheet ("round"): tokens in and out, estimated cost, seconds.

    cd backend
    uv run python scripts/condition-reading-trial.py ~/trial/sheets --out ~/trial/summary.json
    uv run python scripts/condition-reading-trial.py ~/trial/sheets --out ~/trial/summary.json --no-model

WHAT THE SUMMARY NEVER HOLDS: condition text, names, amounts or account digits. The sheets are named
"sheet 1", "sheet 2" in file order, because a file name can carry a borrower's name. The only strings
are lender codes, library type ids, performer and reader names, and an error's class name.

NOTHING IS WRITTEN TO A DATABASE. The conditions are built in memory from the sheet, typed from the
repo's lender code maps (`app/conditions/lender_codes/*.yaml`), and discarded.

Exit codes: 0 ok · 1 refused (a path inside the repo, no sheets, not confirmed).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[2]
_REFUSED = 1


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="condition-reading-trial.py",
        description="Run the condition reading with the configured model on sheets outside the repo.",
    )
    parser.add_argument("sheets", help="Folder of lender condition sheets (PDF), outside the repo")
    parser.add_argument("--out", required=True, help="The summary JSON to write, outside the repo")
    parser.add_argument(
        "--no-model",
        action="store_true",
        help="Make no model call: every condition falls back (checks the pipeline, costs nothing)",
    )
    parser.add_argument("--yes", action="store_true", help="Do not ask before the model calls")
    return parser.parse_args(argv)


def _outside_repo(path: Path) -> bool:
    return not path.resolve().is_relative_to(_REPO)


def _conditions_for(sheet: Any, lender_key: str) -> list[Any]:
    """The sheet's rows as in-memory `Condition`s, typed as import types them (the code map)."""
    from app.conditions.fingerprint import fingerprint
    from app.conditions.lender_codes.loader import LenderCodeSeedError, load_seed
    from app.models.condition import Condition

    try:
        codes = {row.code: row for row in load_seed(lender_key)}
    except LenderCodeSeedError:
        codes = {}
    out = []
    for row in sheet.rows:
        mapped = codes.get(row.lender_code or "")
        out.append(
            Condition(
                sequence=row.sequence,
                lender_code=row.lender_code,
                lender_category=row.lender_category,
                bucket_heading=row.bucket_heading,
                bucket_kind=row.bucket_kind,
                verbatim_text=row.verbatim_text,
                text_fingerprint=fingerprint(row.verbatim_text),
                underwriter_notes=[
                    {"date": n.date.isoformat() if n.date else None, "text": n.text}
                    for n in row.underwriter_notes
                ],
                owner_hint=row.owner_hint,
                owner_hint_source=row.owner_hint_source,
                info_only=bool(mapped.info_only) if mapped else False,
                canonical_type_id=mapped.canonical_type_id if mapped else None,
            )
        )
    return out


async def _read_sheet(path: Path, *, use_model: bool) -> dict[str, Any]:
    from app.conditions.library import load_library
    from app.conditions.sheet_read import header_with_clause, sheet_from_bytes
    from app.models.condition_round import ConditionRound
    from app.services.condition_reading import (
        RoundReading,
        _ai_input,
        _ask_model,
        compose_reading,
    )

    reader, sheet, _text = sheet_from_bytes(path.read_bytes())
    round_ = ConditionRound(header=header_with_clause(sheet))
    conditions = _conditions_for(sheet, reader)
    library = load_library()
    pending = [
        (ref, condition, library.get(condition.canonical_type_id))
        for ref, condition in enumerate(conditions, start=1)
    ]
    loan_facts = (round_.header or {}).get("loan_facts") or {}
    # The summary `_file_summary` sends, without a file: no borrower names (there is no file), the
    # lender as the reader knows it, and the two letter facts the reading uses.
    summary: dict[str, Any] = {
        "borrowers": [],
        "lender": reader,
        "must_not_close_before": loan_facts.get("Must Not Close Before"),
        "earnest_money": loan_facts.get("Earnest Money Deposit"),
        "loan_purpose": None,
    }

    outcome = RoundReading()
    answers = None
    started = time.monotonic()
    if use_model and pending:
        outcome.used_ai = True
        answers = await _ask_model(_ai_input(pending, summary), outcome)
    seconds = round(time.monotonic() - started, 2)
    outcome.fell_back = outcome.used_ai and answers is None

    rows = []
    for ref, condition, condition_type in pending:
        entry = (answers or {}).get(str(ref))
        reading, source, status, confidence = compose_reading(
            condition, condition_type=condition_type, confirmed=None, ai=entry, round_=round_
        )
        performers = sorted({p for item in reading["items"] for p in item.get("performers", [])})
        rows.append(
            {
                "code": condition.lender_code,
                "type": reading["type_id"],
                "items": len(reading["items"]),
                "performers": performers,
                "confidence": float(confidence) if confidence is not None else None,
                # Fell back: the model gave nothing for THIS condition (no call, a failed call, or
                # an answer that skipped it), so the library or the owner hint read it.
                "fallback": entry is None,
                "source": source.value,
                "status": status.value,
            }
        )
    return {
        "reader": reader,
        "conditions": len(rows),
        "input_tokens": outcome.input_tokens,
        "output_tokens": outcome.output_tokens,
        "cost_estimate": round(outcome.cost_estimate, 6),
        "seconds": seconds,
        "model": outcome.model,
        "fell_back": outcome.fell_back,
        "error": outcome.error,
        "rows": rows,
    }


async def _run(sheets: list[Path], out: Path, *, use_model: bool) -> None:
    from app.core.config import settings

    report: dict[str, Any] = {
        # The setting `read_round` passes; under Bedrock the provider maps it, and each sheet's
        # `model` is the id that actually answered.
        "model_setting": settings.anthropic_model_extraction if use_model else None,
        "sheets": [],
    }
    for number, path in enumerate(sheets, start=1):
        label = f"sheet {number}"
        try:
            result = await _read_sheet(path, use_model=use_model)
        except Exception as exc:  # one unreadable sheet must not end the trial
            result = {"error": type(exc).__name__}
        report["sheets"].append({"sheet": label, **result})
        print(f"{label}: {result.get('conditions', 0)} conditions, {result.get('seconds', 0)}s")
        out.write_text(json.dumps(report, indent=2))  # after each sheet, so a stop loses one
    totals = [s for s in report["sheets"] if "rows" in s]
    report["totals"] = {
        "sheets": len(report["sheets"]),
        "conditions": sum(s["conditions"] for s in totals),
        "input_tokens": sum(s["input_tokens"] for s in totals),
        "output_tokens": sum(s["output_tokens"] for s in totals),
        "cost_estimate": round(sum(s["cost_estimate"] for s in totals), 6),
        "seconds": round(sum(s["seconds"] for s in totals), 2),
        "fallback_conditions": sum(r["fallback"] for s in totals for r in s["rows"]),
    }
    out.write_text(json.dumps(report, indent=2))


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    folder, out = Path(args.sheets).expanduser(), Path(args.out).expanduser()
    for name, path in (("sheets folder", folder), ("--out", out)):
        if not _outside_repo(path):
            print(
                f"Refused: the {name} is inside the repository. Sheets and outputs stay outside it."
            )
            return _REFUSED
    sheets = (
        sorted(p for p in folder.iterdir() if p.suffix.lower() == ".pdf") if folder.is_dir() else []
    )
    if not sheets:
        print(f"Refused: no PDF sheets in {folder}.")
        return _REFUSED
    use_model = not args.no_model
    if use_model and not args.yes:
        answer = input(f"{len(sheets)} sheets, one model call each. Continue? [y/N] ")
        if answer.strip().lower() != "y":
            return _REFUSED
    asyncio.run(_run(sheets, out, use_model=use_model))
    print(f"Summary written to {out}")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    sys.exit(main())
