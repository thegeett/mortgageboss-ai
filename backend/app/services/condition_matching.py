"""ONE rule for "does this document answer this item" (LP-953, the staging trial's item 6).

Two matchers used to disagree. The plan's `_find_document` required the item's document TYPE and one of
the library's `match_words` in the document's name; arrival linking (`condition_evidence._takes`) checked
the type only. IV-01 (credit report invoice), IV-02 (processing invoice) and IV-03 (inspection invoice)
all take `service_invoice`, so on arrival a processing invoice was linked to the credit-invoice item.

`document_answers` is the comparison both call. What differs between them is passed IN, not recomputed
inside each caller: the plan matches a new item (a dict, no id, nothing she has unlinked yet); arrival
matches stored items and must skip the pairs she unlinked (`unlinked`), the stored fact from
`condition_item_unlinks`. Arrival's extra statement rules (the month, the account) stay in `_takes`,
after this rule has said yes.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.conditions.library import LibraryItem, load_library
from app.models.condition_evidence import ConditionItemUnlink
from app.models.document import Document


def library_item_for(canonical_type_id: str | None, item_key: str | None) -> LibraryItem | None:
    """The library item an item came from. A part (LP-946) has key `<library key>.<performer>`, so the
    base key is the part before the first dot; that relies on no library key containing a dot, which
    `test_lp953_linking.py` pins."""
    library_type = load_library().get(canonical_type_id)
    if library_type is None or not item_key:
        return None
    base = item_key.split(".", 1)[0]
    return next((each for each in library_type.items if each.key == base), None)


def match_words_for(canonical_type_id: str | None, item_key: str | None) -> tuple[str, ...]:
    found = library_item_for(canonical_type_id, item_key)
    return tuple(found.match_words) if found is not None else ()


def document_answers(
    *,
    wanted: Iterable[str] | None,
    match_words: Sequence[str],
    document: Document,
    item_id: UUID | None = None,
    unlinked: set[tuple[UUID, UUID]] | None = None,
) -> bool:
    """Whether `document` answers an item that wants `wanted` types and the library's `match_words`.

    - the document's type is one the item asks for;
    - when the library gives words, one of them is in the document's name (case-insensitive);
    - and she has not unlinked this document from this item (`unlinked`, for a stored item).
    An item that names no type answers nothing automatically: only she can link to it.
    """
    types = set(wanted or ())
    if not types or document.document_type not in types:
        return False
    if match_words:
        name = (document.document_name or "").lower()
        if not any(word.lower() in name for word in match_words):
            return False
    return not (item_id is not None and unlinked and (item_id, document.id) in unlinked)


async def copy_unlinks(
    db: AsyncSession, *, from_item_id: UUID, to_item_id: UUID, company_id: UUID, loan_file_id: UUID
) -> int:
    """Carry her refusals onto an item that REPLACES another (LP-953 review). Returns how many.

    HER "NO" IS KEYED `(item_id, document_id)`, AND TWO FLOWS REPLACE THE ITEM ID while keeping the
    plan: `carry_plan`, when a reworded condition hands its items to its successor, and `update_item`'s
    re-split, which deletes an open part and makes it again. Without this the fact is stranded on an id
    nothing reads, and the next arrival re-links the document she removed — "her choice wins" held
    within a round and failed across a carry.

    The key stays narrow on purpose. A file-wide key (`loan_file_id, item.key, document_id`) would
    survive both flows without this copy, but item keys are unique only within a CONDITION — AS-01 and
    AS-10 both have a `statements` item — so one refusal would suppress the automatic match on an
    unrelated condition. A missed refusal shows itself when the document reappears; a wrong suppression
    never does.
    """
    rows = (
        await db.execute(
            select(ConditionItemUnlink.document_id, ConditionItemUnlink.unlinked_by_user_id).where(
                ConditionItemUnlink.item_id == from_item_id
            )
        )
    ).tuples()
    carried = 0
    for document_id, unlinked_by in rows:
        db.add(
            ConditionItemUnlink(
                company_id=company_id,
                loan_file_id=loan_file_id,
                item_id=to_item_id,
                document_id=document_id,
                unlinked_by_user_id=unlinked_by,
            )
        )
        carried += 1
    return carried


async def unlinked_pairs(db: AsyncSession, *, loan_file_id: UUID) -> set[tuple[UUID, UUID]]:
    """Every `(item, document)` she has unlinked on the file."""
    rows = await db.execute(
        select(ConditionItemUnlink.item_id, ConditionItemUnlink.document_id).where(
            ConditionItemUnlink.loan_file_id == loan_file_id
        )
    )
    return {(item_id, document_id) for item_id, document_id in rows.tuples()}
