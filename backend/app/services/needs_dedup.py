"""Needs consolidation (LP-111) — deterministic collapse + AI-flagged residue.

One real situation multiplied into 3-4 needs: a single fact became TWO findings (an ``obligation``
+ a ``discrepancy_candidate``), each finding implied a suggestion (LP-67), and the AI reasoner
(LP-69) independently free-formed more needs citing the same fact — with ``needs_type=null`` and
reworded wording every run, so the old exact-title dedup let them accumulate.

This consolidates duplicates in three layers, safest first. **THE DISCIPLINE: never SILENTLY delete
a need.** A duplicate is a minor annoyance; a wrongly-dropped need is a major failure (a required
document never gets collected → the file goes to the lender incomplete). So we UNDER-merge: the
deterministic layers merge only the CERTAIN cases, and the AI layer only FLAGS the rest for the
processor to confirm.

  1. **Collapse-by-source** (certain) — two PROPOSED needs of the SAME ``needs_type`` that share a
     source FINDING are the same ask (the LP-67 suggestion + the LP-69 proposal for one finding).
     Merge deterministically. (Same idea as ``ingest_suggested_need``'s per-finding idempotency.)
  2. **Substance-identity** (certain) — reuse the findings' LP-93 normalization (NFKC + case-fold +
     dash/quote + whitespace) so wording that differs only cosmetically collapses. REPLACES the old
     exact-``.lower()`` title match that let punctuation/case variants through.
  3. **AI flag** (residue, never deletes) — a genuinely-reworded duplicate the deterministic layers
     can't be SURE of (different words, ``needs_type=null``) is only FLAGGED as ``duplicate_of_id``
     for the processor to confirm or dismiss. See :func:`flag_possible_duplicates`.

**Safety boundary:** only a ``PROPOSED`` + ``PENDING`` need is eligible to be MERGED AWAY (the
loser). A confirmed / waived / adjusted / received need (one the processor acted on, or with a
document attached) is a fixed point — never merged away, though a proposed duplicate may merge INTO
it. Merges preserve provenance: the survivor keeps the UNION of both needs' ``source_facts`` (LP-110).
"""

import json
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.client import AIClientError, complete
from app.ai.parsing import extract_json_object
from app.ai.prompt_loader import load_prompt
from app.core.config import settings
from app.models.base import utcnow
from app.models.helpers import only_active
from app.models.needs_item import NeedsItem, NeedsItemDisposition, NeedsItemStatus
from app.services.finding_identity import normalize_text

logger = structlog.get_logger(__name__)

_FLAG_PROMPT_PATH = "needs/needs_dedup_flag.txt"
_FLAG_MAX_TOKENS = 1024


# --------------------------------------------------------------------------- #
# Keys the deterministic layers group on
# --------------------------------------------------------------------------- #


def finding_refs(need: NeedsItem) -> set[str]:
    """The source findings a need traces to (LP-110) — its ``source_finding_id`` + any ``finding``
    refs cited in ``source_facts``. The collapse-by-source key."""
    refs: set[str] = set()
    if need.source_finding_id is not None:
        refs.add(str(need.source_finding_id))
    for fact in need.source_facts or []:
        if fact.get("kind") == "finding" and fact.get("ref"):
            refs.add(str(fact["ref"]))
    return refs


def _intent_key(need: NeedsItem) -> str:
    """The need's intent — its ``needs_type``, normalized. Empty for a free-form (null-type) need."""
    return normalize_text(need.needs_type or "")


def substance_identity(need: NeedsItem) -> tuple[str, str]:
    """The normalized-substance identity ``(intent, title)`` (LP-111, reusing LP-93 normalization).

    Two needs with the same identity are the same ask worded with only cosmetic differences (case /
    dash / whitespace). Deterministic + textual only — NO fuzzy matching (semantically-reworded
    variants stay distinct and go to the AI flag). Conservative by design.
    """
    return (_intent_key(need), normalize_text(need.title))


