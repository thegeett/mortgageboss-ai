"""Snapshot-based AI cross-source findings — the read/write shapes (LP-586)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class SnapshotFindingSource(BaseModel):
    """One side of the comparison — what makes a finding CROSS-source."""

    label: str
    value: str


class SnapshotFindingPublic(BaseModel):
    """One observation, as a processor sees it."""

    id: UUID
    kind: str
    title: str
    detail: str
    sources: list[SnapshotFindingSource]
    # open | resolved (the system's) · signed_off | not_an_issue (the processor's)
    disposition: str
    disposition_note: str | None
    first_seen_at: datetime
    last_seen_at: datetime


class SnapshotFindingDisposition(BaseModel):
    """A processor's disposition.

    ⚠️ NO APPLY, and the absence is the design. This pass has no rule spec, no calibrated threshold
    and no guideline citation, so it may not write to the loan — only record what a human decided.
    `resolved` is excluded too: that one is the system's, set when the file stops producing the
    finding, and letting a client claim it would let the tab lie about why something cleared.
    """

    disposition: str = Field(pattern="^(signed_off|not_an_issue|open)$")
    note: str | None = None
