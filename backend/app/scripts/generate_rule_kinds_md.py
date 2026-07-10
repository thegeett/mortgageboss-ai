"""Generate docs/stage2-rule-classification.md from rule_kinds.csv (LP-301).

The CSV (``app/verification/rules/rule_kinds.csv``) is the source of truth; this
renders the plain-text companion table so future tickets can read rule_id → kind →
path without parsing the xlsx. Regenerate after editing the CSV:

    uv run python -m app.scripts.generate_rule_kinds_md
"""

from collections import Counter
from pathlib import Path

from app.verification.rules.kinds import RuleKindName, load_rule_kinds

_OUT = Path(__file__).resolve().parents[3] / "docs" / "stage2-rule-classification.md"


def render() -> str:
    rules = load_rule_kinds()
    kinds = Counter(rk.kind.value for rk in rules.values())
    numeric = sum(rk.numeric_check for rk in rules.values())
    validated = sum(rk.priya_validated for rk in rules.values())
    needs_signoff = sum(rk.threshold_needs_signoff for rk in rules.values())

    lines: list[str] = []
    lines.append("# Stage 2 — Rule-kind classification (companion to `rule_kinds.csv`)")
    lines.append("")
    lines.append(
        "Generated from `backend/app/verification/rules/rule_kinds.csv` (the source of "
        "truth) via `app.scripts.generate_rule_kinds_md` — do not edit by hand. See "
        "ADR-247 / LP-301."
    )
    lines.append("")
    lines.append(
        f"**{len(rules)} rules** — calculative {kinds['calculative']}, structural "
        f"{kinds['structural']}, judgmental {kinds['judgmental']}, out-of-scope "
        f"{kinds['out_of_scope']}. Numeric-check (deterministic bookend): {numeric}. "
        f"Priya-validated: {validated}/{len(rules)}. Thresholds needing sign-off: "
        f"{needs_signoff}."
    )
    lines.append("")
    lines.append(
        "`exact_match` applies to structural rules only (true = deterministic-only, no "
        "AI; false = AI fuzzy entity match). `numeric_check` = the calculative bookend. "
        "`signoff` = a regulatory threshold Priya must sign off before ship. All rules "
        "are `priya_validated=false` until confirmed."
    )
    lines.append("")

    header = "| rule_id | name | category | kind | evaluation_path | numeric | exact_match | validated | signoff |"
    sep = "|---|---|---|---|---|---|---|---|---|"
    for kind in RuleKindName:
        group = [rk for rk in rules.values() if rk.kind is kind]
        lines.append(f"## {kind.value} ({len(group)})")
        lines.append("")
        lines.append(header)
        lines.append(sep)
        for rk in group:
            em = "—" if rk.exact_match is None else str(rk.exact_match).lower()
            lines.append(
                f"| {rk.rule_id} | {rk.name} | {rk.category} | {rk.kind.value} | "
                f"{rk.evaluation_path.value} | {str(rk.numeric_check).lower()} | {em} | "
                f"{str(rk.priya_validated).lower()} | {str(rk.threshold_needs_signoff).lower()} |"
            )
        lines.append("")
    return "\n".join(lines) + "\n"


def main() -> None:
    _OUT.write_text(render())
    print(f"wrote {_OUT.relative_to(Path(__file__).resolve().parents[3])}")


if __name__ == "__main__":
    main()