def _is_merge_candidate(need: NeedsItem) -> bool:
    """Only an untouched PROPOSED + PENDING need may be merged AWAY (the safety boundary).

    A confirmed / waived / adjusted / received need (processor-acted, or with a document attached)
    is a fixed point — never dropped by consolidation.
    """
    return (
        need.disposition is NeedsItemDisposition.PROPOSED and need.status is NeedsItemStatus.PENDING
    )


def _survivor_key(need: NeedsItem) -> tuple[bool, bool, int]:
    """Higher sorts as the better survivor: an acted-on need beats a proposal; a typed need beats a
    free-form one; more source facts beats fewer. Ties broken by created_at (earliest) at the call
    site for stability."""
    acted = not _is_merge_candidate(need)
    return (acted, need.needs_type is not None, len(need.source_facts or []))


# --------------------------------------------------------------------------- #
# Union-find over the deterministic merge rules
# --------------------------------------------------------------------------- #


class _DSU:
    """Tiny union-find keyed by need id."""

    def __init__(self) -> None:
        self._parent: dict[UUID, UUID] = {}

    def find(self, x: UUID) -> UUID:
        self._parent.setdefault(x, x)
        root = x
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[x] != root:  # path-compress
            self._parent[x], x = root, self._parent[x]
        return root

    def union(self, a: UUID, b: UUID) -> None:
        self._parent[self.find(a)] = self.find(b)


def _deterministic_groups(needs: list[NeedsItem]) -> list[list[NeedsItem]]:
    """Group needs the deterministic layers are CERTAIN are the same (collapse-by-source +
    substance-identity), via union-find. Returns only the multi-need groups."""
    dsu = _DSU()
    for need in needs:
        dsu.find(need.id)  # register even singletons

    # Layer 1 — collapse-by-source: same intent (non-empty) AND a shared source finding.
    by_source_intent: dict[tuple[str, str], UUID] = {}
    for need in needs:
        intent = _intent_key(need)
        if not intent:
            continue  # a free-form need can't be CERTAIN by source alone → leave for the AI flag
        for ref in finding_refs(need):
            key = (intent, ref)
            if key in by_source_intent:
                dsu.union(need.id, by_source_intent[key])
            else:
                by_source_intent[key] = need.id

    # Layer 2 — substance-identity: cosmetically-identical (intent, title).
    by_identity: dict[tuple[str, str], UUID] = {}
    for need in needs:
        identity = substance_identity(need)
        if identity in by_identity:
            dsu.union(need.id, by_identity[identity])
        else:
            by_identity[identity] = need.id

    grouped: dict[UUID, list[NeedsItem]] = {}
    for need in needs:
        grouped.setdefault(dsu.find(need.id), []).append(need)
    return [g for g in grouped.values() if len(g) > 1]


# --------------------------------------------------------------------------- #
# Merge
# --------------------------------------------------------------------------- #


def _merge_source_facts(
    survivor: list[dict[str, Any]] | None, loser: list[dict[str, Any]] | None
) -> list[dict[str, Any]] | None:
    """Union two needs' ``source_facts`` (LP-110), de-duped by (kind, label, ref), survivor first."""
    combined: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for fact in [*(survivor or []), *(loser or [])]:
        key = (str(fact.get("kind")), str(fact.get("label")), str(fact.get("ref")))
        if key in seen:
            continue
        seen.add(key)
        combined.append(fact)
    return combined or None


def _merge_into(survivor: NeedsItem, loser: NeedsItem) -> None:
    """Fold ``loser`` into ``survivor`` and soft-delete the loser (LP-111).

    Preserves provenance: the survivor gains the union of both ``source_facts`` and keeps a source
    finding if it lacked one. The loser is SOFT-deleted (recoverable / audited), not hard-removed.
    Caller must have verified ``loser`` is a merge candidate.
    """
    survivor.source_facts = _merge_source_facts(survivor.source_facts, loser.source_facts)
    if survivor.source_finding_id is None and loser.source_finding_id is not None:
        survivor.source_finding_id = loser.source_finding_id
    loser.deleted_at = utcnow()


