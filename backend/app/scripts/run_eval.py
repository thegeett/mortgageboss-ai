"""Run the golden eval harness and print the GO/NO-GO report (LP-317).

Keyless by default (deterministic, no API key - the CI regression instrument):

    uv run python -m app.scripts.run_eval

Live mode adds real-model calibration (needs an ANTHROPIC key; skips cleanly without one):

    uv run python -m app.scripts.run_eval --live

The report prints per-case PASS/FAIL at the tag AND finding level, a both-directions coverage check
(at least one must-fire case + the no-false-fire real file), and a calibration summary.
"""

from __future__ import annotations

import argparse
import sys

import anyio

from app.verification.eval.calibration import format_calibration, summarize
from app.verification.eval.cases import CASES
from app.verification.eval.harness import format_report, run_suite


def _api_key_present() -> bool:
    from app.core.config import settings

    key = settings.anthropic_api_key
    return bool(key) and len(str(key)) > 10


async def _main(live: bool) -> int:
    if live and not _api_key_present():
        print("live mode requested but no ANTHROPIC key is configured - running KEYLESS instead.\n")
        live = False

    results = await run_suite(CASES, live=live)
    print(format_report(results))
    print()
    print(format_calibration(summarize(results), live=live))

    must_fire = [r for r in results if r.case_id in {"1", "5", "7"}]
    covered_fire = any(r.passed for r in must_fire)
    real = next((r for r in results if r.level == "real"), None)
    covered_no_fire = real is not None and real.passed
    print("-" * 78)
    print(
        f"both-directions coverage: must-fire={'ok' if covered_fire else 'MISSING'}  "
        f"no-false-fire(real)={'ok' if covered_no_fire else 'MISSING'}"
    )

    all_pass = all(r.passed for r in results) and covered_fire and covered_no_fire
    print("=" * 78)
    print("GO" if all_pass else "NO-GO - see failures above")
    return 0 if all_pass else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Golden eval harness (LP-317)")
    parser.add_argument("--live", action="store_true", help="use the real model (calibration)")
    args = parser.parse_args()
    sys.exit(anyio.run(_main, args.live))


if __name__ == "__main__":
    main()
