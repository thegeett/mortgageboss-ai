"""LP-530 — what a PROCESSOR reads is held to a different standard than what an ENGINEER reads.

A spec file is both at once. Comments, tag descriptions and AI prompts are written for us and for the
model; ``couldnt_check_fix``, ``guidance``, ``materiality`` and ``verdict_labels`` are rendered verbatim
into a loan processor's queue. The repo uses a warning emoji freely in the first kind — that is a
convention, and it is fine.

It reached the second kind. CR-6 and IN-3 shipped a fix that opened a sentence with a warning sign in
front of a processor:

    "... so both the report and a closing date are needed. ⚠️ If the borrower has no derogatory events
     the report shows that too — this check will not assume a clean history ..."

Two things are wrong with it and only one is the emoji. The sentence is also written in the engine's
own voice — "this check will not assume", "this check abstains rather than choosing one" — which tells
the reader about the software's decision procedure when what they need is what to do about a document.
The same register is what makes the composer reach for "the system" (LP-529), so it is worth removing
at the source rather than only at the output.
"""

from __future__ import annotations

import ast
import pathlib
import re

import pytest
import yaml
from app.verification.rules.specs import _SPECS_DIR

# Fields rendered verbatim into the UI. Everything not listed is engineer- or model-facing.
_USER_FACING = ("couldnt_check_fix", "guidance", "materiality", "verdict_labels")


def _user_facing_strings() -> list[tuple[str, str, str]]:
    found: list[tuple[str, str, str]] = []
    for path in sorted(_SPECS_DIR.glob("*.yaml")):
        document = yaml.safe_load(path.read_text())

        def walk(node: object, trail: tuple[str, ...], rule: str = path.stem) -> None:
            if isinstance(node, dict):
                for key, value in node.items():
                    walk(value, (*trail, str(key)))
            elif isinstance(node, list):
                for value in node:
                    walk(value, trail)
            elif isinstance(node, str) and any(field in trail for field in _USER_FACING):
                found.append((rule, ".".join(trail), node))

        walk(document, ())
    return found


def test_no_user_facing_string_carries_a_warning_emoji() -> None:
    """⚠️ THE EXACT SHAPE THAT SHIPPED — and note that this docstring may carry one, because a
    docstring is read by us. The assertion is about the other kind of text."""
    offenders = [(rule, field) for rule, field, text in _user_facing_strings() if "⚠️" in text]

    assert not offenders, (
        "a warning emoji reached text a loan processor reads — write the caveat as a plain "
        f"sentence: {offenders}"
    )


# ⚠️ PATTERNS, NOT PHRASES — LP-534. The first version listed "this check" and IH-9 shipped "the check
# cannot tell which coverage period applies": the same sentence, a different article, and the guard read
# clean. Anything matching here names the software where the loan file belongs.
_MACHINERY = (
    r"\b(this|the) check\b",
    r"\bthe (rule )?engine\b",
    r"\bthe system\b",
    r"\bthe extractor\b",
    r"\babstain",
    r"\bcouldnt_check\b",
    r"\bnot_applicable\b",
)


@pytest.mark.parametrize("phrase", _MACHINERY)
def test_no_user_facing_string_describes_the_machinery(phrase: str) -> None:
    """A processor is told what to do about a DOCUMENT. "this check abstains rather than choosing one"
    describes our control flow, which they can neither act on nor verify.

    This is the same failure the composer's ``machinery_talk`` guard catches on the way out (LP-528/529)
    — caught here at the source, where a human wrote it, rather than only in a generation."""
    offenders = [
        (rule, field)
        for rule, field, text in _user_facing_strings()
        if re.search(phrase, text.lower())
    ]

    assert not offenders, f"{phrase!r} describes the software, not the loan file: {offenders}"


# ------------------------------------------------------------------------------------------------ #
# LP-533 — THE HALF LP-530 MISSED, and the reason it missed it
# ------------------------------------------------------------------------------------------------ #
# LP-530 scanned YAML spec fields and I reported the register problem as fixed. It was not: a
# finding's `message` — the HEADLINE a processor reads, and the `problem` the composer is asked to
# rewrite — is built in PYTHON, not authored in YAML. Nine such strings said "this check".
#
# Two of them were on screen at the time, in the exact findings I was explaining:
#
#   CR-6  "... could not be determined — THIS CHECK NEEDS IT to tell whether the rule applies here"
#   IN-8  "... which is what THIS CHECK needs"
#
# A guard scoped to one authoring surface reads as a guard on the topic. This scans the other one.
_REASON_MODULES = (
    "app/verification/rule_engine/applicability.py",
    "app/verification/rule_engine/gate.py",
    "app/verification/rule_engine/deterministic.py",
    "app/verification/rule_engine/judgment.py",
    "app/verification/rule_engine/reasons.py",
    "app/verification/tag_materialization/derived.py",
)