def consolidate_needs(needs: list[NeedsItem]) -> list[tuple[NeedsItem, NeedsItem]]:
    """Deterministically merge the CERTAIN duplicate needs among ``needs`` (LP-111 layers 1+2).

    Merges only where a duplicate is a PROPOSED + PENDING candidate; a confirmed / received need is
    never dropped (it becomes the survivor). Mutates the needs in place (soft-deletes losers, unions
    provenance onto survivors). Returns the (survivor, loser) pairs merged. Pure of I/O — the caller
    owns the session/flush.
    """
    merged: list[tuple[NeedsItem, NeedsItem]] = []
    for group in _deterministic_groups(needs):
        # Survivor = best-ranked; ties → earliest created (stable). Losers = the rest.
        ordered = sorted(group, key=lambda n: (_survivor_key(n), _neg_created(n)), reverse=True)
        survivor = ordered[0]
        for loser in ordered[1:]:
            if not _is_merge_candidate(loser):
                continue  # never drop an acted-on need (under-merge; both survive)
            _merge_into(survivor, loser)
            merged.append((survivor, loser))
    return merged


def _neg_created(need: NeedsItem) -> float:
    """Earliest-created sorts as the better survivor (stable). ``None`` created_at sorts last."""
    return -need.created_at.timestamp() if need.created_at is not None else float("-inf")


# --------------------------------------------------------------------------- #
# Layer 3 — the AI flag (surfaces; never deletes)
# --------------------------------------------------------------------------- #


async def consolidate_and_flag(db: AsyncSession, *, loan_file_id: UUID) -> int:
    """Run the full LP-111 consolidation for a file: deterministic merge, then the AI flag pass.

    Loads the file's active needs, deterministically merges the certain duplicates
    (:func:`consolidate_needs`), flushes, then runs the AI flag pass over the residue
    (:func:`flag_possible_duplicates`). Best-effort; the caller owns the transaction. Returns the
    number of needs newly flagged as possible duplicates. Runs under the caller's per-file lock.
    """
    needs = list(
        (
            await db.scalars(
                only_active(
                    select(NeedsItem).where(NeedsItem.loan_file_id == loan_file_id), NeedsItem
                )
            )
        ).all()
    )
    merged = consolidate_needs(needs)
    if merged:
        await db.flush()
        logger.info("needs_consolidated", loan_file_id=str(loan_file_id), merged=len(merged))
    return await flag_possible_duplicates(db, loan_file_id=loan_file_id)


async def confirm_duplicate_merge(db: AsyncSession, *, need: NeedsItem) -> NeedsItem | None:
    """Processor CONFIRMS an AI-flagged duplicate (LP-111): merge ``need`` into its flagged twin.

    ``need`` (the flagged possible-duplicate) is folded into ``duplicate_of_id`` (the survivor,
    same file) — provenance unioned, ``need`` soft-deleted. Returns the survivor, or ``None`` if the
    twin is gone (in which case the stale flag is cleared and ``need`` kept — never a silent drop).
    Uses ``flush``; the caller owns the transaction + tenant scope.
    """
    if need.duplicate_of_id is None:
        return None
    survivor = await db.scalar(
        only_active(
            select(NeedsItem).where(
                NeedsItem.id == need.duplicate_of_id,
                NeedsItem.loan_file_id == need.loan_file_id,  # same file (tenant safety)
            ),
            NeedsItem,
        )
    )
    if survivor is None:  # twin removed → clear the stale flag, keep the need (never silent-drop)
        need.duplicate_of_id = None
        need.duplicate_reviewed = True
        await db.flush()
        return None
    _merge_into(survivor, need)
    await db.flush()
    return survivor


async def dismiss_duplicate_flag(db: AsyncSession, *, need: NeedsItem) -> NeedsItem:
    """Processor says "NOT a duplicate — keep both" (LP-111): clear the flag and mark it reviewed so
    the AI pass never re-flags this pair. Uses ``flush``."""
    need.duplicate_of_id = None
    need.duplicate_reviewed = True
    await db.flush()
    return need


