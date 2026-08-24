"""LP-457 — model selection is centralised in ONE home (config.py), four tiers, one per purpose.

A single constant would drag one purpose's callers onto whatever another uses — exactly the problem this
split fixes. So there are FOUR settings (classification / extraction / reasoning / analysis — the Tier-3
generic analyzer got its own knob in the LP-457 review, decoupled from the calibrated reasoning tier), and NO
caller may hard-code a model string: a future hard-coded model would silently escape the switch. This guard
fails CI on any literal ``claude-*`` model string in ``app/`` outside the config home and the two
data-not-selection exemptions.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from app.core.config import resolve_model, settings

_APP = Path(__file__).resolve().parents[2] / "app"
# A QUOTED model identifier used as a value (not a word in a comment/docstring sentence).
_MODEL_LITERAL = re.compile(r"""["']claude-(?:haiku|sonnet|opus|fable)-""")

# The only files allowed to contain a literal model string, each for a reason that is NOT model SELECTION:
_ALLOWED = {
    "core/config.py",  # THE home — the three env-overridable model settings live here
    "ai/cost.py",  # a PRICING table keyed by the model string (data), not a selection
    "scripts/seed_dev_data.py",  # a seeded-data placeholder for the stored `model_used` field, not a caller
}


def test_no_hardcoded_model_string_outside_the_config_home() -> None:
    offenders: list[str] = []
    for path in _APP.rglob("*.py"):
        rel = path.relative_to(_APP).as_posix()
        if rel in _ALLOWED:
            continue
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if _MODEL_LITERAL.search(line):
                offenders.append(f"{rel}:{i}: {line.strip()}")
    assert not offenders, (
        "hard-coded model string outside the config home (LP-457 — every AI caller must read "
        "settings.anthropic_model_{classification,extraction,reasoning}):\n  "
        + "\n  ".join(offenders)
    )


def test_four_model_tiers_exist_and_default_correctly() -> None:
    # The four purposes. Extraction is Haiku (LP-457 switch); reasoning STAYS Sonnet (the live rules were
    # calibrated on Sonnet reasoning — moving it invalidates every activation bar); classification is Haiku;
    # analysis (Tier-3 generic analyzer) is Haiku as of LP-628, still on its OWN knob (LP-457 review —
    # decoupled from reasoning, so cheapening Tier 3 cannot drag calibrated reasoning with it).
    assert settings.anthropic_model_classification == "claude-haiku-4-5"
    assert settings.anthropic_model_extraction == "claude-haiku-4-5"
    assert settings.anthropic_model_reasoning == "claude-sonnet-4-5"
    assert settings.anthropic_model_analysis == "claude-haiku-4-5"


def test_the_analysis_tier_resolves_under_bedrock(monkeypatch: pytest.MonkeyPatch) -> None:
    """LP-628 — the trap `docs/secrets-audit.md` warns about, now that Tier 3 has been re-pointed.

    `resolve_model` keys on the model STRING and only knows three BEDROCK_MODEL_* mappings;
    `analysis` has none of its own. It resolved before only because its value happened to equal
    `reasoning`'s. Moving it to Haiku keeps it resolvable ONLY because Haiku is also the
    classification/extraction value — an analysis-only model would raise ModelResolutionError at
    invoke time, on the fallback path that runs when extraction has already failed. That is the
    worst possible place for a config error, so it gets a test rather than a comment.
    """
    monkeypatch.setattr(settings, "ai_provider", "bedrock")
    # Classification and extraction BOTH hold the Haiku value and classification is matched first,
    # so both are pinned to the same id — the tier it resolves through is an implementation detail,
    # the invariant is that it resolves and lands on Haiku rather than Sonnet.
    monkeypatch.setattr(settings, "bedrock_model_classification", "us.anthropic.claude-haiku-4-5-x")
    monkeypatch.setattr(settings, "bedrock_model_extraction", "us.anthropic.claude-haiku-4-5-x")
    monkeypatch.setattr(settings, "bedrock_model_reasoning", "us.anthropic.claude-sonnet-4-5-x")

    assert resolve_model(settings.anthropic_model_analysis) == "us.anthropic.claude-haiku-4-5-x"


def test_reasoning_and_extraction_and_analysis_are_independently_configurable() -> None:
    # The point of the split: they are DIFFERENT settings, so extraction can be cheapened, and the Tier-3
    # analyzer re-pointed, WITHOUT touching calibrated reasoning. (They may hold the same value; not the same knob.)
    assert type(settings).model_fields.keys() >= {
        "anthropic_model_extraction",
        "anthropic_model_reasoning",
        "anthropic_model_analysis",
    }
