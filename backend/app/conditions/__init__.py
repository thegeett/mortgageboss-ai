"""Condition-sheet domain logic (Phase 4.5).

Pure domain code: the lender code map (LP-910) and, next, the layout readers (LP-906). Nothing here
touches the database, the network or a model — the readers are pure functions over positioned lines,
and the code map is data plus a loader.

WHY THIS IS A PACKAGE AND NOT `services/`. `app/services/` holds code that reads and writes rows;
this holds knowledge about what a lender's sheet MEANS, in the shape `app/documents/catalog.py`
established (ADR-400): app-layer domain knowledge that a ticket can extend in one edit, without a
migration, because it is a property of the world rather than of a loan file.
"""
