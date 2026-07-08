"""AS-5 gift-letter evaluator (LP-120) — the REFERENCE evaluator (the template for rules #2..N).

Read this as "here is how you write an evaluator." It is dispatched only when LP-119 says AS-5 is
READY-TO-RUN (a gift asset exists). Its job is the *check*: is the gift documented (a gift letter /
transfer trail)? The letter's ABSENCE is the FINDING; a present letter is SATISFIED.

Deterministic (exact) check → full confidence. It READS the frozen snapshot (``assets[].is_gift``,
``documents[].document_type``) — no recompute, no DB, no AI. It reproduces the live
``xsrc.asset.gift_without_letter`` rule's verdict (same gift predicate + same gift-letter document
types), which is the correctness check for the whole new engine.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.verification.evaluators.contract import (
    EvaluationResult,
    Provenance,
    deterministic_couldnt_check,
    deterministic_finding,
    deterministic_satisfied,
)
from app.verification.fact_namespace.projection import GIFT_LETTER_DOCUMENT_TYPES
from app.verification.fact_namespace.snapshot import FactNamespace


class GiftLetterEvaluator:
    """Gift funds present but no gift letter/transfer documentation → finding (AS-5)."""

    rule_id = "xsrc.asset.gift_without_letter"

    def evaluate(self, snapshot: FactNamespace, params: dict[str, Any]) -> EvaluationResult:
        # Reads only the frozen snapshot. ``is_gift`` was derived at fact-build time (same predicate
        # as the live rule: "gift" in the asset type); we never re-derive it here.
        gift_assets = [asset for asset in snapshot.assets if asset.is_gift]
        gift_total = sum(
            (a.value.value for a in gift_assets if a.value.value is not None), Decimal(0)
        )
        # A gift letter is "present" if a verified gift-letter/gift-funds document exists (the live
        # rule's verified-document semantics: a current extraction with typed fields).
        has_letter = any(
            doc.document_type in GIFT_LETTER_DOCUMENT_TYPES and doc.present and doc.fields
            for doc in snapshot.documents
        )

        provenance = [
            Provenance(
                path="assets[].is_gift",
                observed=f"{len(gift_assets)} gift asset(s), total {gift_total}",
            ),
            Provenance(
                path="documents[].document_type",
                observed="gift-letter document present"
                if has_letter
                else "no gift-letter document",
            ),
        ]

        # A gift is flagged (is_gift) but its amount is undeterminable (None/0). The live rule makes
        # NO verdict here (``_gift_facts`` → (None, None) → ``_check_gift_without_letter`` → []). So
        # do NOT emit a false "$0 gift" FINDING (FIX 2) AND do NOT assert SATISFIED — the live rule
        # never checked it (post-review FIX 8). Surface it as COULDN'T-CHECK, honestly.
        if gift_total <= 0:
            return deterministic_couldnt_check(
                self.rule_id,
                "A gift is stated but its amount was not extracted — cannot verify the documentation.",
                provenance=provenance,
            )
        if has_letter:
            return deterministic_satisfied(
                self.rule_id,
                "Gift funds are documented — a gift letter / transfer document is present.",
                provenance=provenance,
            )
        return deterministic_finding(
            self.rule_id,
            f"A gift of {gift_total} is stated but no gift letter / transfer documentation is present.",
            provenance=provenance,
        )
