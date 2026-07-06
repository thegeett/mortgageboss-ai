"""The deterministic evaluation loop (LP-74) — read → compare → emit.

Pure-engine tests (no DB): a value over the threshold fails, under passes, and
the overlay-patched threshold (45) produces a finding where the investor default
(50) would not — proving the patch is actually applied during evaluation.
"""

from decimal import Decimal

from app.models.lender import LoanProgram
from app.verification.engine import evaluate
from app.verification.facts import Fact, FileFacts
from app.verification.overlays.samples import SAMPLE_OVERLAY_LENDER_SLUG
from app.verification.registry import default_registry
from app.verification.rules.samples import CONV_DTI_BACK_END_MAX


def _result(findings, rule_id):
    return next(f for f in findings if f.rule.rule_id == rule_id)


def test_value_over_threshold_fails() -> None:
    """52 back-end DTI fails the 50 cap."""
    facts = FileFacts(values={"dti.back_end_pct": Fact(value=Decimal("52"))})
    results = evaluate(facts, [CONV_DTI_BACK_END_MAX])

    result = results[0]
    assert result.evaluated is True
    assert result.passed is False
    assert result.observed == Decimal("52")


def test_value_under_threshold_passes() -> None:
    """40 back-end DTI passes the 50 cap."""
    facts = FileFacts(values={"dti.back_end_pct": Fact(value=Decimal("40"))})
    results = evaluate(facts, [CONV_DTI_BACK_END_MAX])

    assert results[0].passed is True


def test_missing_datum_is_not_evaluated() -> None:
    """No value for the field → not-evaluated (the engine invents no verdict)."""
    results = evaluate(FileFacts(values={}), [CONV_DTI_BACK_END_MAX])

    assert results[0].evaluated is False
    assert results[0].passed is False
    assert results[0].observed is None


def test_overlay_patched_threshold_produces_a_finding_the_default_would_not() -> None:
    """48 passes the investor default (50) but fails the overlay value (45).

    Same observed value, same rule logic — only the composed threshold differs.
    This is the end-to-end proof that the overlay patch reaches evaluation.
    """
    facts = FileFacts(values={"dti.back_end_pct": Fact(value=Decimal("48"))})
    registry = default_registry()

    default_rules = registry.resolve(program=LoanProgram.CONVENTIONAL, lender_slug=None)
    patched_rules = registry.resolve(
        program=LoanProgram.CONVENTIONAL, lender_slug=SAMPLE_OVERLAY_LENDER_SLUG
    )

    default_dti = _result(evaluate(facts, default_rules), "conv.dti.back_end_max")
    patched_dti = _result(evaluate(facts, patched_rules), "conv.dti.back_end_max")

    assert default_dti.passed is True  # 48 <= 50
    assert patched_dti.passed is False  # 48 <= 45 → fails under the overlay
    assert patched_dti.rule.overlay_applied == SAMPLE_OVERLAY_LENDER_SLUG


def test_source_location_is_carried_through() -> None:
    """The fact's source-location anchor reaches the engine result."""
    source = {"document_id": "abc", "page": 2}
    facts = FileFacts(values={"dti.back_end_pct": Fact(value=Decimal("40"), source=source)})
    results = evaluate(facts, [CONV_DTI_BACK_END_MAX])

    assert results[0].source_location == source
