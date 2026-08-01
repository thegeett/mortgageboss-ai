"""Stable, run-independent content-ids for raw snapshot facts (LP-312, ADR-251).

Tags (``source_facts``) and findings (``subject_key``) must reference a raw fact by a
STABLE id — one that survives a rebuild. The snapshot is rebuilt from scratch each run,
so array position is NOT stable (a document inserted earlier shifts every later index).
This module derives a content-addressed id instead: same content -> same id, every run.

## The four guarantees

* **Content-derived.** The id is ``prefix + sha256(canonical-content)[:16]`` — a fingerprint
  of the fact's own content. Two facts with identical content hash to the same id; if any
  cited content changes, the id changes (so a dependent tag's cache key changes — §3D).
* **Run-independent / position-independent.** The hash input is the fact's CONTENT, never its
  array index, so extraction order or an inserted/removed sibling elsewhere does not change
  another fact's id.
* **Unique per real fact.** Genuinely-duplicated content (two identical $50 purchases, same
  day + description) would otherwise collide. A deterministic **occurrence tiebreak** (``#0``,
  ``#1`` … among byte-identical siblings) is mixed into the hash so duplicates get DISTINCT
  ids. Because identical siblings are indistinguishable, which physical record receives ``#0``
  vs ``#1`` is immaterial — the *set* of ids is stable across runs either way.
* **Deterministic.** sha256 over a canonical JSON encoding (sorted keys); no randomness, no
  uuid4-per-build.

## PII-at-rest safety (deliberate format choice)

The id is ``<letters><hex>`` with NO internal separator (e.g. ``txna3f90b12…``). In the
serialized snapshot it is one ``\\w`` run beginning with letters, so it can never present a
``\\b\\d{9,}\\b`` match to the persistence guard (a digit run inside it is always bounded by
``\\w`` chars, never a word boundary) — unlike an id like ``txn:123456789`` whose ``:`` would
create a boundary. Content-ids are hashes: they expose none of the hashed content.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

# Hex chars of the digest kept. 64 bits — ample uniqueness within a single snapshot
# (hundreds of facts), and the tiebreak (not entropy) is what separates duplicates.
_ID_LEN = 16

# Letter prefixes make each id a single \w run starting with letters (guard-safe; see
# the module docstring). ``DOC`` scopes a document; ``TXN`` a transaction (under its doc).
DOC_PREFIX = "doc"
TXN_PREFIX = "txn"
# LP-437 — one guard-safe letter prefix for EVERY generic list row (the list name is folded
# into the hashed content, so rows across different lists never collide despite one prefix).
LIST_PREFIX = "lst"


def _canonical(payload: Any) -> str:
    """A stable JSON encoding: sorted keys, no incidental whitespace, deterministic."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def content_fingerprint(payload: Any) -> str:
    """A short deterministic hash of ``payload`` (no prefix, no tiebreak).

    Used to fold one fact's content into another's id — e.g. a document's id includes an
    order-independent fingerprint of its transactions' contents, so two statements that
    differ only in their transactions get different document ids deterministically.
    """
    return hashlib.sha256(_canonical(payload).encode()).hexdigest()[:_ID_LEN]


def unordered_fingerprint(payloads: list[Any]) -> str:
    """An ORDER-INDEPENDENT fingerprint of a collection of contents.

    Hashes the sorted per-item fingerprints, so reordering the collection (e.g. an
    extractor emitting transactions in a different order) does not change the result.
    """
    parts = sorted(content_fingerprint(p) for p in payloads)
    return hashlib.sha256("".join(parts).encode()).hexdigest()[:_ID_LEN]


def assign_content_ids(prefix: str, base_payloads: list[Any]) -> list[str]:
    """Assign a content-id to each payload, with a deterministic duplicate tiebreak.

    Distinct payloads get a pure content hash (position-independent). Byte-identical
    payloads get an incrementing occurrence index folded into the hash so they receive
    DISTINCT ids. Returns one id per input, in input order.
    """
    occurrence: dict[str, int] = {}
    ids: list[str] = []
    for payload in base_payloads:
        canonical = _canonical(payload)
        index = occurrence.get(canonical, 0)
        occurrence[canonical] = index + 1
        digest = hashlib.sha256(f"{canonical}#{index}".encode()).hexdigest()[:_ID_LEN]
        ids.append(f"{prefix}{digest}")
    return ids
