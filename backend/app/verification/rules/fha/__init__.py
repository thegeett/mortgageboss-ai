"""FHA investor rules (LP-84/85) — grounded starters into the LP-74 engine.

The FHA program rule set (``program=fha``), assembled from the content modules:

* :mod:`credit_dti` — credit (8: tiered MDCS + manual-underwriting triggers +
  derogatory periods) + DTI (6: the compensating-factors mitigable model). LP-84.
* :mod:`income_assets` — income (6) + asset (5, incl. the 60% retirement haircut).
  LP-84.
* :mod:`mip` — MIP (6: UFMIP 1.75%, the annual rate table, the LTV-90% duration,
  present-checks). No Conventional analog. LP-84.

These are **GROUNDED STARTERS** — researched against the current HUD Handbook 4000.1
(retrieved 2026-06) with real citations + current values, every rule ``starter=True``
and pending the domain expert's (Priya's) validation. FHA is a SEPARATE program
alongside Conventional (LP-82/83); program-gating (the registry's ``investor(program)``)
means these only evaluate FHA files. FHA property/doc rules are LP-85.
"""

from __future__ import annotations

from app.verification.rules.fha.credit_dti import (
    FHA_CREDIT_DTI_RULES,
    FHA_CREDIT_RULES,
    FHA_DTI_RULES,
)
from app.verification.rules.fha.income_assets import (
    FHA_ASSET_RULES,
    FHA_INCOME_ASSET_RULES,
    FHA_INCOME_RULES,
)
from app.verification.rules.fha.mip import FHA_MIP_RULES
from app.verification.rules.schema import VerificationRule

# The full LP-84 FHA set (~31): credit (8) + DTI (6) + income (6) + asset (5) + MIP (6).
# FHA property/doc rules are LP-85; they extend this tuple when they land.
FHA_RULES: tuple[VerificationRule, ...] = (
    *FHA_CREDIT_DTI_RULES,
    *FHA_INCOME_ASSET_RULES,
    *FHA_MIP_RULES,
)

__all__ = [
    "FHA_ASSET_RULES",
    "FHA_CREDIT_DTI_RULES",
    "FHA_CREDIT_RULES",
    "FHA_DTI_RULES",
    "FHA_INCOME_ASSET_RULES",
    "FHA_INCOME_RULES",
    "FHA_MIP_RULES",
    "FHA_RULES",
]
