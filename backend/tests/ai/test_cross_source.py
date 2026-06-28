"""The AI cross-source boundary (LP-78) — the prompt is general; parsing is defensive.

No real key: tests the prompt's generality and the defensive structured-output
parsing (the AI's perception is captured as typed findings, never prose).
"""

from app.ai.cross_source import (
    CROSS_SOURCE_SYSTEM_PROMPT,
    CrossSourceRawFinding,
    _parse_findings,
)

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
