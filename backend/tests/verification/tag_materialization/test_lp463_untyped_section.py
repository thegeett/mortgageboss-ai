"""LP-463 — the marked-UNTYPED section constraint.

The Tier-3 scoped free-extraction output rides in ``DocumentEntry.untyped_extraction``. It is available to a
processor and to AI cross-source reasoning (opt-in), but **NO DETERMINISTIC RULE MAY READ IT** — labels are
model-chosen and values uncoerced, so it must never drive a deterministic decision. These tests enforce that
structurally (the rule read path can't reach it) and by source scan (no rule/recipe names it), and prove the
opt-in visibility to reasoning.
"""

from pathlib import Path

from app.verification.snapshot.documents_section import _scrub_untyped
from app.verification.snapshot.model import DocumentEntry
from app.verification.tag_materialization.subjects import (
    ContextOptions,
    _doc_context,
    _doc_read_field,
)

_UNTYPED = {
    "document_type_guess": "wiring instructions",
    "key_parties": [{"name": "Liu Law Firm", "role": "sender"}],
    "key_amounts": [{"value": "204000.00", "context": "wire amount at closing"}],
    "summary": "Law-firm wiring instructions for closing funds.",
}


def _entry() -> DocumentEntry:
    return DocumentEntry(content_id="c1", document_type="unknown", untyped_extraction=_UNTYPED)


# --------------------------------------------------------------------------- #
# A deterministic rule CANNOT reach the untyped section
# --------------------------------------------------------------------------- #


def test_doc_read_field_never_returns_untyped() -> None:
    """A rule reads a document via ``_doc_read_field`` → ``entry.fields`` ONLY. No field name resolves the
    untyped section — not the attribute name, not one of its inner keys."""
    entry = _entry()
    for name in (
        "untyped_extraction",
        "summary",
        "key_parties",
        "key_amounts",
        "document_type_guess",
    ):
        assert _doc_read_field(entry, name) is None  # not in entry.fields → unreadable by any rule


def test_no_rule_or_recipe_source_references_the_untyped_section() -> None:
    """Structural scan: the deterministic rule engine (rules / recipes / rule_engine / conventional / fha)
    must not name ``untyped_extraction`` or the raw ``generic_analysis`` — only the AI paths may."""
    backend = Path(__file__).resolve().parents[2]
    verification = backend / "app" / "verification"
    rule_trees = ["rules", "rule_engine", "conventional", "fha"]
    offenders = []
    for tree in rule_trees:
        for py in (verification / tree).rglob("*.py"):
            text = py.read_text(encoding="utf-8")
            if "untyped_extraction" in text or "generic_analysis" in text:
                offenders.append(str(py.relative_to(backend)))
    assert offenders == [], f"deterministic rule code references the untyped section: {offenders}"


# --------------------------------------------------------------------------- #
# AI reasoning CAN reach it — but only opt-in
# --------------------------------------------------------------------------- #


def test_untyped_absent_from_context_by_default() -> None:
    ctx = _doc_context(_entry(), None, ContextOptions())  # default: include_untyped False
    assert "untyped_extraction" not in ctx


def test_untyped_present_in_context_only_when_opted_in() -> None:
    ctx = _doc_context(_entry(), None, ContextOptions(include_untyped=True))
    assert ctx["untyped_extraction"] == _UNTYPED


def test_typed_document_has_no_untyped_even_opted_in() -> None:
    """A typed/catalog document has untyped_extraction=None → nothing is added even under the opt-in."""
    typed = DocumentEntry(content_id="c2", document_type="pay_stub")
    ctx = _doc_context(typed, None, ContextOptions(include_untyped=True))
    assert "untyped_extraction" not in ctx


# --------------------------------------------------------------------------- #
# The identifier scrub (belt-and-braces at the snapshot boundary)
# --------------------------------------------------------------------------- #


def test_scrub_redacts_long_identifiers_keeps_short() -> None:
    scrubbed = _scrub_untyped(
        {
            "summary": "account 1234 5678 9012 3456 for John",
            "key_amounts": [{"value": "5000.00", "context": "deposit to ****6274"}],
        }
    )
    assert "1234 5678 9012 3456" not in scrubbed["summary"]  # 16-digit run redacted
    assert "[redacted]" in scrubbed["summary"]
    assert scrubbed["key_amounts"][0]["context"] == "deposit to ****6274"  # masked last-4 kept


def test_scrub_none_and_empty_return_none() -> None:
    assert _scrub_untyped(None) is None
    assert _scrub_untyped({}) is None
