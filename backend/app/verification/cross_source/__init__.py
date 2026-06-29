"""Deterministic cross-source rules (LP-86) — the graduation.

Reliable, enumerable cross-document checks PROMOTED from the AI cross-source discovery
layer (LP-78, non-deterministic) into DETERMINISTIC rules — run every time, identically,
with templated wording, no recall variance. A DISTINCT rule category: each rule reads
MULTIPLE fields ACROSS sources (not one threshold against one field like LP-82..85), owns
a canonical finding type (so the AI defers — no double-reporting), and emits with
``origin=deterministic_rule``.

* :mod:`facts` — :class:`CrossSourceFacts`, the multi-source snapshot.
* :mod:`rules` — the ~18 :class:`CrossSourceRule` records + the pure checks + the owned
  canonical types + the overlay patcher.
* :mod:`engine` — :func:`evaluate_cross_source`, the pure read-across-sources → diff → emit loop.

This is consistency-option D — the deepest fix, completing the arc with LP-78.1 (caching)
+ LP-81 (stable identity / merge / templated wording): the reliable checks are now FULLY
deterministic. The AI cross-source layer narrows to the novel-discovery frontier.
"""

from __future__ import annotations

from app.verification.cross_source.engine import CrossSourceFinding, evaluate_cross_source
from app.verification.cross_source.facts import (
    CrossSourceFacts,
    ObligationRef,
    SourcedValue,
)
from app.verification.cross_source.rules import (
    CROSS_SOURCE_RULES,
    OWNED_CANONICAL_TYPES,
    CrossSourceMatch,
    CrossSourceRule,
    apply_cross_source_overlay,
)

__all__ = [
    "CROSS_SOURCE_RULES",
    "OWNED_CANONICAL_TYPES",
    "CrossSourceFacts",
    "CrossSourceFinding",
    "CrossSourceMatch",
    "CrossSourceRule",
    "ObligationRef",
    "SourcedValue",
    "apply_cross_source_overlay",
    "evaluate_cross_source",
]
