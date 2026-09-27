"""Condition schemas (LP-904 shapes; LP-905/907/909 use them).

The read schemas are what the Conditions tab renders. Two rules shape them, both from Stage 0:

* **The lender's wording is carried verbatim and never paraphrased** (ADR-405, spec §9.1). It is
  rendered in serif because it is quoted from a document, and the API is the last place it could be
  quietly "tidied".
* **The status fields arrived in Stage 2, with the moves that earn them** (LP-911). They were
  deliberately ABSENT through Stage 1 (ADR-404): created with defaults in LP-904 and moved by nothing,
  so exposing them would have invited a UI implying otherwise. LP-912 adds the endpoints that move
  them, and LP-911 exposes them because the list, the detail sheet and the summary bar all render
  them. **"Cleared" still means a recorded verdict and nothing else** — that rule moved from "the
  field does not exist" to "the field is only ever set by a verdict", which is where ADR-404 always
  pointed.

`draft_rows` is a parse result awaiting review, not a condition. It is modelled as its own schema
rather than reusing `ConditionPublic` because the two differ in the way that matters: a draft row has
a confidence and the source line numbers it came from, and no identity of its own until import.
"""

# ALIASED, AND `from __future__ import annotations` DOES NOT SUBSTITUTE FOR IT.
#
# `UnderwriterNotePublic` has a field NAMED `date` — the name is the API contract (spec §LP-904:
# `underwriter_notes` is `[{date, text, first_seen_round_id}]`), so it cannot be renamed. Annotated
# with the bare `date`, the class body binds the VALUE first and evaluates the ANNOTATION second, so
# `date = None` lands in the class namespace and `date | None` becomes `None | None`:
# `TypeError: unsupported operand type(s) for |: 'NoneType' and 'NoneType'`, raised on import, every
# time. Nothing imported this module until LP-905's router did, so it shipped in LP-904 and 7964
# tests passed over a module that could not be imported at all.
#
# DEFERRING THE ANNOTATIONS DOES NOT FIX IT, which is the part worth remembering. Pydantic evaluates
# the deferred string with the CLASS namespace as `localns`, and that namespace still holds
# `date = None` — deferral changes WHEN the name resolves, not WHICH namespace wins. The alias does,
# because nothing is ever named `date_type`.
#
# Any field named after its own type hits this. This repo has `date`, `status`, `type` and `id`
# fields throughout.
from collections.abc import Callable
from datetime import date as date_type
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

import structlog
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.models.condition import (
    BucketKind,
    Condition,
    ConditionLenderStatus,
    ConditionOrigin,
    ConditionPrepStatus,
    OwnerHint,
    OwnerHintSource,
)
from app.models.condition_event import ConditionEvent, ConditionEventKind
from app.models.condition_round import (
    ConditionRound,
    ConditionRoundCompleteness,
    ConditionRoundStatus,
    ConditionSheetFormat,
    ConditionSourceKind,
)

#: The paste endpoint's ceiling (spec §LP-907). Enforced here so an oversized body is refused before
#: it reaches a reader, rather than after.
MAX_PASTE_CHARS = 100_000

#: The reparse window is NOT declared here. It belongs with the parse time limits it is derived
#: from — `app/conditions/limits.py` — because a schema module importing from `app/tasks/` would
#: invert the direction this repo's imports run.


class ConditionSort(StrEnum):
    """How the conditions list is ordered (spec §LP-911).

    It lives with the schemas because it is the WIRE CONTRACT — a query parameter the client sends —
    and `services/conditions.py` imports it from here, the same direction `condition_import.py`
    already reads `DraftRowPublic`.

    `SHEET` is the default and is what `list_conditions` has always done: `sequence`, then
    `created_at`. `sequence` is "its order on the latest sheet it appeared on", so sheet order is the
    order the processor sees in the lender's own portal — and only a FULL round moves it, which is the
    correction LP-909 §5 had to make after a partial paste renumbered a file.

    `CODE` SORTS AS A STRING, NEVER AS A NUMBER. A lender code keeps its leading zeros because it is
    an identifier printed on a document, not a quantity (ADR-407), so `"0006"` sorts before `"1228"`
    and casting to an int to "fix" the order would be the same silent loss the column type refuses.
    """

    SHEET = "sheet"
    CODE = "code"
    STATUS = "status"
    OWNER = "owner"
    UPDATED = "updated"


class UnderwriterNotePublic(BaseModel):
    """A dated note the underwriter appended inside the condition's text.

    Carried as structure AND left inside `verbatim_text`, deliberately: the lender wrote one string,
    and a UI that showed the note as though it were ours would misattribute it. The structure is what
    lets the review screen render it as a dated chip beside the wording rather than inside it.
    """

    model_config = ConfigDict(from_attributes=True)

    date: date_type | None = None
    text: str
    first_seen_round_id: UUID | None = None


class ConditionSourcePublic(BaseModel):
    """One way a round arrived. A round has a list because a paste can be enriched by its PDF."""

    model_config = ConfigDict(from_attributes=True)

    kind: ConditionSourceKind
    at: datetime | None = None
    document_id: UUID | None = None
    inbound_attachment_id: UUID | None = None
    user_id: UUID | None = None
    #: Whether this arrival stored bytes — the question "can this round still take a PDF" reduces to.
    #:
    #: THE CLIENT COULD NOT ASK THE SERVER'S QUESTION, SO IT ASKED A PROXY (LP-909 review).
    #: `_has_pdf_source` keys on `storage_path` and says why: "it is the BYTES that make a second
    #: attach meaningless. `kind` would need a list of three values kept in step with the enum."
    #: `storage_path` was not serialised, so the round strip maintained exactly that list — holding
    #: only because every bytes-carrying source happens to be written as `pdf_upload` or `email`,
    #: which is a fact about the current writers rather than a rule binding them. A fourth kind that
    #: stores bytes, or a bytes-less forward, would split the two answers silently.
    #:
    #: A BOOLEAN RATHER THAN THE PATH ITSELF. `_storage_path` is server-controlled precisely so a
    #: sender's filename never shapes the storage layout — "a real condition sheet's filename
    #: routinely carries the borrower's surname and the loan number" — and putting it on the wire
    #: would export that layout plus a company and file id to answer a yes/no question. This is the
    #: same fact with nothing extra attached.
    #:
    #: REQUIRED, WITH NO DEFAULT, BECAUSE THE DEFAULT WAS THE BUG (LP-909 review). This shipped as
    #: `= False` and the first version of `from_model` built sources with `model_validate` — a raw
    #: JSONB entry has no `has_bytes` key, so every source silently became `False`, a VALID value
    #: that failed nothing. Fixing that one call site left the MECHANISM in place: this model has
    #: `from_attributes=True`, so the next person who reaches for `model_validate` because it is the
    #: obvious thing gets `False` again with nothing to tell them.
    #:
    #: The asymmetry made it plain — the TypeScript field is required and rejected four stale
    #: fixtures the moment it landed, while this one would have accepted all of them. Now both sides
    #: are required, and `from_source` is the only constructor.
    has_bytes: bool

    @classmethod
    def from_source(cls, source: dict[str, Any]) -> "ConditionSourcePublic":
        """Build from a `sources` entry, deriving `has_bytes` from the stored path.

        Not `model_validate`: the JSONB entry has no `has_bytes` key, and the derivation is the
        whole point — it mirrors `_has_pdf_source` rather than restating its rule somewhere else.
        """
        return cls(
            kind=ConditionSourceKind(source["kind"]),
            at=source.get("at"),
            document_id=source.get("document_id"),
            inbound_attachment_id=source.get("inbound_attachment_id"),
            user_id=source.get("user_id"),
            has_bytes=bool(source.get("storage_path")),
        )


#: A LOGGER IN A SCHEMA MODULE, WHICH IS UNUSUAL HERE AND DELIBERATE. Every other schema in this
#: repo is pure. The alternative is dropping a writer's drift in silence: a count stored as a string
#: renders as a blank history line and nobody learns the writer changed shape. Flagged as a judgement
#: rather than a mechanical fix (LP-909 review).
log = structlog.get_logger(__name__)

#: Every reader that can appear in a `ROUND_PARSED` detail. A CLOSED vocabulary, because the field is
#: exposed and an open string is a hole — see `ConditionEventPublic`.
#:
#: `"paste"` WAS IN HERE AND NOTHING WRITES IT (LP-909 review). `reader_for` returns `uwm`,
#: `champions` or `generic`; `read_pasted_text` returns one of those two; the split task writes
#: `split`. So the set carried a member no writer produces — added in the very commit that removed
#: three exposed fields no sentence read. ADR-404's shape in miniature, on a frozenset instead of an
#: enum: a vocabulary entry nothing writes is an invitation, and it reads as evidence that some path
#: emits it.
_READERS = frozenset({"uwm", "champions", "generic", "split"})


