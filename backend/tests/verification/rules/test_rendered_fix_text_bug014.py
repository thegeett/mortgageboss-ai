"""bug-014 — the fix text a processor reads had its placeholders left unfilled.

MI-1 shipped this to a processor on LF-XMB2:

    "If the borrower is putting more down, confirm the final loan amount — at or below
     {mi_threshold}% the requirement falls away."

`reasoning` has been formatted over the operands since LP-511; `how_to_fix`, written beside it in the
same outcome and rendered a few pixels below it in the same card, was passed through raw. So the one
number the sentence exists to give was the literal name of an operand. MI-4 (`{required}`) and IN-15
(`{end_date}`) carry the same defect and have not reached a processor only because neither has fired.

Three guards, because each catches what the others cannot:

* the EVALUATOR renders it (an end-to-end MI-1 run, the LP-487 standing rule: a real evaluation);
* every SPEC is checked statically, so a rule that never fires in a test is covered too;
* the LOADER rejects an unknown placeholder, so a typo fails at load rather than mid-run in a task.
"""

from __future__ import annotations

import re

import pytest
import yaml
from app.verification.eval.fire_path_scenarios import build_mi1_high_ltv_snapshot
from app.verification.rule_engine.registry import evaluate_rules
from app.verification.rules.specs import _SPECS_DIR
from app.verification.tag_materialization.producer import materialize_tags
from pydantic import ValidationError

pytestmark = pytest.mark.anyio

_PLACEHOLDER = re.compile(r"\{[a-z_]+\}")


async def test_mi1_renders_its_threshold_in_the_fix_a_processor_reads() -> None:
    """THE SHAPE THAT SHIPPED. Asserted on `how_to_fix` from a real evaluation, not on the spec."""
    snapshot = await materialize_tags(build_mi1_high_ltv_snapshot(), only_groups=frozenset())
    evaluations, _tags = await evaluate_rules(snapshot, rule_ids=("MI-1",))

    [mi1] = evaluations
    assert mi1.how_to_fix is not None
    assert not _PLACEHOLDER.search(mi1.how_to_fix), (
        f"an unfilled placeholder reached the processor-facing fix: {mi1.how_to_fix!r}"
    )
    assert "80%" in mi1.how_to_fix  # the threshold itself, not the operand's name
    assert not _PLACEHOLDER.search(mi1.reasoning)


def test_no_spec_outcome_can_reference_an_undeclared_placeholder() -> None:
    """STATIC, over every spec — including the rules no test exercises and the ones not yet active.

    MI-4 and IN-15 are exactly that case: both carry placeholders in `how_to_fix`, neither fires in any
    test, and the defect was invisible until MI-1 reached a real file.
    """
    offenders: list[tuple[str, str, str]] = []
    for path in sorted(_SPECS_DIR.glob("*.yaml")):
        document = yaml.safe_load(path.read_text())
        deterministic = document.get("deterministic") or {}
        operands = set(deterministic.get("operands") or {})
        for outcome in deterministic.get("outcomes") or []:
            for field in ("reasoning", "how_to_fix"):
                text = outcome.get(field)
                if not isinstance(text, str):
                    continue
                referenced = {
                    name.strip("{}").removesuffix("_percent") for name in _PLACEHOLDER.findall(text)
                }
                if unknown := sorted(referenced - operands):
                    offenders.append((path.stem, field, ", ".join(unknown)))

    assert not offenders, (
        "a spec's processor-facing text references something that is not a declared operand, so it "
        f"renders as a literal brace or raises at format time: {offenders}"
    )


def test_the_loader_refuses_a_how_to_fix_with_an_unknown_placeholder() -> None:
    """The guard that makes the two above unnecessary in future: caught at LOAD, where a stray
    placeholder is a config error, rather than mid-run inside a Celery task."""
    from app.verification.rules.specs import DeterministicEval

    body = {
        "load_bearing_tags": ["loan.ltv_percent"],
        "gated_tags": ["loan.ltv_percent"],
        "operands": {"ltv": {"tag": "loan.ltv_percent"}},
        "outcomes": [
            {
                "verdict": "satisfied",
                "default": True,
                "reasoning": "the loan-to-value is {ltv}%",
                "how_to_fix": "compare it against {mi_threshold}%",
            }
        ],
    }

    with pytest.raises(ValidationError, match="how_to_fix references unknown operand"):
        DeterministicEval.model_validate(body)

    body["outcomes"][0]["how_to_fix"] = "compare it against {ltv}%"  # type: ignore[index]
    assert DeterministicEval.model_validate(body).outcomes[0].how_to_fix is not None
