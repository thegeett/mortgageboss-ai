"""The activation census — every count a rule-activation ticket has to re-pin, in ONE pass.

⚠️ WHY THIS EXISTS. Activating (or merely BUILDING) a rule moves roughly a dozen pinned numbers spread
across the suite, and they are pinned in TWO DIFFERENT ORDERS — some sites hold a ``set``, others a
``sorted`` tuple. Discovering them one failure at a time costs a full suite run (~2 minutes) per
discovery; four tickets in a row paid that toll before this script was written.

Run it BEFORE touching the pinned sites::

    uv run python -m app.scripts.activation_census

It prints the authoritative values, computed from the registry / bars / vocabulary themselves, so a
ticket can patch every site once and run the suite once. It asserts nothing and is not a test — the
tests remain the enforcement; this is the worksheet.
"""

from __future__ import annotations

from collections import Counter

from app.verification.rule_engine.activation_bars import is_eligible, load_activation_bars
from app.verification.rule_engine.registry import ACTIVE_RULE_IDS
from app.verification.rules.kinds import RuleKindName, load_rule_kinds, rules_by_kind
from app.verification.rules.projection import load_desired_tags


def _fmt(values: list[str], per_line: int = 6) -> str:
    return "\n".join(
        "    " + ", ".join(repr(v) for v in values[i : i + per_line])
        for i in range(0, len(values), per_line)
    )


def main() -> None:
    bars = load_activation_bars()
    active_sorted = sorted(ACTIVE_RULE_IDS)
    eligible = sorted(r for r, bar in bars.items() if is_eligible(bar))

    print("=" * 78)
    print("ACTIVATION CENSUS")
    print("=" * 78)

    print(f"\n[1] ACTIVE_RULE_IDS — count = {len(ACTIVE_RULE_IDS)}")
    print("    ⚠️ Pinned in BOTH orders. Registry order is the module's own tuple; SORTED is:")
    print(_fmt(active_sorted))

    print(f"\n[2] ELIGIBLE per is_eligible() — count = {len(eligible)}")
    # ⚠️ A DIFFERENCE HERE IS EXPECTED, NOT A BUG: `_BASE_ACTIVE` grandfathers the pre-LP-389 rules,
    # which are active without passing the gate. Watch it for CHANGE, not for emptiness.
    grandfathered = sorted(set(active_sorted) - set(eligible))
    print(f"    active but not gate-eligible (_BASE_ACTIVE): {len(grandfathered)} {grandfathered}")
    print(f"    gate-eligible but NOT active: {sorted(set(eligible) - set(active_sorted))}")

    print("\n[3] Activation-bar status counts (test_activation_bars_lp380)")
    for status, n in sorted(Counter(bar.status for bar in bars.values()).items()):
        print(f"    {status:28} {n}")
    print(f"    {'TOTAL BARS':28} {len(bars)}")

    print("\n[4] rule_kinds.csv (test_rule_kinds, and docs/stage2-rule-classification.md)")
    kinds = load_rule_kinds()
    print(f"    rows = {len(kinds)}   ⚠️ must stay 135")
    for kind in RuleKindName:
        print(f"    {kind.value:28} {len(rules_by_kind(kind))}")
    numeric = sum(1 for rk in kinds.values() if rk.numeric_check)
    signoff = sum(1 for rk in kinds.values() if rk.threshold_needs_signoff)
    validated = sum(1 for rk in kinds.values() if rk.priya_validated)
    print(f"    {'numeric_check':28} {numeric}")
    print(f"    {'threshold_needs_signoff':28} {signoff}")
    print(f"    {'priya_validated':28} {validated}/{len(kinds)}")
    print("    ⚠️ After ANY csv edit: uv run python -m app.scripts.generate_rule_kinds_md")

    print("\n[5] Vocabulary (test_fact_tags_files::test_desired_state_shape)")
    tags = load_desired_tags()
    print(f"    total declared tags = {len(tags)}")
    for entity, n in sorted(Counter(t["entity"] for t in tags.values()).items()):
        print(f"    {entity:28} {n}")

    print("\n[6] The sites that pin these — patch them all, THEN run the suite once")
    for path in (
        "tests/expected_active.py",
        "tests/verification/rule_engine/test_activation_bars_lp380.py",
        "tests/verification/rule_engine/test_activation_bars_lp397.py",
        "tests/verification/rule_engine/test_activation_gate_lp389.py   (a SET and a SORTED tuple)",
        "tests/verification/rule_engine/test_generic_evaluators.py",
        "tests/verification/rules/test_rule_kinds.py",
        "tests/verification/rules/test_fact_tags_files.py",
        "tests/verification/rules/test_projection_db.py",
        "tests/verification/rules/test_normalized_convention.py",
        "tests/**/test_no_rule_activation_changed*.py   (four files)",
        "tests/ai/test_extraction_bench.py",
        "docs/stage2-rule-classification.md   (generated — regenerate, never hand-edit)",
    ):
        print(f"    - {path}")
    print()


if __name__ == "__main__":  # pragma: no cover — a developer worksheet, not a runtime path
    main()