class VerdictSourceKind(StrEnum):
    """Where the lender said it (ADR-408). Part of a verdict, and a verdict requires one.

    IT IS DEFINED UP HERE, ABOVE EVERY MODEL THAT NAMES IT, AND IT HAS NOW MOVED TWICE. The first
    attempt put it with the request bodies at the foot of the file and `VerdictPublic` raised
    `NameError` on import; LP-916 then annotated it on `ConditionEventPublic`, three hundred lines
    higher, and raised the identical error again. That is the same trap `ConditionSummaryPublic` hit
    against `ConditionRoundPublic` earlier in this same feature — three times in one module, so it is
    worth stating as a rule rather than a war story: **an annotation is evaluated when the class body
    runs, so in this file a type must appear above every model that names it.** It is placed beside the
    module's other vocabularies, where the next model to need it will already be below it.

    IT IS NOT A DATABASE ENUM, because a verdict lives in a JSONB column — so there is no CHECK to swap
    and nothing for `test_activity_type_migrations.py` to watch. It IS a wire contract: the client sends
    it and the detail sheet renders it ("Cleared · portal · 09/12/2026"), so it is mirrored in
    `frontend/lib/types/conditions.ts` and registered in `_MIRRORED`.

    THE TWO DERIVED SOURCES ARE NOT INTERCHANGEABLE WITH THE THREE A PERSON PICKS.
    `round_comparison` and `underwriter_note` are produced by the app — the first when a processor
    confirms a "probably cleared" suggestion, the second when the lender's own dated note reopens a
    condition — and both carry a `round_id` naming the sheet that showed it. The three a processor picks
    by hand carry no round, because a portal screen is not a sheet.

    `underwriter_note` IS ALSO WHAT `came_back` KEYS ON. A manual "Came back" recorded from a phone
    call is `not_cleared` and is NOT a came-back, which is the distinction S2-08's amber rail draws.

    IT SHARES `email` WITH `ConditionSourceKind`, WHICH IS WHY THE TWO ARE PROJECTED SEPARATELY. See
    `_VERDICT_SOURCE_KINDS` immediately below.
    """

    PORTAL = "portal"
    EMAIL = "email"
    PHONE = "phone"
    ROUND_COMPARISON = "round_comparison"
    UNDERWRITER_NOTE = "underwriter_note"


#: The kinds whose writers store a VERDICT's source under `detail["source_kind"]`.
#:
#: A KEY NAME IS NOT ENOUGH, AND `email` IS THE PROOF. `ConditionSourceKind` (how a round arrived)
#: and `VerdictSourceKind` (where the lender said it) BOTH contain `email`, and both are written to
#: the same `source_kind` key by different writers. Without this set, a `condition_verdict_recorded`
#: carrying `source_kind: "email"` would satisfy the round-level field too, and the history would
#: render a lender's emailed answer as though a condition sheet had been forwarded to us.
#:
#: `condition_reopened` is ABSENT on purpose: it stores `overruled_source_kind`, a different key,
#: because it describes the verdict it undid rather than one it is making.
_VERDICT_SOURCE_KINDS = frozenset(
    {ConditionEventKind.CONDITION_VERDICT_RECORDED, ConditionEventKind.CONDITION_CAME_BACK}
)

#: The only kind that stores how a ROUND arrived. Guarded for the same reason, in the other
#: direction: `ROUND_RECEIVED` is the sole writer of a `ConditionSourceKind`.
_ROUND_SOURCE_KINDS = frozenset({ConditionEventKind.ROUND_RECEIVED})


def _logged_mismatch(kind: object, key: str, expected: str) -> None:
    """Report that a writer stored the wrong shape — by KEY NAME, never by value.

    THE NAME AND NOTHING ELSE. `detail` is NPI-capable, so logging the value to explain a type
    mismatch would put the lender's text in the log line to complain about its type. The key and the
    event kind are enough to find the writer.
    """
    log.warning(
        "condition_event_detail_shape",
        event_kind=str(kind),
        detail_key=key,
        expected=expected,
    )


def _as_int(value: object, *, kind: object = None, key: str = "") -> int | None:
    """An int from `detail`, or None — never a coercion and never a raise.

    `detail` is free-form JSONB written by fifteen different `ConditionEvent(...)` constructions. A
    history panel must not 500 because one of them stored a string where this reads a count, and a
    coerced `"6"` → 6 would be this layer inventing agreement the writers have not made.

    `bool` IS EXCLUDED EXPLICITLY BECAUSE `True` IS AN `int` IN PYTHON. Without that check a flag
    stored under a count's key renders as the number 1.

    A PRESENT key of the wrong type is logged, because silence there is the failure mode: the line
    renders blank and nobody learns the writer drifted (LP-909 review).
    """
    if isinstance(value, bool) or not isinstance(value, int):
        if value is not None and key:
            _logged_mismatch(kind, key, "int")
        return None
    return value


def _as_bool(value: object, *, kind: object = None, key: str = "") -> bool | None:
    """A bool from `detail`, or None. `1` is not `True` here, for the same reason as above."""
    if not isinstance(value, bool):
        if value is not None and key:
            _logged_mismatch(kind, key, "bool")
        return None
    return value


def _as_date(value: object, *, kind: object = None, key: str = "") -> date_type | None:
    """A date from `detail`, or None — never a raise and never today.

    THE LENDER'S DATE IS THE WHOLE POINT OF THE FIELD IT READS. `verdict_source_date` is when the
    LENDER said it, so a value this cannot parse becomes None rather than falling back to the import's
    clock: a history line that silently dated a verdict by our own day would be the exact claim
    ADR-408 refuses to let the schema make.

    A PRESENT key of the wrong shape is logged by name, like its siblings, because a line that simply
    renders without its date teaches nobody that a writer drifted.
    """
    if not isinstance(value, str):
        if value is not None and key:
            _logged_mismatch(kind, key, "date")
        return None
    try:
        return date_type.fromisoformat(value)
    except ValueError:
        if key:
            _logged_mismatch(kind, key, "date")
        return None


def _as_vocab[T](value: object, allowed: frozenset[str], build: Callable[[str], T]) -> T | None:
    """A value from a CLOSED vocabulary, or None. Anything unrecognised does not travel.

    THIS IS THE FIX FOR A HOLE THE ALLOW-LIST DID NOT CLOSE (LP-909 review). Projecting named keys
    stops an unexpected KEY reaching the client and does nothing about an unexpected VALUE — so
    `detail={"reader": "Alex Rivera"}` would have passed straight through a key that is on the list,
    and the NPI test stayed green because it only ever put text under keys that were NOT.

    Every string this schema exposes is drawn from a fixed set the writers choose from: an enum value,
    or one of five reader names. Refusing anything outside that set turns "no writer does this today"
    into "no writer can".
    """
    if not isinstance(value, str) or value not in allowed:
        return None
    try:
        return build(value)
    except ValueError:  # pragma: no cover — `allowed` already gates this
        return None


