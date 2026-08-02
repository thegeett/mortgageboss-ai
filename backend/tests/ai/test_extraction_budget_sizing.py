"""LP-103 — right-sized extraction budgets for unbounded document types.

LP-102 fixed pay-stub truncation (budget too small for its verbose output) + added the shared
truncation guard. An audit then found the SAME shape on other types: an unbounded "capture every X"
catch-all still at the 4096 scaffold budget. This raises the four flagged types to 8192 —
investment_account (CONFIRMED truncating on LF-6T3N, a silently-empty asset doc), retirement_account
(same holdings shape), profit_and_loss, purchase_agreement — while leaving the correctly-sized types
alone (no blanket raise: a right-sized budget is a meaningful size/anomaly signal, and the LP-102
guard is the backstop for the un-raised tail).
"""

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from app.ai.extraction import (
    bank_statement,
    divorce_decree,
    drivers_license,
    form_1099,
    gift_letter,
    hoa_statement,
    homeowners_insurance,
    investment_account,
    letter_of_explanation,
    model_call,
    mortgage_statement,
    pay_stub,
    profit_and_loss,
    property_tax_bill,
    purchase_agreement,
    retirement_account,
    tax_return,
    voe,
    w2,
)
from app.models.extraction import ExtractionStatus

_PDF = b"%PDF-1.4 fake"


def _resp(text: str | None, *, stop_reason: str = "end_turn") -> SimpleNamespace:
    return SimpleNamespace(
        text=text, input_tokens=500, output_tokens=300, model="m", stop_reason=stop_reason
    )


def _patch(monkeypatch: pytest.MonkeyPatch, *, side_effect: Any) -> AsyncMock:
    mock = AsyncMock(side_effect=side_effect)
    monkeypatch.setattr(model_call, "complete", mock)
    return mock


def _dense_rows(prefix: str, n: int = 40) -> list[dict[str, Any]]:
    """A long line-item list — the unbounded catch-all that overflowed 4096."""
    return [
        {
            "label": f"{prefix}{i}",
            "value": f"{i * 1000}.00",
            "page": 1,
            "snippet": f"{prefix}{i} {i * 1000}.00",
        }
        for i in range(n)
    ]


INVESTMENT_JSON = json.dumps(
    {
        "typed_core": {
            "institution_name": {"value": "Vanguard", "page": 1, "snippet": "Vanguard"},
            "total_value": {"value": "1250000.00", "page": 1, "snippet": "Total 1,250,000.00"},
        },
        "additional_sections": [{"section": "Holdings", "fields": _dense_rows("FUND")}],
        "confidence": 0.95,
        "reasoning": "brokerage with itemized holdings",
    }
)
RETIREMENT_JSON = json.dumps(
    {
        "typed_core": {
            "institution_name": {"value": "Fidelity", "page": 1, "snippet": "Fidelity"},
            "vested_balance": {"value": "480000.00", "page": 1, "snippet": "Vested 480,000.00"},
        },
        "additional_sections": [{"section": "Holdings", "fields": _dense_rows("FUND")}],
        "confidence": 0.95,
        "reasoning": "401k with itemized holdings",
    }
)
PNL_JSON = json.dumps(
    {
        "typed_core": {
            "business_name": {"value": "Swad Mania LLC", "page": 1, "snippet": "Swad Mania"},
            "net_profit": {"value": "88200.00", "page": 1, "snippet": "Net 88,200.00"},
        },
        "additional_sections": [{"section": "Major Expenses", "fields": _dense_rows("Expense")}],
        "confidence": 0.9,
        "reasoning": "detailed P&L",
    }
)
PURCHASE_JSON = json.dumps(
    {
        "typed_core": {
            "property_address": {"value": "123 Main St", "page": 1, "snippet": "123 Main St"},
            "sales_price": {"value": "1380000.00", "page": 1, "snippet": "1,380,000"},
        },
        "additional_sections": [{"section": "Contingencies", "fields": _dense_rows("Clause")}],
        "confidence": 0.9,
        "reasoning": "heavily-amended contract",
    }
)


# --------------------------------------------------------------------------- #
# The budgets — the four unbounded types raised; everything else UNCHANGED
# --------------------------------------------------------------------------- #


def test_unbounded_types_raised_to_8192() -> None:
    assert investment_account._MAX_TOKENS == 8192  # confirmed live failure on LF-6T3N
    assert retirement_account._MAX_TOKENS == 8192  # same holdings shape
    assert profit_and_loss._MAX_TOKENS == 8192
    assert purchase_agreement._MAX_TOKENS == 8192


def test_correctly_sized_types_are_unchanged_no_blanket_raise() -> None:
    # Already right-sized (bumped earlier) — left as-is.
    assert tax_return._MAX_TOKENS == 16384
    assert bank_statement._MAX_TOKENS == 8192
    assert pay_stub._MAX_TOKENS == 8192  # LP-102
    assert divorce_decree._MAX_TOKENS == 6144
    # Bounded / semi-bounded fixed-form types — small budget is CORRECT; the LP-102 guard backstops
    # any rare overflow. NOT preemptively raised (that removes the size-expectation signal).
    assert drivers_license._MAX_TOKENS == 2048
    for mod in (
        w2,
        voe,
        letter_of_explanation,
        homeowners_insurance,
        mortgage_statement,
        hoa_statement,
        property_tax_bill,
        form_1099,
        gift_letter,
    ):
        assert mod._MAX_TOKENS == 4096


