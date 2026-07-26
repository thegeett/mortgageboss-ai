"""LP-383 — LE/CD extraction is PREMATURE: no rule consumes an LE/CD field yet (a reported, pinned finding).

LP-383 was queued as "extract Loan Estimate / Closing Disclosure." LP-381/382's discipline: an extraction
ticket first MAPS the consumer, then extracts ONLY if a real rule resolves once the field exists. The gate of
record says NO rule in THIS engine consumes LE/CD today, so an LE/CD extractor would emit fields nothing reads
— dead code + a future field-name trap (the LP-333/369 silent-death class). So nothing was built; these pin the
map so the moment a real consumer appears (the cash-to-close calculator, §3B / LP-323-AS-B), a test here fails
and forces the extractor↔consumer chain to be completed together.

THE MAP (see docs/tickets/LP-383.md):
* The classifier CATALOGS loan_estimate + closing_disclosure (a routing target exists) — but NO extractor is
  registered for either, so an LE/CD document classifies and then extracts NOTHING today.
* The only conceptual consumer is AS-3 (cash-to-close), via calc.cash_to_close's closing_costs. But AS-3 is
  INERT, its calc.cash_to_close recipe is a STUB that always abstains (there is NO cash-to-close calculator,
  §3B), and there is NO declared *.closing_costs / le.* / cd.* tag — so there is no NAME to emit an extractor
  against, and extraction ALONE would not resolve AS-3 (the §3B calculator must be built first).
* The natural LE/CD consumers — the TRID compliance rules DC-1..DC-7 (LE timing, ITP, CD 3-day timing, fee
  tolerance, APR change, appraisal delivery, changed-circumstance) — are ALL out_of_scope (LOS-owned).
* LF-6T3N carries no LE/CD document — so even a built extractor could not be verified against it.

VERDICT: premature. LE/CD extraction belongs WITH the cash-to-close calculator wave (§3B / LP-323-AS-B), built
against a fixture that carries an LE/CD, so the extracted field has a reader and can be verified.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.ai.classification_prompt import DOCUMENT_TYPE_INDICATORS
from app.ai.extraction import EXTRACTORS
from app.services.calculators import CALCULATORS
from app.verification.rule_engine.registry import ACTIVE_RULE_IDS
from app.verification.rules.kinds import RuleKindName, kind_for
from app.verification.snapshot.model import (
    DocumentsSection,
    MismoSection,
    Snapshot,
    TagsSection,
)
from app.verification.tag_materialization.declarations import load_declarations
from app.verification.tag_materialization.derived import _cash_to_close_shortfall

_LE_CD = ("loan_estimate", "closing_disclosure")


def _empty_snapshot() -> Snapshot:
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 7, 21, tzinfo=UTC),
        documents=DocumentsSection.present([]),
        mismo=MismoSection.present({}),
        tags=TagsSection.present({}),
    )


# --------------------------------------------------------------------------- #
# The classifier can ROUTE an LE/CD, but nothing extracts one — no orphaned extractor either way
# --------------------------------------------------------------------------- #
def test_classifier_catalogs_le_cd_but_no_extractor_is_registered() -> None:
    # The routing target exists: an LE/CD document classifies to a known type ...
    for doc_type in _LE_CD:
        assert doc_type in DOCUMENT_TYPE_INDICATORS
    # ... but NO extractor is registered, so it extracts nothing. (When an extractor is added, it MUST come
    # with a consumer — update this test and prove the field-name match, the LP-333/369 trap.)
    for doc_type in _LE_CD:
        assert doc_type not in EXTRACTORS


# --------------------------------------------------------------------------- #
# The only conceptual consumer (AS-3) cannot resolve from extraction alone — the recipe is a stub
# --------------------------------------------------------------------------- #
def test_the_only_consumer_as3_is_inert_and_its_recipe_only_abstains() -> None:
    assert (
        "AS-3" not in ACTIVE_RULE_IDS
    )  # inert (LP-380/381 held it, no-ai-dependency, input unresolved)
    # calc.cash_to_close is a STUB: it always abstains, naming the missing LE/CD extraction as the gap.
    value, reason = _cash_to_close_shortfall(_empty_snapshot(), "loan", None)
    assert value == "unknown" and "Closing-Disclosure" in reason
    # ... and there is no cash-to-close CALCULATOR (§3B) to build the requirement even if closing_costs existed.
    assert "cash_to_close" not in CALCULATORS


# --------------------------------------------------------------------------- #
# No NAME to emit an extractor against — no declared tag is sourced from an LE/CD field
# --------------------------------------------------------------------------- #
def test_no_declared_tag_is_sourced_from_an_le_cd_field() -> None:
    decls = load_declarations()
    # closing_costs appears ONLY as a breakdown LINE inside calc.cash_to_close's description — never as a
    # declared, materialized tag. So an LE/CD extractor today has no consumer field name to match.
    assert not any(
        tag_id.endswith("closing_costs") or tag_id.startswith(("le.", "cd.")) for tag_id in decls
    )


# --------------------------------------------------------------------------- #
# The natural LE/CD consumers (the TRID compliance rules) are out of scope for this engine
# --------------------------------------------------------------------------- #
def test_the_trid_compliance_rules_that_would_read_le_cd_are_out_of_scope() -> None:
    # DC-1..DC-7 are the TRID rules an LE/CD would feed; all are LOS-owned (out_of_scope), evaluated by no
    # rule here. So the compliance path is not a consumer either.
    for rid in ("DC-1", "DC-2", "DC-3", "DC-4", "DC-5", "DC-6", "DC-7"):
        rk = kind_for(rid)
        assert rk is not None and rk.kind is RuleKindName.OUT_OF_SCOPE
