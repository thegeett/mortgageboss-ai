"""Document staleness + package fitness (LP-71) — deterministic, date-driven.

Staleness is a **threshold rule, like DTI** — not a new AI call. The AI's contribution
is the *date extraction* (the Tier 1 extractors already capture pay date / statement
period / ID expiration, LP-60..64); this module *judges* freshness deterministically:

  * **Recency windows** — a dated document is stale if its extracted date is older than
    a configured window (a pay stub within ~30 days, a bank statement within ~60 days).
  * **Expiration** — an expiring document is stale once its date has passed (a driver's
    license / insurance policy past its expiration).

The processor RESOLVES a flagged-stale document (waive / accept — stored on the doc;
*replace* is the versioning flow). Auto-resolution is V2.

**Package fitness** combines versioning + staleness: a document is fit for the lender
package when it is the CURRENT version AND not stale-unresolved; a historical
(superseded) or stale document is flagged, not silently included. Assembly is Phase 6;
this is the data groundwork.

The recency windows below are **sensible industry-standard starters — REFINE WITH
PRIYA** (her lenders' [UWM, Sun-West] exact windows vary by program). They are a plain
config dict: editing them is the whole knob.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel

from app.models.base import utcnow
from app.models.document import Document, StalenessResolution
from app.models.extraction import Extraction

StalenessKind = Literal["aged", "expired"]


@dataclass(frozen=True)
class RecencyRule:
    """A document is stale if its extracted date is older than ``max_age_days``."""

    max_age_days: int
    # The extracted_data keys to read the date from, in preference order.
    fields: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ExpirationRule:
    """A document is stale (expired) once the extracted date is before today."""

    fields: tuple[str, ...] = field(default_factory=tuple)


# --- The configurable windows (SENSIBLE STARTERS — REFINE WITH PRIYA) ----------- #
# Keyed by ``document_type``. Recency = "must be recent enough"; expiration = "must not
# have lapsed". Priya's lenders' exact windows (varying by program) refine these.
RECENCY_WINDOWS: dict[str, RecencyRule] = {
    "pay_stub": RecencyRule(max_age_days=30, fields=("pay_date", "pay_period_end")),
    "bank_statement": RecencyRule(max_age_days=60, fields=("statement_period_end",)),
}
EXPIRATION_RULES: dict[str, ExpirationRule] = {
    "drivers_license": ExpirationRule(fields=("expiration_date",)),
    "homeowners_insurance": ExpirationRule(fields=("expiration_date",)),
}


class StalenessInfo(BaseModel):
    """A document's freshness assessment — deterministic, date-driven."""

    is_stale: bool  # aged/expired AND not resolved
    kind: StalenessKind | None  # why it's stale (or would be), if dated
    reason: str | None  # human-readable, for the calm warning
    resolution: StalenessResolution | None  # the processor's decision (clears the flag)
    as_of_date: date | None  # the extracted date the assessment used


class PackageFitness(BaseModel):
    """Is this document fit for the lender package? (current + fresh). Groundwork."""

    fit: bool
    reason: str | None  # why not: "superseded" | "stale" | None


def _read_date(extracted_data: dict[str, Any], fields: tuple[str, ...]) -> date | None:
    """Read the first present date (TypedField ``{value, source}``) from ``fields``."""
    for key in fields:
        cell = extracted_data.get(key)
        raw = cell.get("value") if isinstance(cell, dict) else None
        if raw is None:
            continue
        if isinstance(raw, date):
            return raw
        try:
            return date.fromisoformat(str(raw)[:10])
        except ValueError:
            continue
    return None


def evaluate_staleness(
    document: Document,
    extraction: Extraction | None,
    *,
    today: date | None = None,
) -> StalenessInfo:
    """Assess a document's freshness from its extracted date + the configured window.

    Deterministic: no AI call. Returns ``is_stale=False`` when the type has no window,
    there's no usable extracted date, or the processor already resolved it. A resolved
    document keeps its ``resolution`` (so the UI can show "accepted"/"waived") but is no
    longer flagged.
    """
    today = today or utcnow().date()
    resolution = document.staleness_resolution
    data = extraction.extracted_data if extraction is not None else {}
    doc_type = document.document_type or ""

    kind: StalenessKind | None = None
    reason: str | None = None
    as_of: date | None = None

    if doc_type in EXPIRATION_RULES:
        as_of = _read_date(data, EXPIRATION_RULES[doc_type].fields)
        if as_of is not None and as_of < today:
            kind = "expired"
            reason = f"Expired {(today - as_of).days} days ago (dated {as_of.isoformat()})."
    elif doc_type in RECENCY_WINDOWS:
        rule = RECENCY_WINDOWS[doc_type]
        as_of = _read_date(data, rule.fields)
        if as_of is not None:
            age = (today - as_of).days
            if age > rule.max_age_days:
                kind = "aged"
                reason = f"Dated {age} days ago — may exceed the ~{rule.max_age_days}-day window."

    # A resolved document is no longer flagged (the processor decided), but we keep the
    # resolution + the assessed date for display.
    is_stale = kind is not None and resolution is None
    return StalenessInfo(
        is_stale=is_stale,
        kind=kind,
        reason=reason if is_stale else None,
        resolution=resolution,
        as_of_date=as_of,
    )


def package_fitness(document: Document, staleness: StalenessInfo) -> PackageFitness:
    """Whether the document is fit for the lender package (current + fresh).

    Combines versioning (current vs. historical/superseded) + staleness (fresh vs.
    stale). A superseded document (a newer version is current) or a stale-unresolved one
    is flagged — not silently included. The package itself is Phase 6; this is the data.
    """
    if not document.is_current:
        return PackageFitness(fit=False, reason="superseded")
    if staleness.is_stale:
        return PackageFitness(fit=False, reason="stale")
    return PackageFitness(fit=True, reason=None)