async def _load_flaggable(db: AsyncSession, loan_file_id: UUID) -> list[NeedsItem]:
    """The proposed, pending, not-yet-reviewed, not-yet-flagged needs the AI pass may consider."""
    rows = (
        await db.scalars(
            only_active(
                select(NeedsItem).where(
                    NeedsItem.loan_file_id == loan_file_id,
                    NeedsItem.disposition == NeedsItemDisposition.PROPOSED,
                    NeedsItem.status == NeedsItemStatus.PENDING,
                    NeedsItem.duplicate_reviewed.is_(False),
                    NeedsItem.duplicate_of_id.is_(None),
                ),
                NeedsItem,
            )
        )
    ).all()
    return list(rows)


def _parse_duplicate_groups(text: str, valid_ids: set[str]) -> list[tuple[str, list[str]]]:
    """Parse ``{"duplicate_groups": [{"primary_id", "duplicate_ids": [...]}]}`` defensively.

    Keeps only ids in ``valid_ids`` (never invents / cross-file), drops a primary that appears as its
    own duplicate, and returns (primary_id, [duplicate_ids]) with at least one duplicate each.
    """
    snippet = extract_json_object(text)
    if snippet is None:
        return []
    try:
        payload: Any = json.loads(snippet)
    except (json.JSONDecodeError, ValueError):
        return []
    groups = payload.get("duplicate_groups") if isinstance(payload, dict) else None
    if not isinstance(groups, list):
        return []
    out: list[tuple[str, list[str]]] = []
    for group in groups:
        if not isinstance(group, dict):
            continue
        primary = group.get("primary_id")
        dups = group.get("duplicate_ids")
        if not isinstance(primary, str) or primary not in valid_ids:
            continue
        if not isinstance(dups, list):
            continue
        clean = [d for d in dups if isinstance(d, str) and d in valid_ids and d != primary]
        if clean:
            out.append((primary, clean))
    return out


async def flag_possible_duplicates(db: AsyncSession, *, loan_file_id: UUID) -> int:
    """AI pass (LP-111 layer 3): FLAG likely-semantic-duplicate proposed needs for processor review.

    Runs AFTER the deterministic layers, over the residue they couldn't be sure of. It NEVER deletes
    or merges — it only sets ``duplicate_of_id`` (a "possible duplicate of …" flag the processor
    confirms or dismisses). Conservative: high-confidence flags only; when unsure it flags nothing.
    Gated by ``settings.needs_duplicate_flagging_enabled``. Best-effort — never raises (a failed or
    disabled pass simply flags nothing). Uses the cheaper classification model. Uses ``flush``.

    Returns the number of needs newly flagged.
    """
    if not settings.needs_duplicate_flagging_enabled:
        return 0
    candidates = await _load_flaggable(db, loan_file_id)
    if len(candidates) < 2:
        return 0

    by_id = {str(n.id): n for n in candidates}
    listing = [
        {
            "id": str(n.id),
            "needs_type": n.needs_type,
            "title": n.title,
            "reasoning": (n.reasoning or "")[:300],
        }
        for n in candidates
    ]
    system_prompt = load_prompt(_FLAG_PROMPT_PATH)
    user_content = "Here are the file's outstanding proposed needs as JSON:\n\n" + json.dumps(
        {"needs": listing}
    )
    try:
        result = await complete(
            model=settings.anthropic_model_classification,  # cheap — a comparison, not reasoning
            system=system_prompt,
            messages=[{"role": "user", "content": user_content}],
            max_tokens=_FLAG_MAX_TOKENS,
        )
    except AIClientError:
        logger.warning("needs_duplicate_flag_ai_failed", loan_file_id=str(loan_file_id))
        return 0

    flagged = 0
    for primary_id, dup_ids in _parse_duplicate_groups(result.text, set(by_id)):
        for dup_id in dup_ids:
            need = by_id[dup_id]
            if need.duplicate_of_id is not None:
                continue  # already pointed somewhere this pass
            need.duplicate_of_id = by_id[primary_id].id
            flagged += 1
    if flagged:
        await db.flush()
        logger.info("needs_duplicates_flagged", loan_file_id=str(loan_file_id), flagged=flagged)
    return flagged