class ConditionEventPublic(BaseModel):
    """One thing that happened to a round — the history on screen S1-09.

    NAMED SCALARS, NEVER `detail` ITSELF, AND THIS IS THE WHOLE DESIGN OF THE SCHEMA.
    `ConditionEvent.detail` is classified NPI: the round model calls it "what changed, which is the
    lender's text", `readonly.condition_events` drops it whole rather than scrubbing it, and
    `condition_import.py` states the rule at its own write site — "WHAT CHANGED, NOT THE WORDING".
    Passing the dict through would export a column the readonly layer deliberately refuses, through a
    door built for a history panel.

    AND THE KEYS ARE NOT ENOUGH — THE VALUES ARE CLOSED TOO. The first version projected named keys
    as open `str`, which stops an unexpected KEY arriving and does nothing about an unexpected VALUE:
    `detail={"reader": "Alex Rivera"}` would have travelled through a key that IS on the list. The NPI
    test passed only because it put text under keys that were not. Every string exposed here is now
    drawn from a fixed vocabulary — an enum value, or one of `_READERS` — and anything outside it
    becomes None (LP-909 review).

    AND THE SET IS AS SMALL AS THE SCREEN NEEDS. `reader_version`, `duplicates_dropped` and
    `filled_from` were projected and read by nothing: `historyLine` never touches them. Three open
    doors serving no sentence. `filled_from` was also mis-documented as "on an enrich" — it is written
    once, on `CONDITION_EDITED` (`condition_enrich.py:273`), and `ROUND_ENRICHED` stores no such key,
    so the arm that would have used it could never have seen it.

    What the FOURTEEN `ConditionEvent(...)` constructions actually store, of what is exposed —
    `condition_import` 6, `condition_rounds` 4, `condition_enrich` 3, `tasks/conditions` 1:

    * receipt: `source_kind` always, plus `bytes` on an UPLOAD and `chars` on a PASTE (neither of
      those two is exposed); a MANUAL round stores `source_kind` alone.
    * parse: `reader`, `rows`.
    * import: `round_number`, `rows`, `created`, `seen_again`.
    * reparse: `from_status`.
    * enrich: `filled_header`, `filled_expiry`, `matched` — and NOT `filled_date_printed`, which is on
      `ConditionEnrichResult` but not in the event's detail.
    * discard: `rows`.

    AN EARLIER VERSION OF THIS PARAGRAPH GOT THREE OF THOSE WRONG (LP-909 review): it said fifteen
    constructions from a grep I never filtered, put `bytes` on every receipt when a paste stores
    `chars`, and listed `filled_date_printed` as an enrich key while the field comment below correctly
    said it is not stored. A docstring enumerating writers is worth only as much as the count behind
    it, and the last one was asserted rather than taken.

    `actor_user_id` IS NULL FOR A SYSTEM EVENT, DELIBERATELY. The model says why: "a parse task has
    no actor, and naming the processor who uploaded the sheet as the actor of the parse would make the
    trail say something untrue." The history must therefore distinguish "the reader did this" from "a
    person did this" rather than attributing everything to whoever touched the round last.

    NO `id`. A history line is not addressable — nothing links to one, and `condition_events` is
    append-only, so there is no update or delete for an id to name. Adding one would invite a caller
    to build a URL for a resource that has no endpoint.
    """

    model_config = ConfigDict(from_attributes=True)

    kind: ConditionEventKind
    occurred_at: datetime
    #: Null for a system event — see the class docstring.
    actor_user_id: UUID | None = None

    #: How the round arrived (`ROUND_RECEIVED`). A CLOSED enum, not a string.
    source_kind: ConditionSourceKind | None = None
    #: Which reader ran (`ROUND_PARSED`) — one of `_READERS`. `"split"` after an AI split.
    reader: str | None = None
    #: How many rows the event concerned — read on a parse, imported on an import, thrown away on a
    #: discard. The three are different facts under one key because the writers named it that way.
    #:
    #: A PASTE'S `ROUND_RECEIVED` HAS NO `rows`. It stores `{source_kind, bytes}`, so the count for
    #: "6 conditions read" comes from the following `ROUND_PARSED`, not from the arrival.
    rows: int | None = None
    #: What an import did (`ROUND_IMPORTED`) — the numbers S1-09's line quotes.
    round_number: int | None = None
    created: int | None = None
    seen_again: int | None = None
    #: What a reparse came back from (`ROUND_REPARSE_REQUESTED`). A CLOSED enum.
    from_status: ConditionRoundStatus | None = None
    #: What an enrich actually did (`ROUND_ENRICHED`), so the line can stop claiming it filled the
    #: letter details when it filled nothing (LP-909 review).
    #: NO `filled_date_printed`. `ConditionEnrichResult` carries one, but the EVENT writer does not
    #: store it (`condition_enrich.py` writes `reader`, `matched`, `added`, `unmatched_existing`,
    #: `filled_header`, `filled_expiry`) — so projecting it would add a field nothing fills, which is
    #: the shape this stage keeps deleting. `added` and `unmatched_existing` are stored and unused by
    #: any sentence, so they stay unprojected for the same reason in reverse.
    filled_header: bool | None = None
    filled_expiry: bool | None = None
    matched: int | None = None

    # --- condition-level scalars (LP-916, screen S2-03) --------------------------------------- #
    #
    # THE ROUND-LEVEL KEYS ABOVE ARE NOT ENOUGH FOR A CONDITION'S HISTORY, and the events route said
    # so in as many words: a condition event arrived carrying `kind`, `occurred_at` and
    # `actor_user_id` and nothing else, because every projected key belongs to a ROUND. S2-03's
    # sentences need what our own LP-912 writers already store.
    #
    # EVERY ONE IS AN ENUM VALUE, A DATE OR AN INT. Nothing here is open text, which is the rule the
    # class docstring sets and the reason `lender_code` is deliberately ABSENT: it is free text off
    # the sheet, and the sheet already knows which condition it is showing.

    #: Our track's move (`CONDITION_PREP_MOVED`, and the consequence recorded on a came-back or a
    #: `not_cleared` verdict). CLOSED enums.
    prep_status_from: ConditionPrepStatus | None = None
    prep_status_to: ConditionPrepStatus | None = None
    #: Who we are waiting on, when a move went TO `waiting` (LP-916 review) — what turns "Moved to
    #: Waiting on someone" into S2-03's "Moved to Waiting on Borrower". A CLOSED enum (`OwnerHint`),
    #: projected for `CONDITION_PREP_MOVED` only.
    waiting_on: OwnerHint | None = None
    #: The lender's track's move, on the three events that state one. CLOSED enums.
    lender_status_from: ConditionLenderStatus | None = None
    lender_status_to: ConditionLenderStatus | None = None
    #: WHERE THE LENDER SAID IT — and NOT under `source_kind`, which is already taken by
    #: `ConditionSourceKind` (how a ROUND arrived: pdf_upload / email / paste / manual). These are two
    #: different closed vocabularies that share the word "source", and reusing the key would let a
    #: value from one arrive in a field typed as the other — the precise hole LP-909's review closed
    #: when it stopped projecting named keys as open `str`.
    verdict_source_kind: VerdictSourceKind | None = None
    #: The date the LENDER said it, never ours. See `_as_date`.
    verdict_source_date: date_type | None = None
    #: How many notes an import added (`CONDITION_NOTE_ADDED`, `CONDITION_CAME_BACK`). A COUNT, never
    #: the notes: the wording is the lender's and is dropped whole from `readonly.condition_events`.
    notes_added: int | None = None
    #: Who did it, resolved from `actor_user_id` by the caller — NOT read from `detail`, which is why
    #: no closed-vocabulary check applies: it comes from our own `users` table. Null for a system
    #: event, deliberately (see the class docstring). Follows `timeline.py`'s existing `actor_name`
    #: rather than inventing a second attribution shape.
    actor_name: str | None = None

    @classmethod
    def from_model(
        cls,
        event: ConditionEvent,
        *,
        actor_name: str | None = None,
        round_number: int | None = None,
    ) -> "ConditionEventPublic":
        """Project the allow-list, with every string drawn from a closed vocabulary.

        `actor_name` AND `round_number` ARE SUPPLIED BY THE CALLER, because neither can be read from
        this row alone. A name lives in `users`, and a condition event's round is `round_id` on the
        event — the import's condition-level writers store `lender_code` and `changed` in `detail`,
        never a round number. Resolving either one per event would be a query per history line, so the
        route resolves both in one go and passes them down.

        `round_number` FALLS BACK TO `detail`, which keeps the ROUND events unchanged: `ROUND_IMPORTED`
        stores its own number and has no `round_id` to resolve.
        """
        detail = event.detail or {}
        kind = event.kind
        prep_values = frozenset(member.value for member in ConditionPrepStatus)
        lender_values = frozenset(member.value for member in ConditionLenderStatus)
        return cls(
            kind=kind,
            occurred_at=event.occurred_at,
            actor_user_id=event.actor_user_id,
            actor_name=actor_name,
            prep_status_from=_as_vocab(
                detail.get("prep_status_from"), prep_values, ConditionPrepStatus
            ),
            prep_status_to=_as_vocab(
                detail.get("prep_status_to"), prep_values, ConditionPrepStatus
            ),
            waiting_on=_as_vocab(
                detail.get("waiting_on"),
                frozenset(member.value for member in OwnerHint),
                OwnerHint,
            )
            if kind is ConditionEventKind.CONDITION_PREP_MOVED
            else None,
            lender_status_from=_as_vocab(
                detail.get("lender_status_from"), lender_values, ConditionLenderStatus
            ),
            lender_status_to=_as_vocab(
                detail.get("lender_status_to"), lender_values, ConditionLenderStatus
            ),
            verdict_source_kind=_as_vocab(
                detail.get("source_kind"),
                frozenset(member.value for member in VerdictSourceKind),
                VerdictSourceKind,
            )
            if kind in _VERDICT_SOURCE_KINDS
            else None,
            verdict_source_date=_as_date(detail.get("source_date"), kind=kind, key="source_date")
            if kind in _VERDICT_SOURCE_KINDS
            else None,
            notes_added=_as_int(detail.get("notes_added"), kind=kind, key="notes_added"),
            # GUARDED BY KIND, NOT JUST BY KEY — see `_ROUND_SOURCE_KINDS`. Both source vocabularies
            # contain `email` and share this key, so without the guard a lender's emailed verdict
            # would also read as a condition sheet arriving by email.
            source_kind=_as_vocab(
                detail.get("source_kind"),
                frozenset(member.value for member in ConditionSourceKind),
                ConditionSourceKind,
            )
            if kind in _ROUND_SOURCE_KINDS
            else None,
            reader=_as_vocab(detail.get("reader"), _READERS, str),
            rows=_as_int(detail.get("rows"), kind=kind, key="rows"),
            # THE CALLER'S VALUE WINS, AND THE `detail` FALLBACK KEEPS THE ROUND EVENTS UNCHANGED:
            # `ROUND_IMPORTED` stores its own number and has no `round_id` to resolve, while a
            # condition event is the exact opposite — `round_id` on the row, no number in `detail`.
            #
            # THE PARAMETER WAS ACCEPTED AND IGNORED IN THE FIRST VERSION OF THIS METHOD. The
            # signature took `round_number`, the docstring above described this very fallback, and the
            # body read only `detail` — so the route resolved a number, passed it in, and every
            # condition event still came back `round_number: null`. Nothing failed: the field was
            # already nullable and the round events were unaffected. A dead parameter that reads as a
            # feature is the same defect `_gate_map` shipped in LP-911, and only a test that asserted
            # the resolved value found either one.
            round_number=round_number
            if round_number is not None
            else _as_int(detail.get("round_number"), kind=kind, key="round_number"),
            created=_as_int(detail.get("created"), kind=kind, key="created"),
            seen_again=_as_int(detail.get("seen_again"), kind=kind, key="seen_again"),
            from_status=_as_vocab(
                detail.get("from_status"),
                frozenset(member.value for member in ConditionRoundStatus),
                ConditionRoundStatus,
            ),
            filled_header=_as_bool(detail.get("filled_header"), kind=kind, key="filled_header"),
            filled_expiry=_as_bool(detail.get("filled_expiry"), kind=kind, key="filled_expiry"),
            matched=_as_int(detail.get("matched"), kind=kind, key="matched"),
        )