_DOCSTRING_HOLDERS = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)


def _literals(module: pathlib.Path) -> list[tuple[int, str]]:
    """Every string LITERAL in the module, minus docstrings.

    Docstrings are excluded deliberately: they are written for us and use the machinery vocabulary
    freely and correctly. What ships to a processor is the literals."""
    tree = ast.parse(module.read_text())
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, _DOCSTRING_HOLDERS):
            body = getattr(node, "body", [])
            first = body[0] if body else None
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                docstrings.add(id(first.value))
    return [
        (node.lineno, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]


@pytest.mark.parametrize("module", _REASON_MODULES)
def test_no_generated_reason_describes_the_machinery(module: str) -> None:
    """The same standard as the YAML guard, on the surface that actually produced the finding text."""
    root = pathlib.Path(__file__).resolve().parents[3]
    offenders = [
        (module.rsplit("/", 1)[-1], line, text.strip()[:60])
        for line, text in _literals(root / module)
        if any(re.search(phrase, text.lower()) for phrase in _MACHINERY[:4])
    ]

    assert not offenders, (
        "a generated finding message describes the software rather than the loan file — it is what "
        f"a processor reads AND what the composer is asked to rewrite: {offenders}"
    )


# ------------------------------------------------------------------------------------------------ #
# LP-538 — a rule identifies itself by NAME, not only by id
# ------------------------------------------------------------------------------------------------ #
def test_every_rule_that_can_produce_a_finding_has_a_name_to_show() -> None:
    """A processor cannot know that "DT-7" means ATR documentation completeness, or that "CR-6" means
    derogatory seasoning. The findings payload now carries the spec's own name beside the id.

    This holds for every FUTURE rule by construction rather than by vigilance: `RuleSpec.name` is
    `str = PydField(min_length=1)`, so a spec with no name (or an empty one) fails to load and the rule
    cannot run at all. The test pins the two things that make that guarantee reach the UI — that every
    active rule HAS a spec, and that no spec's name is blank — because a rule active without a spec file
    would resolve `rule_name` to None and silently fall back to the bare id."""
    from app.verification.rule_engine.registry import ACTIVE_RULE_IDS
    from app.verification.rules.specs import load_rule_spec

    spec_ids = {path.stem for path in _SPECS_DIR.glob("*.yaml")}

    assert not set(ACTIVE_RULE_IDS) - spec_ids, (
        "an active rule has no spec, so it has no name to show"
    )
    assert all(load_rule_spec(rule_id).name.strip() for rule_id in sorted(spec_ids))


def test_the_findings_payload_actually_carries_the_name() -> None:
    """The guarantee above is worthless if the schema drops it — this is the wire."""
    from app.schemas.verification import RuleFindingPublic

    assert "rule_name" in RuleFindingPublic.model_fields


# ------------------------------------------------------------------------------------------------ #
# LP-553 — a PASS says what holds, never what was absent
# ------------------------------------------------------------------------------------------------ #
_ABSENCE_PHRASING = (
    r"\bstates no\b",
    r"\bshows no\b",
    r"\bfound no\b",
    r"\bwith no\b",
    r"\bhas not\b",
    r"\bwas not\b",
    r"\bdid not\b",
    r"\bnothing\b",
)


def test_no_satisfied_outcome_is_phrased_as_an_absence() -> None:
    """A satisfied finding is the only reassurance a processor gets, and it has to read like one.

    "the homeowners insurance policy has not expired" and "the credit report states no consumer
    dispute" are accurate and land like a near-miss. Said positively — "the policy is in force", "this
    tradeline is reported clean" — the same fact tells a processor the file is SOLID on that point.

    Pinned on the TEMPLATE rather than left to the composer. The composer rewrites every finding and is
    told to do this, but a prompt is a hope: a rejected or failed composition falls back to the template
    on any file, so the floor has to be right on its own.
    """
    offenders = []
    for path in sorted(_SPECS_DIR.glob("*.yaml")):
        document = yaml.safe_load(path.read_text())
        for outcome in (document.get("deterministic") or {}).get("outcomes") or []:
            if outcome.get("verdict") != "satisfied":
                continue
            text = " ".join(str(outcome.get("reasoning", "")).split()).lower()
            for pattern in _ABSENCE_PHRASING:
                if re.search(pattern, text):
                    offenders.append((path.stem, pattern, text[:70]))

    assert not offenders, f"a passing check is phrased as an absence: {offenders}"
