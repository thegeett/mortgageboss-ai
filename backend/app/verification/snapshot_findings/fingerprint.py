"""What makes a snapshot-based AI pass STABLE across runs (LP-586).

An AI pass is non-deterministic: ask twice about the same file and the wording moves, the ordering
moves, and a finding can appear or vanish. To a processor that reads as though the FILE changed —
and a count that drifts for no reason teaches people to stop reading the tab at all.

Stability therefore cannot come from prompting. It comes from NOT ASKING AGAIN: hash what the model
would see and reuse the previous answer verbatim while the hash holds. The finding-prose cache
(LP-527) makes the same argument for the same reason.

THE PER-RUN FIELDS MUST BE EXCLUDED, AND THAT IS THE WHOLE TRICK. `run_id` is a fresh UUID and
`created_at` a fresh timestamp on EVERY run, so hashing the snapshot as-is would produce a new
fingerprint every time, the cache would never hit, and the feature would look implemented while
being inert.

AND NOTE WHAT IS *NOT* HASHED: the engine. `app/services/cross_source.py` folds
`engine_fingerprint()` — every version-controlled file under `app/verification/` — into its key,
because it reasons over live tables and cannot tell which engine version produced them. This pass
does not need to: engine changes that MATTER reach it through the snapshot itself, since the tags
and calculations it reads are the engine's own output. A recipe change that moves a tag moves the
snapshot and misses the cache; a change that moves nothing a snapshot records is, correctly, not a
reason to re-ask the model about an unchanged file. That is the difference the snapshot substrate
buys, and it is the reason this pass can be stable where the older one could not.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.verification.snapshot.model import Snapshot

# Fields that differ on every run WITHOUT the file differing. Excluded by NAME rather than by a
# positive allow-list of content, so a NEW content section counts as content automatically — the safe
# default, because a missed content field means a stale answer served against a changed file.
_PER_RUN_FIELDS = ("run_id", "created_at")

# Bumped when the prompt or the finding schema changes, so a reworded question re-asks rather than
# serving an answer to the previous one. The snapshot cannot capture this — it is not in the file.
PROMPT_VERSION = 1


def snapshot_fingerprint(snapshot: Snapshot) -> str:
    """A stable hash of everything the pass reasons over, plus the prompt version.

    Two runs over an unchanged file produce the same value. Any change to the stated facts, the
    documents, the calculations or the tags — or to the prompt — produces a different one.
    """
    payload: dict[str, Any] = snapshot.model_dump(mode="json")
    for field in _PER_RUN_FIELDS:
        payload.pop(field, None)
    # sort_keys so dict iteration order can never move the hash. The snapshot's ORDERED collections
    # (documents, transactions) keep their order, which is content: a reordered document list is a
    # different file to a reader.
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(f"v{PROMPT_VERSION}\0{blob}".encode()).hexdigest()
