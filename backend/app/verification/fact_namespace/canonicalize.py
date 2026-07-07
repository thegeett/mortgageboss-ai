"""Category canonicalization (LP-118.6) — map-first, AI-fallback-for-misses, learn.

Raw-string category fields (``income_type`` / ``asset_type`` / ``liability_type``) are free text
in the DB (fact-namespace-foundation §4). This ONE general mechanism canonicalizes them to a clean
vocabulary at **fact-build time**, so the result is FROZEN into the snapshot and rule evaluation
later reads a deterministic canonical value — no AI call at eval time, no drift within a run.

The logic (ADR-239):

1. **map-first** — a curated, version-controlled map (``canonicalization_map.json``) handles the
   common variants deterministically.
2. **AI-fallback-for-misses** — any string the map misses goes to a fallback SEAM, so an unknown
   string is NEVER silently ignored (the failure mode of a pure hardcoded map). The default seam
   (:class:`NoFallback`) returns nothing and records the miss as ``UNMAPPED`` — a live AI call is
   out of scope for this ticket, so this is a documented, clearly-marked seam that LP-120 fills;
   **AI results are never faked**.
3. **learn** — a fallback answer is recorded back into the in-run map so a repeat string in the
   same run needs no second call (deterministic within a run). Persistent cross-run learning (write
   back to the map file / a learned table) is a seam LP-120 owns.

Cousin of the LP-120 DET-FUZZY entity matching, kept distinct (category canonicalization vs. fuzzy
name/employer matching).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from app.verification.fact_namespace.snapshot import Fact, FactSource

_MAP_PATH = Path(__file__).with_name("canonicalization_map.json")


def _normalize(raw: str) -> str:
    """Lowercase, strip, collapse internal whitespace — the map lookup key."""
    return re.sub(r"\s+", " ", raw.strip().lower())


@dataclass(frozen=True)
class FallbackAnswer:
    """A fallback classifier's answer for a map miss."""

    canonical: str
    confidence: float


class CanonicalizationFallback(Protocol):
    """The seam an AI-backed classifier implements (LP-120). Returns ``None`` if it can't classify."""

    def classify(self, field: str, raw: str, vocab: list[str]) -> FallbackAnswer | None: ...


class NoFallback:
    """The default seam — no AI wired in this environment. Records the miss (returns ``None``)."""

    def classify(self, field: str, raw: str, vocab: list[str]) -> FallbackAnswer | None:
        return None


def _load_maps() -> dict[str, dict[str, dict[str, str] | list[str]]]:
    data = json.loads(_MAP_PATH.read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if not k.startswith("_")}


@dataclass
class Canonicalizer:
    """The build-time canonicalizer. One instance per run — its ``learned`` map holds fallback
    answers so a repeat raw string in the same run is deterministic (no second fallback call)."""

    fallback: CanonicalizationFallback = field(default_factory=NoFallback)
    _maps: dict[str, dict[str, dict[str, str] | list[str]]] = field(default_factory=_load_maps)
    _learned: dict[str, dict[str, str]] = field(default_factory=dict)
    misses: list[tuple[str, str]] = field(default_factory=list)  # (field, raw) for the eval set

    def _vocab(self, field_name: str) -> list[str]:
        entry = self._maps.get(field_name, {})
        vocab = entry.get("vocab", [])
        return list(vocab) if isinstance(vocab, list) else []

    def _lookup(self, field_name: str, key: str) -> str | None:
        entry = self._maps.get(field_name, {})
        table = entry.get("map", {})
        if isinstance(table, dict) and key in table:
            return table[key]
        return self._learned.get(field_name, {}).get(key)

    def canonicalize(self, field_name: str, raw: str | None) -> Fact[str]:
        """Canonicalize one raw category string to its clean value, frozen into the snapshot.

        ``raw is None`` → an EMPTY fact (nothing stated), not absent. A map hit →
        ``CANONICAL_MAP``. A miss handed to the fallback → ``CANONICAL_AI`` (with confidence) and
        learned back. A miss the fallback can't answer → ``UNMAPPED`` (recorded, never silent).
        """
        if raw is None or not raw.strip():
            return Fact[str](value=None, source=None)
        key = _normalize(raw)

        mapped = self._lookup(field_name, key)
        if mapped is not None:
            return Fact.present(mapped, source=FactSource.CANONICAL_MAP)

        answer = self.fallback.classify(field_name, raw, self._vocab(field_name))
        if answer is not None:
            self._learned.setdefault(field_name, {})[key] = answer.canonical  # learn (in-run)
            return Fact.present(
                answer.canonical, source=FactSource.CANONICAL_AI, confidence=answer.confidence
            )

        # No answer — flag it (never silently ignore); LP-120's AI seam will resolve these.
        self.misses.append((field_name, raw))
        return Fact[str](value=None, source=FactSource.UNMAPPED)
