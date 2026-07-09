"""Per-run snapshot primitives (LP-203).

The shared field shapes and PII handling every snapshot fact is built from. Pure
primitives — the snapshot model (LP-204) and the assemblers come later; nothing
consumes these yet.
"""

from app.verification.snapshot.fields import Field, FieldSource, JsonScalar
from app.verification.snapshot.pii import PiiField, PiiKind, mask, match_hash

__all__ = [
    "Field",
    "FieldSource",
    "JsonScalar",
    "PiiField",
    "PiiKind",
    "mask",
    "match_hash",
]