class ParseReportPublic(BaseModel):
    """What the reader did — the honest record of a parse, including what it could not place.

    `unassigned_lines` is the invariant spec §9.2 exists for: every non-blank line in the conditions
    block becomes a row, a heading, a known artifact, or an entry here. Nothing is silently dropped,
    and the review screen shows these so a processor can add or ignore each one.
    """

    model_config = ConfigDict(from_attributes=True)

    reader: str | None = None
    reader_version: str | None = None
    warnings: list[str] = Field(default_factory=list)
    unassigned_lines: list[str] = Field(default_factory=list)
    duplicates_dropped: int = 0
    ai_used: bool = False
    #: NOT THE SAME FACT AS `ai_used`, AND THE PAIR IS READ TOGETHER. `needs_ai` is the READER's
    #: verdict that the rules could not split this text; `ai_used` is whether an AI split actually
    #: ran. Both false means the rules read it. `needs_ai` true with `ai_used` false means the round
    #: is waiting for LP-908 — a state that has to be findable, or the gap is invisible to everyone
    #: except whoever reads the warning. Never set merely because a read was imperfect: a sheet with
    #: warnings is still a rule-read sheet.
    needs_ai: bool = False
    #: Set only on PARSE_FAILED — the typed reason, never a bare exception string (spec §9.8).
    failure_kind: str | None = None
    failure_detail: str | None = None


class DraftRowPublic(BaseModel):
    """One parsed row awaiting review. Not yet a condition — it has no identity until import."""

    model_config = ConfigDict(from_attributes=True)

    sequence: int
    lender_code: str | None = None
    lender_category: str | None = None
    bucket_heading: str
    bucket_kind: BucketKind
    verbatim_text: str
    underwriter_notes: list[UnderwriterNotePublic] = Field(default_factory=list)
    owner_hint: OwnerHint = OwnerHint.UNKNOWN
    owner_hint_source: OwnerHintSource = OwnerHintSource.NONE
    processor_assist: bool = False
    #: 1.0 for a row the rules read; 0.6 for an AI split (LP-908). The review screen sorts anything
    #: below 0.8 first and requires the flagged-rows checkbox before import.
    confidence: float = 1.0
    source_line_numbers: list[int] = Field(default_factory=list)


class VerdictPublic(BaseModel):
    """What the lender said, and where — the callout on S2-03 ("Cleared · portal · 09/12/2026").

    IT IS DEFINED ABOVE `ConditionPublic` BECAUSE THAT MODEL ANNOTATES IT. Python evaluates an
    annotation when the class body runs, and LP-912 already learned this the hard way one model over:
    `ConditionSummaryPublic` referencing `ConditionRoundPublic` from above it raised `NameError` on
    import. Order here is mechanical, not stylistic.

    BUILT LENIENTLY FROM JSONB, WHICH IS UNUSUAL IN THIS FILE AND DELIBERATE. `conditions.verdict` is
    written only by `services/condition_status.py`, so the values are ours — but it is still a free-form
    column, and a list of sixty conditions must not 500 because one row was written by an older shape or
    edited by hand on staging. `from_stored` returns `None` for anything it cannot read, which the UI
    already has to handle: most conditions have no verdict at all.

    `source_kind` COMES THROUGH A CLOSED VOCABULARY, and that is load-bearing rather than tidy.
    `ConditionPublic.came_back` branches on it being `underwriter_note`, so an unrecognised string
    coerced to that value would paint the amber "Came back" rail on a condition the lender never
    reopened. Anything outside the enum makes the whole verdict unreadable instead — the same argument
    `ConditionEventPublic` makes for `_as_vocab`, where an open `str` let `{"reader": "Alex Rivera"}`
    through a key that was on the allow-list.

    `note` IS THE PROCESSOR'S OWN, AND IT DOES TRAVEL HERE. It is NPI and stays out of
    `readonly.conditions` (ADR-405), but so does `verbatim_text`, which this same model returns: the
    readonly views are the analytics path, not the API. The processor who typed it is the one reading it
    back.
    """

    model_config = ConfigDict(from_attributes=True)

    status: ConditionLenderStatus
    source_kind: VerdictSourceKind
    #: The date the LENDER said it. Never defaulted to today — that is the point of recording it.
    source_date: date_type
    #: The sheet that showed it, for the two sources the app derives. `None` for portal/email/phone,
    #: because a portal screen is not a sheet.
    round_id: UUID | None = None
    note: str | None = None
    recorded_by: UUID | None = None
    recorded_at: datetime | None = None

    @classmethod
    def from_stored(cls, stored: dict[str, Any] | None) -> "VerdictPublic | None":
        """The row's verdict, or `None` if there is none or it cannot be read.

        A MALFORMED VERDICT IS REPORTED, NOT SWALLOWED SILENTLY. The log line carries the keys and the
        condition is the caller's to identify — never the note, which is what a processor typed. The
        same judgement `_logged_mismatch` above makes: dropping a writer's drift in silence means the
        field renders blank and nobody learns the shape changed.
        """
        if not stored:
            return None
        try:
            return cls.model_validate(stored)
        except ValidationError:
            log.warning("condition_verdict_unreadable", keys=sorted(stored))
            return None


