"""The shipped ``_LIST_SPECS`` must match the JSON specs that generate them (LP-479 follow-up).

LP-479 found that ``credit_report``'s spec declared no ``redact`` while the shipped module declared one:
regenerating that spec and pasting the emitted snippet would have silently dropped the redaction and
un-masked a full account number at rest. It fixed that one list. The drift existed in **ten**.

The mechanism makes this the default failure, not bad luck. ``emit_list_specs`` writes ``redact`` and
``stable_row_id`` ONLY when the spec declares them (``emitters.py``), and the spec is the source of truth
(a spec-only edit regenerates byte-identically; a module-only edit is lost on the next regeneration —
LP-445). So a module-only declaration is invisible to the generator and disappears the moment anyone
regenerates, and a spec-only declaration never reaches runtime at all. Both directions are silent.

This test closes the loop in both directions, per registered list:

* **spec declares, module omits** — the declaration never shipped. Live PII gap
  (``custom.unmapped_key_value_pairs``: the spec's own ``pii_note`` says any PII on a Custom document
  lands in that passthrough unmasked).
* **module declares, spec omits** — the declaration is one regeneration away from being dropped.

Deliberately scoped to ``redact`` + ``stable_row_id``: those are the two helpers with a *safety*
consequence (PII at rest; stable subject identity for a rule enumerating rows). ``fields`` and ``derived``
are covered by the generator's own emit tests, and a field-list difference fails loudly at extraction
rather than silently at the snapshot boundary.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.ai.extraction.generator.spec import load_spec
from app.verification.snapshot.documents_section import _LIST_SPECS

_SPECS_DIR = Path(__file__).resolve().parents[3].parent / "docs" / "schema-specs"


def _specs_by_document_type() -> dict[str, Path]:
    """Map ``document_type`` → its spec file. Read raw: a spec too broken to load is its own failure."""
    out: dict[str, Path] = {}
    for path in sorted(_SPECS_DIR.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        doc_type = payload.get("document_type")
        if isinstance(doc_type, str) and doc_type:
            out[doc_type] = path
    return out


def test_specs_dir_is_found() -> None:
    """Guard the path derivation — a wrong root would make every parity case vacuously pass."""
    assert _SPECS_DIR.is_dir(), f"schema-specs not found at {_SPECS_DIR}"
    assert len(_specs_by_document_type()) > 100


@pytest.mark.parametrize("doc_type", sorted(_LIST_SPECS))
def test_list_spec_matches_its_json_spec(doc_type: str) -> None:
    """Every registered list's ``redact`` + ``stable_row_id`` match its spec declaration, both ways."""
    specs = _specs_by_document_type()
    spec_path = specs.get(doc_type)
    assert spec_path is not None, (
        f"{doc_type} is registered in _LIST_SPECS but has no docs/schema-specs entry — "
        "the spec is the source of truth, so a registered list with no spec cannot be regenerated"
    )
    declared = {nl.name: nl for nl in load_spec(spec_path).nested_lists}

    for shipped in _LIST_SPECS[doc_type]:
        nl = declared.get(shipped.name)
        assert nl is not None, (
            f"{doc_type}.{shipped.name} ships in _LIST_SPECS but is not declared in "
            f"{spec_path.name} nested_lists"
        )
        assert set(shipped.redact) == set(nl.redact), (
            f"{doc_type}.{shipped.name}: redact drift — "
            f"module={sorted(shipped.redact)} spec={sorted(nl.redact)} ({spec_path.name}). "
            "A module-only redaction is dropped on the next regeneration; a spec-only redaction "
            "never shipped. Declare it in BOTH."
        )
        assert shipped.stable_row_id == nl.stable_row_id, (
            f"{doc_type}.{shipped.name}: stable_row_id drift — "
            f"module={shipped.stable_row_id} spec={nl.stable_row_id} ({spec_path.name})"
        )
