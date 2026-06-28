"""Confidence semantics + the aggression cutoffs (LP-75).

Every finding carries a **confidence** in [0, 1] — how sure the system is the
finding is *real*. This is the substrate the **aggression dial** (LP-79) filters
on, and the input to the **blocking** computation (a finding only blocks
submission if its confidence is at or above the active cutoff).

Who populates it:

* **Deterministic threshold rules** (LP-74) are **certain** — 48 % genuinely
  exceeds 45 %, the math is not probabilistic — so they emit
  :data:`DETERMINISTIC_CONFIDENCE` (1.0).
* **AI cross-source** findings (LP-78) carry the AI's own confidence, which
  *varies* (0.95 on a clear income discrepancy, 0.40 on a possible obligation).

The aggression levels map to confidence cutoffs. LP-75 ships the levels + the
default so the blocking computation works standalone; **LP-79 builds the dial**
that lets a processor pick the level (a user default + a per-file override) and
records the active level on the file at submission.
"""

from __future__ import annotations

from enum import StrEnum

# Deterministic threshold findings are certain (the comparison is exact).
DETERMINISTIC_CONFIDENCE = 1.0


class AggressionLevel(StrEnum):
    """How aggressively to surface/​block on findings (the dial's setting, LP-79).

    Conservative shows only high-confidence findings; Thorough shows almost
    everything (incl. low-confidence hunches). Balanced is the default.
    """

    CONSERVATIVE = "conservative"
    BALANCED = "balanced"
    THOROUGH = "thorough"


# The confidence cutoff each level applies: a finding at/above the cutoff is
# in-scope (shown + blocking). Conservative → high bar; Thorough → everything.
CONFIDENCE_CUTOFFS: dict[AggressionLevel, float] = {
    AggressionLevel.CONSERVATIVE: 0.8,
    AggressionLevel.BALANCED: 0.5,
    AggressionLevel.THOROUGH: 0.0,
}

# The standalone default until LP-79's dial supplies the file's chosen level.
DEFAULT_AGGRESSION = AggressionLevel.BALANCED
DEFAULT_CONFIDENCE_CUTOFF = CONFIDENCE_CUTOFFS[DEFAULT_AGGRESSION]