class ConditionPublic(BaseModel):
    """One imported condition, as the list and the detail sheet render it.

    `round_numbers` is what drives the `R1 R2` chips: every round this condition appeared on, derived
    from its CONDITION_CREATED / CONDITION_SEEN_AGAIN events.

    THE STATUS FIELDS ARE HERE AS OF LP-911 — see the module docstring for why they were absent
    before. ONE field below has **no producer yet**, `superseded_by_id`, and ships anyway because its
    final type is already fixed (the FK LP-912 creates), so adding it now changes nothing later.

    `verdict` AND `pending_suggestion` SHIPPED HERE TOO AND WERE TAKEN OUT IN REVIEW. The argument
    for shipping early was "add the key once, not twice", and it did not hold for either: `verdict`
    was `dict[str, Any]`, which LP-912 must replace with a typed verdict anyway, and
    `pending_suggestion` was a sentence, where LP-915's confirm button needs the round it came from.
    A guessed type is the second change, not a saving. Each arrives with its producer.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    lender_code: str | None
    lender_category: str | None
    bucket_heading: str
    bucket_kind: BucketKind
    #: The lender's words. Rendered in serif; never paraphrased anywhere in the stack.
    verbatim_text: str
    underwriter_notes: list[UnderwriterNotePublic] = Field(default_factory=list)
    owner_hint: OwnerHint
    owner_hint_source: OwnerHintSource
    info_only: bool
    canonical_type_id: str | None
    origin: ConditionOrigin
    sequence: int
    first_round_id: UUID
    last_seen_round_id: UUID
    round_numbers: list[int] = Field(default_factory=list)
    created_at: datetime

    #: Both tracks (ADR-404). Ours says what WE are doing; the lender's says what the LENDER said.
    prep_status: ConditionPrepStatus
    lender_status: ConditionLenderStatus

    #: WITHOUT THIS, LP-912's `stale` REFUSAL IS UNREACHABLE. Its writes are optimistic on
    #: `updated_at`, and a client cannot echo a value it was never given — which is exactly how
    #: LP-909 §4 found the draft's 409 could never fire, because `ConditionRoundPublic` carried only
    #: `created_at`. Exposed here so the guard has something to compare.
    updated_at: datetime

    #: The owner the list groups and filters on. `owner_hint` is the sheet's guess; this is the
    #: answer, and LP-912 makes them differ by adding a manual override that wins (A2).
    effective_owner: OwnerHint
    effective_owner_source: OwnerHintSource

    #: The newest dated underwriter note, for the row's chip — the whole list is in
    #: `underwriter_notes`, and this saves every caller re-deriving "newest".
    latest_note: UnderwriterNotePublic | None = None

    #: Whether the lender has answered, or answered "not satisfied". Info-only and superseded
    #: conditions are never open (spec §LP-911).
    is_open: bool
    #: Days since we first saw it. FROM `created_at`, which is when this file first recorded the
    #: condition — not from the round's printed date, which is when the LENDER wrote it. The
    #: distinction is worth keeping: a sheet imported late would otherwise show a condition as open
    #: for longer than it has been ours.
    days_open: int

    #: BROADER THAN ITS NAME UNTIL LP-912, AND SAID SO RATHER THAN LEFT TO READ WRONG. The spec
    #: defines it as "lender status is `not_cleared` **because of an underwriter note**", and which
    #: cause set the status is only knowable from the verdict's `source_kind` — a column LP-912 adds.
    #: Here it is simply "the lender said not satisfied", which is the same set today because nothing
    #: else can produce `not_cleared` yet. LP-912 narrows it.
    came_back: bool

    #: What the lender said and where, or `None` while they have not answered. THE ONLY THING THAT MAY
    #: SET `cleared` OR `waived` (ADR-404, ADR-408), which is why it travels with the row rather than
    #: behind a second request: a screen showing "Cleared" has to be able to say who said so.
    #:
    #: TYPED, HAVING SHIPPED AS `dict[str, Any]` AND BEEN REMOVED FOR IT (LP-911 review, R8). The
    #: argument then was "add the key once so the cross-stack mirror changes once", and it did not
    #: survive the key being the wrong shape — LP-912 had to replace the type anyway. It arrives now
    #: because it now has a producer.
    verdict: VerdictPublic | None = None
    #: Set by LP-915 when the processor confirms a "reworded" pair. Nothing disappears: the replaced
    #: condition stays, struck through, pointing at the one that carries on from it.
    #:
    #: Read from the row as of LP-912, which added the column; it was hard-coded `None` before.
    superseded_by_id: UUID | None = None

    @classmethod
    def from_model(
        cls,
        condition: Condition,
        *,
        effective_owner: OwnerHint,
        effective_owner_source: OwnerHintSource,
        is_open: bool,
        days_open: int,
        round_numbers: list[int] | None = None,
    ) -> "ConditionPublic":
        """Build the public view.

        `round_numbers` is supplied by the caller, which reads the events for the whole list in one
        query rather than per row.

        THE FOUR DERIVED VALUES ARE REQUIRED PARAMETERS, AND THIS SCHEMA DELIBERATELY CANNOT COMPUTE
        THEM. `services/conditions.py` owns `effective_owner`, `effective_owner_source`, `is_open` and
        the day count — the same rules its filters and its summary run on. Two things follow, and both
        are the reason for the awkwardness:

        1. **A schema that re-derived them would be a second statement of each**, free to disagree
           with the very filter that selected the row. A list filtered on `owner=borrower` rendering a
           row whose `effective_owner` says something else is the kind of split nothing fails on.
        2. **This module stays pure.** It already apologises for holding a logger ("a logger in a
           schema module, which is unusual here and deliberate"); importing a SERVICE would be a
           larger inversion, and doing it inside the function body to dodge the import cycle —
           `services/conditions.py` imports `ConditionSort` from here — would leave a trap for whoever
           later moves it to the top of the file, where it becomes a crash on startup.

        Required rather than defaulted so a new caller cannot quietly get a different answer than the
        list does. There are two callers, both in `api/conditions.py`, and both already hold the
        service.
        """
        notes = [
            UnderwriterNotePublic.model_validate(note)
            for note in (condition.underwriter_notes or [])
        ]
        dated = [note for note in notes if note.date is not None]
        verdict = VerdictPublic.from_stored(condition.verdict)
        return cls(
            id=condition.id,
            lender_code=condition.lender_code,
            lender_category=condition.lender_category,
            bucket_heading=condition.bucket_heading,
            bucket_kind=condition.bucket_kind,
            verbatim_text=condition.verbatim_text,
            underwriter_notes=notes,
            owner_hint=condition.owner_hint,
            owner_hint_source=condition.owner_hint_source,
            info_only=condition.info_only,
            canonical_type_id=condition.canonical_type_id,
            origin=condition.origin,
            sequence=condition.sequence,
            first_round_id=condition.first_round_id,
            last_seen_round_id=condition.last_seen_round_id,
            round_numbers=round_numbers or [],
            created_at=condition.created_at,
            prep_status=condition.prep_status,
            lender_status=condition.lender_status,
            updated_at=condition.updated_at,
            effective_owner=effective_owner,
            effective_owner_source=effective_owner_source,
            # NEWEST BY DATE, and undated notes are not candidates: "newest" of a set with no dates
            # would be "whichever the reader happened to store last", which is not a fact about the
            # lender. A condition whose only notes are undated therefore has no `latest_note`, and
            # the chips still show them all.
            latest_note=max(dated, key=lambda note: note.date) if dated else None,  # type: ignore[arg-type,return-value]
            is_open=is_open,
            days_open=days_open,
            verdict=verdict,
            # NARROWED, AS LP-912 SAID IT WOULD BE. The spec defines `came_back` as `not_cleared`
            # **because of an underwriter note**, and which cause set the status is only knowable from
            # the verdict — so until the verdict was projected this could only be the broader "the
            # lender said not satisfied". It now requires both: the status AND a verdict sourced to the
            # note. A manual "Came back" recorded from a phone call is `not_cleared` and is NOT
            # `came_back`, which is the distinction the amber rail on S2-08 is drawing.
            came_back=(
                condition.lender_status is ConditionLenderStatus.NOT_CLEARED
                and verdict is not None
                and verdict.source_kind is VerdictSourceKind.UNDERWRITER_NOTE
            ),
            superseded_by_id=condition.superseded_by_id,
        )


class ConditionRoundAppearancePublic(BaseModel):
    """One round, and whether this condition was on it — the detail sheet's Rounds pills (S2-03).

    "R1 08/28 · on the sheet ✓", "R2 09/10 · full list · not on it —". The three states are NOT two:
    a condition absent from a FULL round is genuinely absent, while a condition absent from a PARTIAL
    one says nothing at all — the processor pasted six lines and did not claim the rest were gone
    (ADR-404). `on_sheet` plus `completeness` is what lets the screen say "not comparable" instead of
    implying a condition was dropped.
    """

    model_config = ConfigDict(from_attributes=True)

    round_id: UUID
    round_number: int | None
    round_date: date_type
    date_printed: date_type | None
    completeness: ConditionRoundCompleteness
    #: How the round FIRST arrived — a closed `ConditionSourceKind`, not NPI (LP-916 review). S2-03's
    #: history reads "Imported from round 1 (PDF upload, printed 08/28)"; `condition_created` stores
    #: neither fact, but the ROUND holds both, and neither is the lender's words: `date_printed` is
    #: already in `readonly.condition_rounds`, and the arrival kind is a closed set. So the sentence
    #: is built from the round, and nothing is projected out of `detail`.
    arrived_as: ConditionSourceKind | None = None
    #: Whether this condition appeared on this round's sheet, from its appearance events — not from
    #: `first_round_id`/`last_seen_round_id`, which cannot express "on R1 and R3 but not R2".
    on_sheet: bool
    #: The notes that arrived IN this round — matched on each note's `first_seen_round_id`, so a
    #: chip appears against the round that actually brought it. A LIST: one sheet can carry two notes
    #: on one condition, and a single field kept only the last of them.
    notes: list[UnderwriterNotePublic] = Field(default_factory=list)


class ConditionDetailPublic(ConditionPublic):
    """One condition with its whole story — the detail sheet (LP-916, read by LP-911's endpoint).

    IT EXTENDS `ConditionPublic` RATHER THAN RESTATING IT, so a field added to the row cannot go
    missing from the sheet. The sheet's Previous/Next walks the same list the row came from, and a
    detail view that carried a different set of fields than the list is how the two come to disagree
    about a status in front of a processor.

    The history is NOT here: it is a separate call (`…/events`), for the reason LP-909 gives about the
    round's history — the condition is fetched whenever the list refreshes, and the history is read
    only when somebody opens one sheet.
    """

    #: Every IMPORTED round on the file, oldest first, each saying whether this condition was on it.
    rounds: list[ConditionRoundAppearancePublic] = Field(default_factory=list)


class LetterChangePublic(BaseModel):
    """One value the lender changed between two sheets — "note rate 6.374% → 6.490%" (S2-06).

    BOTH SIDES ARE OPTIONAL AND A MISSING ONE IS NEVER GUESSED. Round 1's rate lock is genuinely
    blank, so the panel draws "— → 09/30/2026"; inventing a prior value would put a date in front of
    a processor that no sheet ever carried.
    """

    label: str
    old: str | None = None
    new: str | None = None


class RewordedPairPublic(BaseModel):
    """A condition this sheet may have reworded, and the one it created (S2-08).

    TWO IDS, NEVER THE TWO WORDINGS. The screen draws *Was* above *Now*, and it resolves both from
    condition rows it already holds — so this pair carries no word the lender wrote.
    """

    old_id: UUID
    new_id: UUID


class CameBackMovePublic(BaseModel):
    """What a came-back did to OUR track, for S2-08's "our status moved from … back to …"."""

    condition_id: UUID
    prep_status_from: ConditionPrepStatus
    prep_status_to: ConditionPrepStatus


class RoundComparisonPublic(BaseModel):
    """What one import changed, as the panel reads it (S2-06 / S2-07 / S2-08 / S2-10).

    TYPED RATHER THAN A RAW BLOB, following `ParseReportPublic` above. The column is JSONB, but a
    `dict[str, Any]` on the wire would make every count and every id untyped at the boundary the
    frontend generates its own types from — and `reworded` in particular is stored as `[[old, new]]`,
    a shape no client should be left to interpret.

    EXPOSING IT ADDS NO NPI THAT THIS RESPONSE DID NOT ALREADY CARRY. `comparison` is classified NPI
    and `readonly.condition_rounds` reduces it to `has_comparison`, because `letter_changes` derives
    from `header` — but ADR-405 governs the READONLY layer, and `ConditionRoundPublic.header` is
    already served whole to the authenticated processor working the file. The ids likewise resolve to
    conditions this same caller may read. What must not happen is this blob reaching a log line or a
    `readonly.*` view, and neither is this schema's door.
    """

    round_id: UUID
    round_number: int | None = None
    #: The panel's "Compared with the N conditions that were open before it."
    compared_with: int = 0
    new: list[UUID] = Field(default_factory=list)
    still_open: list[UUID] = Field(default_factory=list)
    came_back: list[UUID] = Field(default_factory=list)
    reworded: list[RewordedPairPublic] = Field(default_factory=list)
    probably_cleared: list[UUID] = Field(default_factory=list)
    letter_changes: list[LetterChangePublic] = Field(default_factory=list)
    #: Why nothing is suggested, or None when something is. S2-10's callout shows it as-is.
    no_suggestions_reason: str | None = None
    #: Each came-back that moved our track (LP-915 review). CLOSED enums; an unrecognised stored value
    #: drops the entry rather than travelling as an open string.
    came_back_moves: list[CameBackMovePublic] = Field(default_factory=list)

    @classmethod
    def from_stored(cls, stored: dict[str, Any] | None) -> "RoundComparisonPublic | None":
        """Read the saved JSONB. `None` for a round that was never compared — round 1, or a draft.

        `None` RATHER THAN AN EMPTY COMPARISON, for the reason `created` and `seen_again` above give
        at length: an all-zero comparison is a confident wrong answer where "the question does not
        apply" is the true one. Round 1 compares against nothing, and a panel reading "0 probably
        cleared · compared with 0" would be a claim nobody made.
        """
        if not stored:
            return None
        pairs = [
            RewordedPairPublic(old_id=UUID(str(pair[0])), new_id=UUID(str(pair[1])))
            for pair in stored.get("reworded") or []
            # A pair is written as exactly two ids. Anything else is skipped rather than raised on:
            # this is a stored blob being rendered, and one malformed entry must not 500 the panel.
            if isinstance(pair, (list, tuple)) and len(pair) == 2
        ]
        return cls(
            round_id=UUID(str(stored["round_id"])),
            round_number=stored.get("round_number"),
            compared_with=stored.get("compared_with") or 0,
            new=[UUID(str(value)) for value in stored.get("new") or []],
            still_open=[UUID(str(value)) for value in stored.get("still_open") or []],
            came_back=[UUID(str(value)) for value in stored.get("came_back") or []],
            reworded=pairs,
            probably_cleared=[UUID(str(value)) for value in stored.get("probably_cleared") or []],
            letter_changes=[
                LetterChangePublic.model_validate(change)
                for change in stored.get("letter_changes") or []
            ],
            no_suggestions_reason=stored.get("no_suggestions_reason"),
            came_back_moves=[
                CameBackMovePublic(
                    condition_id=UUID(str(condition_id)),
                    prep_status_from=ConditionPrepStatus(pair[0]),
                    prep_status_to=ConditionPrepStatus(pair[1]),
                )
                for condition_id, pair in (stored.get("came_back_moves") or {}).items()
                if isinstance(pair, (list, tuple))
                and len(pair) == 2
                and all(value in ConditionPrepStatus._value2member_map_ for value in pair)
            ],
        )


class ConditionRoundPublic(BaseModel):
    """One round, for the round strip and the review screen."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    round_number: int | None
    status: ConditionRoundStatus
    completeness: ConditionRoundCompleteness
    sheet_format: ConditionSheetFormat
    sources: list[ConditionSourcePublic] = Field(default_factory=list)
    date_printed: date_type | None
    round_date: date_type
    expiry_dates: dict[str, Any] | None = None
    #: PRESENT DOES NOT MEAN REVIEWABLE, and an earlier version of this comment said "Present on a
    #: DRAFT and cleared on import", which is true of one state and populated in two. `from_model`
    #: fills this whenever the round HAS rows, and `create_round_from_paste` writes them
    #: unconditionally — so a `PARSING` round awaiting the AI split carries the rules-read rows too.
    #:
    #: Screen S1-02 is the reason that is safe: while a round is `PARSING` it renders SKELETONS and
    #: polls, never these rows. Nothing is under review, which is exactly why the split task may
    #: replace them wholesale under its `status = PARSING` compare-and-set — where the enrich merge,
    #: acting on a DRAFT whose rows ARE on screen and editable, deliberately may not.
    #:
    #: So: read `status` to decide whether a processor can act on these, never their presence.
    draft_rows: list[DraftRowPublic] | None = None
    parse_report: ParseReportPublic = Field(default_factory=ParseReportPublic)
    #: The letter's own details, shown in the side panel and the round-details sheet. Absent for a
    #: paste, which has no letter — the panel then says so rather than rendering empty fields.
    header: dict[str, Any] | None = None
    #: What this import changed (LP-915). `None` until a round has been compared, which is every
    #: round 1 and every round that is not yet imported — see `RoundComparisonPublic.from_stored`.
    #:
    #: WITHOUT THIS FIELD S2-06 HAS NO DATA AT ALL. The comparison was computed and saved by the
    #: import, and nothing carried it to a client: the panel, its count pills, its letter changes and
    #: its confirm list are all this one object.
    comparison: RoundComparisonPublic | None = None
    condition_count: int = 0
    #: What the import recorded — "11 on sheet · 11 new", "· 0 new · 6 seen again" (S1-05, S1-08).
    #:
    #: `None` RATHER THAN `0`, AND THE FIELD DIRECTLY ABOVE IS WHY. `condition_count` shipped as
    #: `int = 0` with no producer at all, so every round card read "0 on sheet" for as long as anyone
    #: looked — and 0 is a VALID count, so nothing failed and no test noticed. These two carry the
    #: same hazard doubled: a DRAFT round has never been imported, so "0 new" is a confident wrong
    #: answer where "the question does not apply" is the true one. `None` cannot be mistaken for a
    #: measurement, and it is the difference between "nothing was new" and "nobody asked yet".
    #:
    #: THEY LIVE IN AN EVENT, NOT ON THE ROW. `condition_rounds` stores neither, so both are read
    #: from the round's newest `ROUND_IMPORTED` detail. `condition_events` is append-only, so
    #: "newest" is deliberate rather than incidental: a re-import would leave two.
    created: int | None = None
    seen_again: int | None = None
    created_at: datetime
    #: EXPOSED SO THE STALE-WRITE GUARD IS REACHABLE AT ALL (LP-909 §4). `ConditionDraftUpdate`
    #: says "the caller sends the `updated_at` it read" — and until now no caller could read it,
    #: because this schema carried only `created_at`. Every client therefore sent
    #: `expected_updated_at=None`, which the service treats as "no opinion", so the 409 that exists
    #: for two tabs on one draft could never fire. The review screen is the first caller that edits
    #: rows, which is what made the gap load-bearing rather than latent.
    updated_at: datetime

    @classmethod
    def from_model(
        cls,
        round_: ConditionRound,
        *,
        condition_count: int = 0,
        created: int | None = None,
        seen_again: int | None = None,
    ) -> "ConditionRoundPublic":
        return cls(
            id=round_.id,
            round_number=round_.round_number,
            status=round_.status,
            completeness=round_.completeness,
            sheet_format=round_.sheet_format,
            # `from_source`, NOT `model_validate`. A `sources` entry is raw JSONB with no
            # `has_bytes` key, so validating it would silently default the flag to False on every
            # round — and False is a VALID value, so nothing would fail. The client would then offer
            # "Attach the lender's PDF" on rounds that already have one, which is the exact defect
            # the field was added to close.
            sources=[ConditionSourcePublic.from_source(s) for s in (round_.sources or [])],
            date_printed=round_.date_printed,
            round_date=round_.round_date,
            expiry_dates=round_.expiry_dates,
            draft_rows=(
                [DraftRowPublic.model_validate(r) for r in round_.draft_rows]
                if round_.draft_rows is not None
                else None
            ),
            parse_report=ParseReportPublic.model_validate(round_.parse_report or {}),
            header=round_.header,
            comparison=RoundComparisonPublic.from_stored(round_.comparison),
            condition_count=condition_count,
            created=created,
            seen_again=seen_again,
            created_at=round_.created_at,
            updated_at=round_.updated_at,
        )


class ConditionSummaryPublic(BaseModel):
    """The summary bar and the file rail's counts (spec §LP-911, screens S2-01 and S2-02).

    IT LIVES BELOW `ConditionRoundPublic` BECAUSE IT REFERS TO IT, and Python resolves an annotation
    when the class body runs. Declared above, `latest_round: ConditionRoundPublic | None` raises
    `NameError` on import — measured, not guessed: it did. A quoted forward reference would also work
    and is the wrong fix here, because it would leave the file readable in an order it cannot actually
    be built in.

    COUNTS AND NOTHING ELSE — no codes, no wording. It is the one response the file rail reads on
    every visit, and a summary that carried rows would put the lender's words on a screen that only
    ever shows numbers.

    `open` COUNTS `not_cleared` TOO, because a condition the lender refused is back with the
    processor; and info-only and superseded conditions are never open (spec §LP-911). That rule lives
    in `services/conditions.py::is_open` so the number here and the row's own `is_open` cannot
    disagree.
    """

    model_config = ConfigDict(from_attributes=True)

    total: int
    open: int
    cleared: int
    waived: int
    not_cleared: int
    superseded: int
    info_only: int

    #: Keyed by the enum's value. OPEN conditions only — the summary bar exists to say what is still
    #: outstanding, which is what makes S2-02's "Prior to docs open 1" a different number from "how
    #: many prior-to-docs conditions this file has ever had".
    by_prep_status: dict[str, int] = Field(default_factory=dict)
    by_owner: dict[str, int] = Field(default_factory=dict)
    by_bucket_kind: dict[str, int] = Field(default_factory=dict)

    #: The two the summary bar prints as their own numbers. Both are `by_bucket_kind` lookups rather
    #: than separate counts, so they cannot drift from it.
    open_prior_to_docs: int
    open_prior_to_funding: int

    #: 0 UNTIL LP-915 PRODUCES ONE. Shipped as a key now because LP-913 renders the bar from this
    #: model and the TypeScript mirror would otherwise change twice; never a guess, and the round
    #: card's "N probably cleared — review" reads it.
    pending_suggestions: int = 0

    #: The newest imported round, for the rail's "from round 2, printed 09/10". `None` on a file whose
    #: sheets have all been discarded or never imported.
    latest_round: ConditionRoundPublic | None = None


# --------------------------------------------------------------------------- #
# Write bodies
# --------------------------------------------------------------------------- #


class BulkAction(StrEnum):
    """Which of the three writes a bulk call applies (spec §LP-912)."""

    PREP_STATUS = "prep_status"
    VERDICT = "verdict"
    OWNER = "owner"


#: `expected_updated_at` RATHER THAN THE SPEC'S `updated_at`, AND THE DEPARTURE IS DELIBERATE.
#: Spec §LP-912 writes `updated_at` in all five request bodies; `ConditionDraftUpdate` above already
#: ships `expected_updated_at` for exactly this purpose, in this same feature, since LP-909. Two names
#: for one concept inside one feature is the drift this repo keeps correcting, and the existing name is
#: the clearer of the two — it says it is the value the caller READ, not the value it is setting.
#:
#: OPTIONAL, AND THAT IS NOT A LOOPHOLE. `None` means "no opinion", the same as on the draft: a caller
#: that never read the row cannot be made to echo it. What makes the guard real is that the client
#: always has the value (LP-911 put `updated_at` on `ConditionPublic` for this), and a test asserts a
#: stale value is refused AND changed nothing.
class _ConcurrentWrite(BaseModel):
    """The optimistic-concurrency field every LP-912 write carries."""

    expected_updated_at: datetime | None = None


class PrepStatusRequest(_ConcurrentWrite):
    """Move our track (ADR-408). Forward needs nothing; backward needs a reason.

    `waiting_on` IS REQUIRED WHEN MOVING TO `waiting` and the service refuses without it: "waiting"
    with nobody named is a status that cannot be acted on, and the list groups by owner.
    """

    to: ConditionPrepStatus
    waiting_on: OwnerHint | None = None
    #: Required for a BACKWARD move only. One short line, kept in history.
    reason: str | None = Field(default=None, max_length=500)
    #: NPI — what a processor typed about this file. Never logged, never in `readonly.*`.
    note: str | None = Field(default=None, max_length=256)
    #: Defaults to now on a move to `with_underwriter`, but overridable: a processor records a
    #: submission they made this morning.
    sent_at: datetime | None = None


class VerdictRequest(_ConcurrentWrite):
    """Record what the lender said (ADR-408). The ONLY way to `cleared` or `waived`.

    `source_date` IS REQUIRED AND IS NEVER DEFAULTED TO TODAY. It is the date the LENDER said it; a
    verdict dated by our clock is a verdict about us. That is why it has no default here rather than
    `date.today()`.
    """

    status: ConditionLenderStatus
    source_kind: VerdictSourceKind
    source_date: date_type
    #: Required for the two derived sources, which name the sheet that showed it.
    round_id: UUID | None = None
    #: NPI — the processor's own note about the verdict ("Cleared in EASE, condition status screen").
    note: str | None = Field(default=None, max_length=500)


class ReopenRequest(_ConcurrentWrite):
    """Put a cleared or waived condition back to open. The reason is required.

    The old verdict STAYS in history: this says it was overruled, not that it never happened.
    """

    reason: str = Field(min_length=1, max_length=500)


class OwnerRequest(_ConcurrentWrite):
    """Set or clear the manual owner override (A2).

    `None` MEANS "BACK TO THE HINT", not "nobody". Clearing the override restores whatever the sheet or
    the code map suggested, which is why the field is nullable rather than the endpoint having a second
    verb.
    """

    owner: OwnerHint | None = None


class BulkRequest(_ConcurrentWrite):
    """One write applied to many conditions, refusing the rows that may not have it.

    THE FIELDS OF ALL THREE ACTIONS LIVE HERE, and the service validates the ones the chosen action
    needs. The spec's shape is `{condition_ids[], action, …same fields}`, and a discriminated union per
    action would be the tidier model — rejected because the UI sends one dialog's worth of fields for a
    row set it does not want to split, and three request models would push that split onto the client.
    """

    condition_ids: list[UUID] = Field(min_length=1, max_length=500)
    action: BulkAction

    # `prep_status`
    to: ConditionPrepStatus | None = None
    waiting_on: OwnerHint | None = None
    reason: str | None = Field(default=None, max_length=500)
    #: 256, MATCHING `PrepStatusRequest.note`, AND THE MISMATCH WAS A REAL HOLE. This was 500 while
    #: that one is 256 (the width of the `prep_note` column), so a bulk prep-status call carrying a
    #: 300-character note built a `PrepStatusRequest` inside `_apply_one` and raised a Pydantic
    #: `ValidationError` — which is not a `ConditionRefused`, so it escaped the per-row `except` and
    #: would have failed the whole batch with a 500 instead of refusing one row. Both linters and mypy
    #: were happy: two different valid integers.
    #:
    #: `reason` is deliberately still 500 here and 500 there, so the pair now agrees in both fields.
    #: The general rule this is an instance of: a bulk request that re-constructs a single-row request
    #: must not be able to hold a value the single-row request rejects, or bulk becomes the way round
    #: the validation.
    note: str | None = Field(default=None, max_length=256)
    sent_at: datetime | None = None

    # `verdict`
    status: ConditionLenderStatus | None = None
    source_kind: VerdictSourceKind | None = None
    source_date: date_type | None = None
    round_id: UUID | None = None

    # `owner`
    owner: OwnerHint | None = None


class BulkRefusalPublic(BaseModel):
    """One row the bulk write would not touch, and why — in the server's own sentence."""

    model_config = ConfigDict(from_attributes=True)

    condition_id: UUID
    #: The typed code, so a client can branch without parsing prose.
    code: str
    #: The plain sentence the UI shows AS-IS (spec §6 rule 5). It never writes its own.
    message: str


class BulkResultPublic(BaseModel):
    """What a bulk write did and what it refused (spec §LP-912).

    BOTH HALVES, ALWAYS. The UI's line is "4 marked cleared · 1 skipped: information only", so a
    response that reported only the successes would leave the processor to work out which row did not
    move — and silently skipping a row is the failure this shape exists to prevent.
    """

    model_config = ConfigDict(from_attributes=True)

    applied: list[UUID] = Field(default_factory=list)
    refused: list[BulkRefusalPublic] = Field(default_factory=list)


class ConditionPasteRequest(BaseModel):
    """Paste conditions copied from a lender portal (LP-907).

    `completeness` is REQUIRED and has no default here on purpose. The UI defaults the control to
    "just some" — the answer that can never remove anything — but the API refusing to guess is what
    makes that a decision rather than a fallback (ADR-404).
    """

    text: str = Field(min_length=1, max_length=MAX_PASTE_CHARS)
    completeness: ConditionRoundCompleteness
    round_date: date_type | None = None


class ConditionDraftUpdate(BaseModel):
    """Replace a draft round's rows before import (LP-909).

    Optimistic concurrency: the caller sends the `updated_at` it read, and a mismatch is refused
    rather than silently overwriting another tab's edit.
    """

    draft_rows: list[DraftRowPublic]
    completeness: ConditionRoundCompleteness | None = None
    round_date: date_type | None = None
    expected_updated_at: datetime | None = None


class ConfirmClearedRequest(BaseModel):
    """Which of a round's suggestions to record as cleared (LP-915, screens S2-06 and S2-07).

    THE TICKED IDS, NEVER "ALL". S2-07's whole content is that `0132` is unticked and the button reads
    *Confirm 4 as cleared* — so the client sends what she ticked. A request meaning "all of them"
    would make the panel's state unrepresentable and would clear a condition she had just untied.

    AT LEAST ONE, WHICH IS A GUARD RATHER THAN VALIDATION FOR ITS OWN SAKE. Confirming resolves the
    round's suggestions either way — the unticked ones stay open and lose the suggestion — so an empty
    list would withdraw every suggestion while recording no verdict at all. That is *Not now*'s
    opposite and it is reachable by accident; *Not now* sends no request.
    """

    condition_ids: list[UUID] = Field(min_length=1)
    #: True from the PANEL, which decides the whole round (the unticked lose their suggestion). False
    #: from the DETAIL SHEET, which answers one condition and leaves the rest pending (LP-915 review).
    resolve_rest: bool = True


class RewordedDecisionRequest(BaseModel):
    """S2-08's two buttons: *Same condition — replace the old one* / *Different conditions — keep
    both*.

    BOTH IDS TRAVEL, NOT A PAIR INDEX. The saved comparison is a list, and an index would name a
    different pair the moment another pair in the same round was resolved — two processors on one
    file is exactly the case that produces.
    """

    old_id: UUID
    new_id: UUID
    #: True for *Same condition*. False for *Different conditions*, which changes no condition at all
    #: and only answers the question.
    same: bool


class RoundCompletenessUpdate(_ConcurrentWrite):
    """Switch an imported round between *Full list* and *Just some* (A7, screen S2-10).

    `expected_updated_at`, NOT THE SPEC'S `updated_at`. §LP-915 writes the body as
    `{completeness, updated_at}`, and every other concurrent write in this feature ships
    `expected_updated_at` — the name says it is the value the caller READ, not one it is setting.
    `_ConcurrentWrite`'s own comment records the same choice being made once already; a second
    spelling inside one feature is the drift this file keeps correcting.
    """

    completeness: ConditionRoundCompleteness


class ConditionCreateRequest(BaseModel):
    """Add one condition by hand (LP-909, screen S1-12).

    The wording is required and is stored exactly as typed — the dialog's hint says "Type it exactly
    as the lender wrote it", and this is the boundary that honours it.
    """

    verbatim_text: str = Field(min_length=1, max_length=20_000)
    lender_code: str | None = Field(default=None, max_length=16)
    lender_category: str | None = Field(default=None, max_length=256)
    bucket_heading: str | None = Field(default=None, max_length=256)
    bucket_kind: BucketKind = BucketKind.UNKNOWN


class ConditionEnrichResult(BaseModel):
    """What attaching the lender's PDF to an existing round did (LP-907, screen S1-09).

    EVERY FIELD IS A COUNT OR A FLAG, NEVER A CONDITION'S WORDING. S1-09's success callout says
    what the PDF filled in and that it added no new conditions and no second round, so counts are
    what it needs — and `unmatched_existing` is deliberately a NUMBER rather than the texts, because
    those are the lender's words and this response is not where they belong (ADR-405). The rows
    themselves come back on the round.
    """

    round_id: UUID
    #: Always the round that was passed in. Present so the caller can assert it, since "no second
    #: round was created" is the property this whole endpoint exists to guarantee.
    round_number: int | None = None
    status: ConditionRoundStatus
    sheet_format: ConditionSheetFormat
    filled_header: bool = False
    filled_expiry: bool = False
    filled_date_printed: bool = False
    #: Existing rows that gained a code, category or bucket the paste could not carry.
    matched: int = 0
    #: Rows on the PDF that the paste did not have — added to THIS round, never a new one.
    added: int = 0
    #: Rows the paste had and the PDF does not. KEPT, never removed (ADR-404).
    unmatched_existing: int = 0
    warnings: list[str] = Field(default_factory=list)


class ConditionImportResult(BaseModel):
    """What an import did, for the toast and the timeline entry.

    `seen_again` never implies anything was closed: a condition missing from a new sheet is simply
    not touched in Stage 1.
    """

    round_id: UUID
    round_number: int
    created: int
    seen_again: int
    unmapped_codes: list[str] = Field(default_factory=list)
