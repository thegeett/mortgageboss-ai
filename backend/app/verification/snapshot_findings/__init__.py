"""Snapshot-based AI cross-source findings (LP-586).

DISTINCT FROM `app/services/cross_source.py`, and deliberately so. That pass (LP-78) assembles its
context from the LIVE DATABASE — `_stated_borrowers(db, …)`, `_verified_documents(db, …)` — a
substrate that is rebuilt on every run from mutable tables. Stabilising it meant hashing the
assembled context AND every version-controlled file under `app/verification/`, so any engine edit
invalidated everything even when the file itself had not moved.

This pass reads the SNAPSHOT: one frozen, already-persisted artifact that is the same bytes on every
run until the file genuinely changes. That makes the stability question tractable — hash the
snapshot's content, reuse the previous answer when it matches, and the tab stops moving under a
processor's feet.
"""
