"""AS-1 identifiers — the rule's DECISION LOGIC is now DATA (LP-324).

AS-1's decision tree lives in ``AS-1.yaml``'s ``deterministic`` block and is run by the generic
deterministic evaluator (:mod:`app.verification.rule_engine.deterministic`). NO per-rule evaluation
code remains here; only the spec-derived identifiers a few call sites + tests reference. The former
``evaluate_as1`` (the per-subject decision tree, the threshold arithmetic, the source_strength nudge)
is deleted — it is the spec now.
"""

from __future__ import annotations

from app.verification.rules.specs import load_rule_spec

RULE_ID = "AS-1"

# The tag ids AS-1 reads (names, not logic). LOAD_BEARING_TAGS is DERIVED from the spec (the single
# source of truth), so it can never drift from what the evaluator actually reads.
TAG_IS_MONEY_IN = "txn.is_money_in"
TAG_AMOUNT = "txn.amount"
TAG_HAS_SOURCE = "txn.has_identified_source"
TAG_SOURCE_STRENGTH = "txn.source_strength"

_DETERMINISTIC = load_rule_spec(RULE_ID).deterministic
assert _DETERMINISTIC is not None, "AS-1 must carry a deterministic evaluation block"
LOAD_BEARING_TAGS = tuple(_DETERMINISTIC.load_bearing_tags)

__all__ = [
    "LOAD_BEARING_TAGS",
    "RULE_ID",
    "TAG_AMOUNT",
    "TAG_HAS_SOURCE",
    "TAG_IS_MONEY_IN",
    "TAG_SOURCE_STRENGTH",
]