def test_every_wired_generated_extractor_matches_the_sizing_rule() -> None:
    """LP-443 (step 7) extends the guard to the wired GENERATED modules — LP-440 noted this test only
    named the 18 shipping types. Every generated extractor's ``_MAX_TOKENS`` must equal the sizing rule
    (``max_tokens_for``: 0 lists → 4096, 1 → 8192, ≥2 → 16384) derived from its spec's nested-list count,
    so a regeneration can never silently under-budget a list-bearing type."""
    import importlib
    import json
    from pathlib import Path

    from app.ai.extraction import EXTRACTORS
    from app.ai.extraction.generator.emitters import max_tokens_for
    from app.ai.extraction.generator.spec import load_spec

    backend = Path(__file__).resolve().parents[2]
    specs = backend.parent / "docs" / "schema-specs"
    ext_dir = backend / "app" / "ai" / "extraction"
    by_dt = {json.loads(p.read_text())["document_type"]: p for p in specs.glob("[0-9]*.json")}
    marker = "GENERATED from a schema spec by the LP-434 generator"

    checked, mismatches = 0, []
    for dt in EXTRACTORS:
        spec_path = by_dt.get(dt)
        module_file = ext_dir / f"{dt}.py"
        # Skip a type whose module isn't a same-named generated file: shipping extractors, and the
        # diff-mode "1099" (its extractor lives in form_1099.py — not a generated module named "1099").
        if spec_path is None or not module_file.exists() or marker not in module_file.read_text():
            continue
        module = importlib.import_module(f"app.ai.extraction.{dt}")
        checked += 1
        expected = max_tokens_for(load_spec(str(spec_path)))
        if expected != module._MAX_TOKENS:
            mismatches.append((dt, module._MAX_TOKENS, expected))
    assert checked >= 80, f"expected the full generated fleet to be wired, only checked {checked}"
    assert mismatches == [], f"generated modules mis-budgeted (module != sizing rule): {mismatches}"


# --------------------------------------------------------------------------- #
# The raised types extract a DENSE instance fully (the confirmed-failure regression)
# --------------------------------------------------------------------------- #


async def test_investment_dense_holdings_extracts_fully(monkeypatch: pytest.MonkeyPatch) -> None:
    mock = _patch(monkeypatch, side_effect=[_resp(INVESTMENT_JSON)])
    result = await investment_account.extract_investment_account(_PDF, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED  # not empty / NEEDS_REVIEW
    assert result.data.total_value.value is not None  # the KEY reserves figure populated
    holdings = next(s for s in result.data.additional_sections if s.section == "Holdings")
    assert len(holdings.fields) == 40  # the full itemized list, not truncated
    assert mock.await_args_list[0].kwargs["max_tokens"] == 8192  # the raised budget is used


async def test_retirement_dense_holdings_extracts_fully(monkeypatch: pytest.MonkeyPatch) -> None:
    mock = _patch(monkeypatch, side_effect=[_resp(RETIREMENT_JSON)])
    result = await retirement_account.extract_retirement_account(_PDF, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED
    assert result.data.vested_balance.value is not None
    assert mock.await_args_list[0].kwargs["max_tokens"] == 8192


async def test_profit_and_loss_dense_extracts_fully(monkeypatch: pytest.MonkeyPatch) -> None:
    mock = _patch(monkeypatch, side_effect=[_resp(PNL_JSON)])
    result = await profit_and_loss.extract_profit_and_loss(_PDF, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED
    assert result.data.net_profit.value is not None
    assert mock.await_args_list[0].kwargs["max_tokens"] == 8192


async def test_purchase_agreement_dense_extracts_fully(monkeypatch: pytest.MonkeyPatch) -> None:
    mock = _patch(monkeypatch, side_effect=[_resp(PURCHASE_JSON)])
    result = await purchase_agreement.extract_purchase_agreement(_PDF, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED
    assert result.data.sales_price.value is not None
    assert mock.await_args_list[0].kwargs["max_tokens"] == 8192


# --------------------------------------------------------------------------- #
# Composes with the LP-102 guard — the backstop still applies to a raised type
# --------------------------------------------------------------------------- #


async def test_raised_type_still_backstopped_by_the_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    """Even at 8192, if an extreme instance truncated, the LP-102 guard retries once at 16384 —
    right-sizing didn't remove the backstop."""
    mock = _patch(
        monkeypatch,
        side_effect=[
            _resp("{truncated…", stop_reason="max_tokens"),  # attempt 1 at 8192 truncates
            _resp(INVESTMENT_JSON, stop_reason="end_turn"),  # retry at 16384 fits
        ],
    )
    result = await investment_account.extract_investment_account(_PDF, "application/pdf")
    assert mock.await_count == 2
    assert (
        mock.await_args_list[0].kwargs["max_tokens"] == 8192
    )  # first attempt at the raised budget
    assert mock.await_args_list[1].kwargs["max_tokens"] == 16384  # guard's retry ceiling
    assert result.status == ExtractionStatus.SUCCEEDED
