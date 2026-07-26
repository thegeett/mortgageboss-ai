"""Generic vocabulary-driven tag materialization (LP-326).

Production is a property of the TAG, declared in the vocabulary and resolved by GENERIC producers —
adding a family's tags is declarations, never new producer Python (mirroring LP-324's rules-as-data).
Three modes: ``parsed`` (map an extraction field), ``derived`` (a deterministic recipe), ``ai`` (reuse
the LP-313 machinery). See :mod:`app.verification.tag_materialization.producer`.
"""

from __future__ import annotations

from app.verification.tag_materialization.declarations import (
    DeclarationError,
    ProductionMode,
    load_declarations,
    validate_declarations,
)
from app.verification.tag_materialization.derived import KNOWN_RECIPES
from app.verification.tag_materialization.producer import materialize_tags
from app.verification.tag_materialization.subjects import KNOWN_CONTEXT_BUILDERS

__all__ = [
    "KNOWN_CONTEXT_BUILDERS",
    "KNOWN_RECIPES",
    "DeclarationError",
    "ProductionMode",
    "load_declarations",
    "materialize_tags",
    "validate_declarations",
]
