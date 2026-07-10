"""Per-run snapshot (LP-203 primitives + LP-204 model).

The shared field shapes and PII handling every snapshot fact is built from
(LP-203), plus the frozen three-section snapshot model (LP-204). The assemblers
that populate the model come later (LP-205-207); nothing consumes these yet.
"""

from app.verification.snapshot.fields import Field, FieldSource, JsonScalar
from app.verification.snapshot.model import (
    SNAPSHOT_SCHEMA_VERSION,
    CalcSource,
    Calculation,
    CalculationLine,
    Calculations,
    DocumentSnapshot,
    Snapshot,
    SnapshotField,
)
from app.verification.snapshot.pii import PiiField, PiiKind, mask, match_hash

__all__ = [
    "SNAPSHOT_SCHEMA_VERSION",
    "CalcSource",
    "Calculation",
    "CalculationLine",
    "Calculations",
    "DocumentSnapshot",
    "Field",
    "FieldSource",
    "JsonScalar",
    "PiiField",
    "PiiKind",
    "Snapshot",
    "SnapshotField",
    "mask",
    "match_hash",
]
