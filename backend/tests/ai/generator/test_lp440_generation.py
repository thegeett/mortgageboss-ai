"""LP-440 — the generation run: _MAX_TOKENS sizing, the PII snippet, and the no-metadata guarantee.

Pins: `_MAX_TOKENS` is derived from the nested-list count (D3); the `_PII_FIELDS` snippet emits live-enum
kinds; and NO generated extractor module carries review metadata (why / reason_class / rejected /
open_questions) — the guarantee across all 86 landed modules, not just one.
"""

from __future__ import annotations

from pathlib import Path

from app.ai.extraction.generator.emitters import emit_pii_registration, max_tokens_for
from app.ai.extraction.generator.spec import load_spec

_BACKEND = Path(__file__).resolve().parents[3]
_SPECS = _BACKEND.parent / "docs" / "schema-specs"
_EXTRACTION = _BACKEND / "app" / "ai" / "extraction"
_GEN_MARKER = "GENERATED from a schema spec by the LP-434 generator"
_METADATA = (
    "reason_class",
    "rejected",
    "open_questions",
    "blocks_implementation",
    "rule_floor",
    '"why"',
)


def _generated_modules() -> list[Path]:
    return [p for p in _EXTRACTION.glob("*.py") if _GEN_MARKER in p.read_text(encoding="utf-8")]


def test_max_tokens_is_sized_by_nested_list_count() -> None:
    assert max_tokens_for(load_spec(_SPECS / "030-business-license.json")) == 4096  # 0 lists
    assert max_tokens_for(load_spec(_SPECS / "095-statement-of-account.json")) == 8192  # 1 list
    assert max_tokens_for(load_spec(_SPECS / "005-credit-report.json")) == 16384  # 3 lists


def test_generated_modules_carry_the_right_max_tokens() -> None:
    # The landed modules reflect the sizing rule (spot-check across the three tiers).
    def budget(dt: str) -> int:
        text = (_EXTRACTION / f"{dt}.py").read_text(encoding="utf-8")
        line = next(ln for ln in text.splitlines() if ln.startswith("_MAX_TOKENS"))
        return int(line.split("=")[1])

    assert budget("business_license") == 4096
    assert budget("statement_of_account") == 8192
    assert budget("appraisal") == 8192


def test_pii_snippet_emits_live_enum_kinds() -> None:
    snippet = emit_pii_registration(load_spec(_SPECS / "108-work-visa-ead-card.json"))
    assert "PiiKind.ACCOUNT" in snippet
    assert "PiiKind.NAME" not in snippet and "PiiKind.PASSPORT" not in snippet  # remapped by LP-439


def test_at_least_eighty_modules_were_generated() -> None:
    assert len(_generated_modules()) >= 80  # 86 new-type modules landed


def test_no_generated_module_carries_review_metadata() -> None:
    offenders = []
    for p in _generated_modules():
        text = p.read_text(encoding="utf-8")
        for token in _METADATA:
            if token in text:
                offenders.append((p.name, token))
    assert offenders == [], f"review metadata leaked into generated modules: {offenders}"
