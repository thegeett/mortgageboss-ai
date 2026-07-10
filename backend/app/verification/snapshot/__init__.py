"""Per-run snapshot (LP-203 primitives + LP-204 container model).

The shared field shapes + PII handling (LP-203) and the frozen three-section
container (LP-204) that assemblers code against. Nothing populates the container
yet — assemblers (LP-205/206/207), the builder (LP-208), and persistence (LP-209)
come later.
"""

from app.verification.snapshot.builder import LoanFileNotFound, build_snapshot
from app.verification.snapshot.calculations_section import build_calculations_section
from app.verification.snapshot.documents_section import (
    build_document_fields,
    build_documents_section,
    build_transactions,
)
from app.verification.snapshot.fields import Field, FieldSource, JsonScalar
from app.verification.snapshot.mismo_section import build_mismo_section, load_mismo_section
from app.verification.snapshot.model import (
    SNAPSHOT_VERSION,
    BorrowerRef,
    CalcBreakdownLine,
    CalculationEntry,
    CalculationsSection,
    DocumentEntry,
    DocumentsSection,
    MismoSection,
    Snapshot,
    SnapshotField,
    TransactionRecord,
)
from app.verification.snapshot.persistence import (
    RawPiiAtRestError,
    SnapshotAlreadyPersisted,
    load_snapshot,
    load_snapshots_for_loan_file,
    persist_snapshot,
)
from app.verification.snapshot.pii import PiiField, PiiKind, mask, match_hash

__all__ = [
    "SNAPSHOT_VERSION",
    "BorrowerRef",
    "CalcBreakdownLine",
    "CalculationEntry",
    "CalculationsSection",
    "DocumentEntry",
    "DocumentsSection",
    "Field",
    "FieldSource",
    "JsonScalar",
    "LoanFileNotFound",
    "MismoSection",
    "PiiField",
    "PiiKind",
    "RawPiiAtRestError",
    "Snapshot",
    "SnapshotAlreadyPersisted",
    "SnapshotField",
    "TransactionRecord",
    "build_calculations_section",
    "build_document_fields",
    "build_documents_section",
    "build_mismo_section",
    "build_snapshot",
    "build_transactions",
    "load_mismo_section",
    "load_snapshot",
    "load_snapshots_for_loan_file",
    "mask",
    "match_hash",
    "persist_snapshot",
]
