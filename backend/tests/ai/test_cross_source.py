"""The AI cross-source boundary (LP-78) — the prompt is general; parsing is defensive.

No real key: tests the prompt's generality and the defensive structured-output
parsing (the AI's perception is captured as typed findings, never prose). Also
covers the consistency hardening — canonical types with an "other" escape hatch
for novel discrepancies, deterministic settings, and the truncation guard.
"""

import app.ai.cross_source as cross_source
import pytest
from app.ai.client import AICompletion
from app.ai.cross_source import (
    CROSS_SOURCE_SYSTEM_PROMPT,
    CrossSourceRawFinding,
    _parse_findings,
    reason_cross_source,
)
from structlog.testing import capture_logs

_VALID = """
{"findings": [
  {"type": "income_variance", "category": "income", "severity": "yellow",
   "description": "Stated income exceeds documents by 8%",
   "stated_value": "16400", "document_value": "15100", "amount": "1300",
   "source_document_type": "pay_stub", "page": 1, "snippet": "Gross 3,775",
   "confidence": 0.82, "reasoning": "8% over"}
]}
"""


def test_prompt_is_general_not_a_fixed_checklist() -> None:
    """The prompt directs a general read-and-compare, not N hardcoded checks."""
    # Normalize whitespace (the prompt is line-wrapped) before checking phrases.
    prompt = " ".join(CROSS_SOURCE_SYSTEM_PROMPT.lower().split())
    assert "does not line up" in prompt
    assert "do not run a fixed checklist" in prompt
    # It guides toward high-value comparisons but does not limit to them.
    assert "do not limit yourself to these" in prompt
    assert "surfacing candidates" in prompt  # human review, not a decision


def test_prompt_has_canonical_types_with_an_open_other_escape_hatch() -> None:
    """Canonical types stop label churn, but novel discrepancies MUST still survive."""
    prompt = " ".join(CROSS_SOURCE_SYSTEM_PROMPT.lower().split())
    # The known high-frequency types are pinned to exact strings.
    for canonical in (
        "income_variance",
        "employer_mismatch",
        "gift_documentation_missing",
        "co_borrower_income_missing",
        "property_address_mismatch",
    ):
        assert canonical in prompt
    # The enum is NOT closed — "other" is first-class, with a required description,
    # so novel findings are surfaced rather than discarded (the key constraint).
    assert '"other"' in prompt
    assert "never discard a real discrepancy" in prompt
    # Granularity rules keep the count stable run to run.
    assert "report each distinct discrepancy exactly once" in prompt
    assert "do not split a single issue" in prompt


def test_other_type_finding_parses_and_survives() -> None:
    """A novel discrepancy reported as type 'other' is parsed (not dropped)."""
    novel = (
        '{"findings": [{"type": "other", "category": "property", "severity": "yellow",'
        ' "description": "Driver\'s license address matches the subject property",'
        ' "confidence": 0.7}]}'
    )
    findings = _parse_findings(novel)
    assert len(findings) == 1
    assert findings[0].type == "other"
    assert "subject property" in (findings[0].description or "")


def test_parses_structured_findings() -> None:
    findings = _parse_findings(_VALID)
    assert len(findings) == 1
    f = findings[0]
    assert isinstance(f, CrossSourceRawFinding)
    assert f.type == "income_variance"
    assert f.document_value == "15100"
    assert f.page == 1
    assert f.confidence == 0.82


def test_tolerates_prose_and_fences() -> None:
    """Markdown fences / surrounding prose don't break parsing (defensive)."""
    wrapped = f"Here are the findings:\n```json\n{_VALID}\n```\nThanks!"
    assert len(_parse_findings(wrapped)) == 1


def test_garbage_yields_no_findings() -> None:
    """Unparseable output → no findings (never raises; nothing invented)."""
    assert _parse_findings("the model said no") == []
    assert _parse_findings("{not json") == []
    assert _parse_findings('{"findings": "not a list"}') == []


def test_skips_malformed_items_keeps_valid() -> None:
    mixed = (
        '{"findings": ['
        '{"description": "no type"},'  # dropped — missing type
        '{"type": "gift_mismatch", "description": "ok", "confidence": 2.0}'  # clamped
        "]}"
    )
    findings = _parse_findings(mixed)
    assert len(findings) == 1
    assert findings[0].type == "gift_mismatch"
    assert findings[0].confidence == 1.0  # confidence clamped to [0, 1]


def test_dropped_entries_are_logged() -> None:
    """A malformed entry the model returned is surfaced (raw-vs-parsed), not silent."""
    mixed = '{"findings": [{"description": "no type"}, {"type": "income_variance", "description": "ok"}]}'
    with capture_logs() as logs:
        _parse_findings(mixed)
    events = [log["event"] for log in logs]
    assert "cross_source_findings_dropped" in events


async def test_reason_uses_deterministic_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """The pass runs at temperature 0 with the raised token budget (consistency)."""
    captured: dict[str, object] = {}

    async def _fake_complete(**kwargs: object) -> AICompletion:
        captured.update(kwargs)
        return AICompletion(
            text='{"findings": []}',
            input_tokens=10,
            output_tokens=5,
            model="m",
            stop_reason="end_turn",
        )

    monkeypatch.setattr(cross_source, "complete", _fake_complete)
    await reason_cross_source("{}")

    assert captured["temperature"] == 0.0
    assert captured["max_tokens"] == cross_source._MAX_TOKENS
    assert cross_source._MAX_TOKENS >= 8192


async def test_truncation_is_surfaced_not_silent(monkeypatch: pytest.MonkeyPatch) -> None:
    """A response cut at max_tokens logs a truncation warning (never silently dropped)."""

    async def _truncated(**kwargs: object) -> AICompletion:
        return AICompletion(
            text="{garbage",
            input_tokens=10,
            output_tokens=8192,
            model="m",
            stop_reason="max_tokens",
        )

    monkeypatch.setattr(cross_source, "complete", _truncated)
    with capture_logs() as logs:
        result = await reason_cross_source("{}")
    events = [log["event"] for log in logs]
    assert "cross_source_response_truncated" in events
    assert result.findings == []  # truncated body parsed to nothing — but it was surfaced
