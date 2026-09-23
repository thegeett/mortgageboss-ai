"""The (lender, code) → meaning map: the shipped seed data and its loader (LP-910, ADR-407).

A lender condition code is that lender's own template id — `7086` is short funds to close at UWM and
means nothing at Champions, where the same demand is `268`. So every row is keyed `(lender, code)`
and the YAML files are per lender.

THE DATA IS YAML BECAUSE THE DOMAIN EXPERT MAINTAINS IT. These rows are reviewed, corrected and
extended by someone who reads condition sheets for a living, not by whoever is editing Python that
week — the same reason the rule specs and `distrusted_fields.yaml` are data rather than literals.

THE FILES LIVE INSIDE `app/` DELIBERATELY. `[tool.hatch.build.targets.wheel] packages = ["app"]` is
what ships, so anything outside `app/` is absent from the image — and `distrust.py`'s docstring
records what that costs: a loader that derived its path by walking `parents[4]` found a `backend/`
directory that exists in the repo and not in the container, came back empty, and failed every
containerised run with an error that named a field rather than the packaging. Paths here are built
with `Path(__file__).with_name(...)` for that reason.
"""

from app.conditions.lender_codes.loader import (
    LenderCodeRow,
    LenderCodeSeedError,
    load_seed,
    seeded_lender_keys,
)

__all__ = [
    "LenderCodeRow",
    "LenderCodeSeedError",
    "load_seed",
    "seeded_lender_keys",
]
