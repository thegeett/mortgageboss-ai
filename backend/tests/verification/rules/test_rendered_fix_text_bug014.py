"""bug-014 — the fix text a processor reads had its placeholders left unfilled.

MI-1 shipped this to a processor on LF-XMB2:

    "If the borrower is putting more down, confirm the final loan amount — at or below
     {mi_threshold}% the requirement falls away."

`reasoning` has been formatted over the operands since LP-511; `how_to_fix`, written beside it in the
same outcome and rendered a few pixels below it in the same card, was passed through raw. So the one
number the sentence exists to give was the literal name of an operand. MI-4 (`{required}`) and IN-15
(`{end_date}`) carry the same defect and have not reached a processor only because neither has fired.

Five guards, because each catches what the others cannot:

* the EVALUATOR renders it (an end-to-end MI-1 run, the LP-487 standing rule: a real evaluation);
* the OTHER EVALUATOR renders it too — a consistency fix carrying `{count}`/`{sources}`, which nothing
  exercised while five specs already define one;
* every SPEC is checked statically — BOTH rule shapes, deterministic outcomes against their declared
  operands and consistency outcomes against `{values}`/`{sources}`/`{count}` — so a rule that never
  fires in a test is covered too;
* the LOADER rejects an unknown placeholder, so a typo fails at load rather than mid-run in a task;
* the LOADER also rejects a `_percent` companion the evaluator will not supply — it exists only for a
  DECIMAL operand, so `{end_date_percent}` on a date operand was a KeyError waiting inside the check
  that was supposed to prevent exactly that.
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

#: What a CONSISTENCY outcome may reference — the gathered set, not operands (it declares none).
_CONSISTENCY_FIELDS = frozenset({"values", "sources", "count"})


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

        # bug-014 review — THE OTHER RULE SHAPE, which this scan skipped while the docstring claimed
        # every spec. Five specs already carry a consistency `how_to_fix` (ID-1…ID-4, IN-5, all on
        # `on_disagree`), so the evaluator's new `.format` call runs on real specs today — it is a no-op
        # only for as long as none of them contains a brace, which is not a property anyone maintains.
        consistency = document.get("consistency") or {}
        for key in ("on_agree", "on_disagree", "on_cannot_tell"):
            outcome = consistency.get(key)
            if not isinstance(outcome, dict):
                continue
            for field in ("reasoning", "how_to_fix"):
                text = outcome.get(field)
                if not isinstance(text, str):
                    continue
                referenced = {name.strip("{}") for name in _PLACEHOLDER.findall(text)}
                if unknown := sorted(referenced - _CONSISTENCY_FIELDS):
                    offenders.append((path.stem, f"{key}.{field}", ", ".join(unknown)))

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


def test_a_consistency_fix_is_formatted_over_the_gathered_set() -> None:
    """THE OTHER EVALUATOR, which the original three guards left to the loader alone.

    Five specs already define a consistency `how_to_fix` (ID-1…ID-4, IN-5), so this `.format` call runs
    on real specs — today over templates that happen to contain no brace. This drives the path with one
    that does, so the half of the fix nobody could see working is pinned to actual rendered output.
    """
    from app.verification.rule_engine.consistency import _Gathered, _outcome_result
    from app.verification.rules.specs import ConsistencyOutcome, load_rule_spec
    from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage

    def _tag(value: str) -> Tag:
        return Tag(
            value=value,
            confidence=None,
            reasoning="fixture",
            source_facts=("doc1",),
            produced_by=TagProducedBy.PARSED,
            tag_role=TagRole.STRUCTURAL_FACT,
            stage=TagStage.A,
        )

    gathered = [
        _Gathered("doc1", _tag("123 Main St"), "pay stub"),
        _Gathered("doc2", _tag("9 Oak Ave"), "W-2"),
    ]
    outcome = ConsistencyOutcome(
        verdict="fired",
        reasoning="the address differs across {count} sources ({sources})",
        how_to_fix="Compare the {count} sources ({sources}) and correct the one that is wrong.",
    )

    result = _outcome_result(
        load_rule_spec("ID-1"),
        "borrower-1",
        outcome,
        gathered,
        verdict_confidence=None,
        ratification_pending=False,
    )

    assert result.how_to_fix == (
        "Compare the 2 sources (pay stub, W-2) and correct the one that is wrong."
    )
    assert result.how_to_fix is not None and not _PLACEHOLDER.search(result.how_to_fix)


def test_the_loader_refuses_a_percent_companion_on_a_date_operand() -> None:
    """bug-014 review — THE HOLE INSIDE THE NEW CHECK ITSELF.

    `_reason_fields` supplies `{name}_percent` only where the operand's value is a Decimal, but the
    validator accepted the companion for ANY declared operand by stripping the suffix before the
    membership test. So `{end_date_percent}` on IN-15's date operand loaded clean and raised KeyError
    mid-run — the exact failure this load-time check exists to prevent, surviving inside it.
    """
    from app.verification.rules.specs import DeterministicEval

    dated = {
        "load_bearing_tags": ["income.terminated_employment_end_date"],
        "gated_tags": ["income.terminated_employment_end_date"],
        "operands": {"end_date": {"tag": "income.terminated_employment_end_date", "type": "date"}},
        "outcomes": [
            {
                "verdict": "satisfied",
                "default": True,
                "reasoning": "employment ended {end_date}",
                "how_to_fix": "Upload a pay stub dated after {end_date_percent}",
            }
        ],
    }
    with pytest.raises(ValidationError, match="how_to_fix references unknown operand"):
        DeterministicEval.model_validate(dated)

    # And the companion a DECIMAL operand really does get still loads — IN-3 depends on it (LP-511).
    decimal_operand = {
        "load_bearing_tags": ["income.ytd_annualized_shortfall_pct"],
        "gated_tags": ["income.ytd_annualized_shortfall_pct"],
        "operands": {"shortfall": {"tag": "income.ytd_annualized_shortfall_pct"}},
        "outcomes": [
            {
                "verdict": "satisfied",
                "default": True,
                "reasoning": "short by {shortfall_percent}",
                "how_to_fix": "document the {shortfall_percent} gap",
            }
        ],
    }
    assert DeterministicEval.model_validate(decimal_operand).outcomes[0].how_to_fix is not None
