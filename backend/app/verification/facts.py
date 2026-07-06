"""File facts (LP-74) — the typed-field snapshot the engine reads.

The deterministic engine reads **typed fields**, never prose. A :class:`FileFacts`
is that structured-data handoff: a mapping from a field path (e.g.
``"dti.back_end_pct"``) to a :class:`Fact` — a typed value plus an optional
source-location anchor.

Keeping facts a plain, pure data structure (no DB, no ORM) is deliberate:

* the engine (:mod:`app.verification.engine`) stays pure and trivially testable —
  a test constructs :class:`FileFacts` directly and asserts the findings;
* *how* facts are gathered (summing stated liabilities, computing a ratio,
  reading a current extraction) lives in the service layer
  (:mod:`app.services.verification_engine`), so the calculators (LP-76/77) can
  grow there without touching the engine.

A field path maps to at most one fact. A rule names the path(s) it ``reads``; the
engine looks each up here. A missing path (or a ``None`` value) means the file
does not yet carry that datum — the engine records the rule as *not evaluated*
rather than inventing a pass/fail.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class Fact:
    """One typed field value plus where it came from (the audit anchor).

    ``value`` is numeric (the LP-74 threshold engine compares numbers; a date
    becomes an age-in-days number upstream). ``source`` is a structured
    source-location placeholder — e.g. ``{"document_id": ..., "page": 2}`` or
    ``{"type": "computed", "note": "..."}`` — carried through onto the finding.
    LP-75 formalises source-location on the finding model.
    """

    value: Decimal | int | None
    source: dict[str, Any] | None = None


@dataclass(frozen=True)
class FileFacts:
    """The per-file typed snapshot — field path → :class:`Fact`."""

    values: Mapping[str, Fact] = field(default_factory=dict)

    def read(self, reads: Sequence[str]) -> Fact | None:
        """Read the (primary) typed field a rule needs.

        A rule's ``reads`` lists the field path(s) it consumes; LP-74 sample
        rules each compare one value, so the first path is the comparison datum.
        Returns ``None`` if the file does not carry it.
        """
        for path in reads:
            fact = self.values.get(path)
            if fact is not None:
                return fact
        return None
