"""FHA investor rules (LP-84/85) — grounded starters into the LP-74 engine.

The FHA program rule set (``program=fha``), assembled from the content modules:

* :mod:`credit_dti` — credit (8: tiered MDCS + manual-underwriting triggers +
  derogatory periods) + DTI (6: the compensating-factors mitigable model). LP-84.
* :mod:`income_assets` — income (6) + asset (5, incl. the 60% retirement haircut).
  LP-84.
* :mod:`mip` — MIP (6: UFMIP 1.75%, the annual rate table, the LTV-90% duration,
  present-checks). No Conventional analog. LP-84.
* :mod:`property_docs` — property/MPR (13: the three S's + the deficiency checklist as
  subject-to-repair conditional findings + eligibility + condo approval) + documentation
  (5). The most distinctively-FHA content; Tier-2 honest. LP-85.

These are **GROUNDED STARTERS** — researched against the current HUD Handbook 4000.1
(retrieved 2026-06) with real citations + current values, every rule ``starter=True``
and pending the domain expert's (Priya's) validation. FHA is a SEPARATE program
alongside Conventional (LP-82/83); program-gating (the registry's ``investor(program)``)
means these only evaluate FHA files. With LP-85 the Conventional + FHA rule content
(LP-82..85) is COMPLETE — the engine holds a full grounded-starter rule set.
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
from app.verification.rules.fha.property_docs import (
    FHA_DOC_RULES,
    FHA_PROPERTY_DOC_RULES,
    FHA_PROPERTY_ELIGIBILITY_RULES,
    FHA_PROPERTY_MPR_RULES,
)
from app.verification.rules.schema import VerificationRule

# The full FHA set (~49): credit (8) + DTI (6) + income (6) + asset (5) + MIP (6) [LP-84]
# + property/MPR (13) + documentation (5) [LP-85]. The content arc (LP-82..85) is complete.
FHA_RULES: tuple[VerificationRule, ...] = (
    *FHA_CREDIT_DTI_RULES,
    *FHA_INCOME_ASSET_RULES,
    *FHA_MIP_RULES,
    *FHA_PROPERTY_DOC_RULES,
)

__all__ = [
    "FHA_ASSET_RULES",
    "FHA_CREDIT_DTI_RULES",
    "FHA_CREDIT_RULES",
    "FHA_DOC_RULES",
    "FHA_DTI_RULES",
    "FHA_INCOME_ASSET_RULES",
    "FHA_INCOME_RULES",
    "FHA_MIP_RULES",
    "FHA_PROPERTY_DOC_RULES",
    "FHA_PROPERTY_ELIGIBILITY_RULES",
    "FHA_PROPERTY_MPR_RULES",
    "FHA_RULES",
]
