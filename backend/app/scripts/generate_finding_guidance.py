"""One-time AI generation pass for finding guidance (LP-96).

Generates the **why it matters** + **suggested fix** for each canonical finding TYPE by calling
the AI with the type's grounding facts (its category + the rule's plain description) and asking it
to EXPLAIN them — grounded, not free-form. This is the AI-authoring mechanism behind the
grounded-starter :data:`app.verification.finding_guidance.GUIDANCE_BY_TYPE`.

Deliberately **not** per-request: run it once (and re-run to refresh / after Priya's review),
review the output, and fold it into the store. It is **idempotent** — by default it only generates
the types missing from the store; pass ``--force`` to regenerate all. Output is written to a JSON
file for review (never auto-applied — Priya validates first).

The committed store is the **grounded-starter** content (authored deterministically from each
type's meaning). Running this with an API key produces the richer, AI-authored version — the same
grounded-starter → validated-by-Priya posture as the rule content.

Run: ``uv run python -m app.scripts.generate_finding_guidance [--force] [--out PATH]``
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from app.core.logging import get_logger
from app.verification.finding_guidance import (
    GUIDANCE_BY_TYPE,
    generate_guidance,
)

logger = get_logger(__name__)

# The grounding facts per canonical type — the plain description the AI must explain (and nothing
# more). These mirror the deterministic cross-source rules + the AI finding types.
_TYPE_FACTS: dict[str, tuple[str, str]] = {
    "income_variance": ("income", "The stated income does not match the documented income."),
    "employer_mismatch": ("income", "A documented employer is not among the stated employers."),
    "gift_discrepancy": ("assets", "A stated gift lacks a matching gift letter / paper trail."),
    "asset_discrepancy": ("assets", "The stated assets do not match the documented assets."),
    "liability_discrepancy": (
        "credit",
        "A documented obligation was not disclosed as a liability.",
    ),
    "property_address_discrepancy": (
        "property",
        "The subject property address is inconsistent across sources.",
    ),
    "co_borrower_discrepancy": (
        "cross_source",
        "A co-borrower's details are inconsistent across sources.",
    ),
    "identity_discrepancy": (
        "cross_source",
        "A borrower's name / SSN / DOB is inconsistent across sources.",
    ),
    "missing_documentation": ("documentation", "A stated item has no supporting documentation."),
    "other": ("cross_source", "A novel cross-source discrepancy not mapped to a known rule."),
}

_DEFAULT_OUT = Path("docs/finding-guidance-generated.json")


async def _run(*, force: bool, out: Path) -> None:
    generated: dict[str, dict[str, str]] = {}
    for finding_type, (category, description) in _TYPE_FACTS.items():
        if not force and finding_type in GUIDANCE_BY_TYPE:
            # Idempotent: skip a type already in the store unless --force.
            logger.info("finding_guidance_skip_existing", finding_type=finding_type)
            continue
        guidance = await generate_guidance(
            finding_type=finding_type, category=category, description=description
        )
        if guidance is None:
            logger.warning("finding_guidance_generation_none", finding_type=finding_type)
            continue
        generated[finding_type] = {
            "why_it_matters": guidance.why_it_matters,
            "remediation": guidance.remediation,
            "starter": str(guidance.starter),
        }

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(generated, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    logger.info("finding_guidance_written", count=len(generated), path=str(out))


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate finding why/fix guidance (LP-96).")
    parser.add_argument(
        "--force", action="store_true", help="Regenerate all types, not just missing."
    )
    parser.add_argument("--out", type=Path, default=_DEFAULT_OUT, help="Output JSON path.")
    args = parser.parse_args()
    asyncio.run(_run(force=args.force, out=args.out))


if __name__ == "__main__":
    main()
