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

from app.core.config import settings

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
    # analysis (Tier-3 generic analyzer) is Sonnet on its OWN knob (LP-457 review — decoupled from reasoning).
    assert settings.anthropic_model_classification == "claude-haiku-4-5"
    assert settings.anthropic_model_extraction == "claude-haiku-4-5"
    assert settings.anthropic_model_reasoning == "claude-sonnet-4-5"
    assert settings.anthropic_model_analysis == "claude-sonnet-4-5"


def test_reasoning_and_extraction_and_analysis_are_independently_configurable() -> None:
    # The point of the split: they are DIFFERENT settings, so extraction can be cheapened, and the Tier-3
    # analyzer re-pointed, WITHOUT touching calibrated reasoning. (They may hold the same value; not the same knob.)
    assert type(settings).model_fields.keys() >= {
        "anthropic_model_extraction",
        "anthropic_model_reasoning",
        "anthropic_model_analysis",
    }
