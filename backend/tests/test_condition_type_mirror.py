"""The frontend's condition types are a second copy of one fact — this is what forces them to agree.

⚠️ `frontend/lib/types/conditions.ts` RESTATES EVERY CONDITION ENUM BY HAND, and until this file
nothing connected the two. A review pass checked all eight member-for-member and found no drift, which
is the problem rather than the reassurance: it was correct by vigilance, and vigilance is not a
mechanism. Add `BucketKind.ESCROW_HOLDBACK` to the backend and the TypeScript union simply does not
have it; every Python test passes, `tsc` passes, and the first symptom is a bucket chip that renders
as an unrecognised value in front of a processor.

THIS IS `test_activity_type_migrations.py`'s TRICK, POINTED ACROSS THE STACK. That guard reads
migrations AS TEXT because a database test cannot see the bug — the schema it tests was built from the
very enum it would be checking. Here the same shape: no Python test can see a TypeScript file, and no
`tsc` run can see a Python enum, so the only way the two can be compared is for one side to read the
other as text.

⚠️ WHAT THIS DOES NOT COVER, said plainly so nobody reads it as more than it is:

* **The eleven interfaces are not checked field-for-field.** Parsing TypeScript interfaces with a
  regex is a different order of difficulty from parsing string-union members, and a half-working
  parser that silently matched nothing would be worse than no test — that failure mode has cost this
  ticket four assertions already. Enums are where a silent addition is most likely and where the
  comparison is unambiguous, so enums are what this pins.
* **A NEW backend enum nobody mirrors** is caught only if someone adds it to `_MIRRORED` below. That
  list is deliberately hand-written for the reason `design-tokens.test.ts` gives about its own
  exemptions: "listed rather than pattern-matched so a new one is a decision somebody makes".
"""

from __future__ import annotations

import re
from enum import StrEnum
from pathlib import Path

import pytest
from app.models.condition import BucketKind, ConditionOrigin, OwnerHint, OwnerHintSource
from app.models.condition_round import (
    ConditionRoundCompleteness,
    ConditionRoundStatus,
    ConditionSheetFormat,
    ConditionSourceKind,
)
from app.schemas.condition import MAX_PASTE_CHARS

#: `backend/tests/x.py` → `backend/tests` → `backend` → the repo root.
_TYPES_FILE = Path(__file__).resolve().parents[2] / "frontend" / "lib" / "types" / "conditions.ts"

#: The hooks module, which holds the numbers rather than the types. A second path because the
#: stranded window lives with the polling logic that uses it, not with the type declarations.
_TYPES_FILE_API = Path(__file__).resolve().parents[2] / "frontend" / "lib" / "api" / "conditions.ts"

#: TypeScript name → the backend enum it restates. Hand-written on purpose: a backend enum added
#: with no entry here is invisible to this test, and that has to be somebody's decision rather than
#: a silent omission.
_MIRRORED: dict[str, type[StrEnum]] = {
    "BucketKind": BucketKind,
    "OwnerHint": OwnerHint,
    "OwnerHintSource": OwnerHintSource,
    "ConditionOrigin": ConditionOrigin,
    "ConditionRoundStatus": ConditionRoundStatus,
    "ConditionRoundCompleteness": ConditionRoundCompleteness,
    "ConditionSheetFormat": ConditionSheetFormat,
    "ConditionSourceKind": ConditionSourceKind,
}

#: `export type Name = "a" | "b";` — on one line when short, wrapped across many when biome decides
#: it is long. Both forms are the same to this pattern, which is why it matches the whole right-hand
#: side up to the semicolon rather than a line.
_UNION = re.compile(r"export type (\w+)\s*=\s*([^;]+);")
_MEMBER = re.compile(r'"([^"]+)"')


def _unions() -> dict[str, list[str]]:
    """Every `export type X = "..." | "..."` in the file, as name → members in source order."""
    source = _TYPES_FILE.read_text(encoding="utf-8")
    found: dict[str, list[str]] = {}
    for name, body in _UNION.findall(source):
        members = _MEMBER.findall(body)
        # Unions of other TYPES rather than of string literals have no members; skipping them
        # silently is safe because `_MIRRORED` names what must be present and the test below fails
        # on anything missing.
        if members:
            found[name] = members
    return found


def test_the_types_file_is_where_this_test_thinks_it_is() -> None:
    """⚠️ WITHOUT THIS, A MOVED OR RENAMED FILE MAKES EVERY TEST BELOW VACUOUS. `_unions()` would
    raise, or — worse, if the read were ever made forgiving — return nothing and turn every
    comparison into a pass over an empty set. The guard that cannot fail is this ticket's most
    repeated defect; this is its antidote here."""
    assert _TYPES_FILE.is_file(), f"the frontend condition types are not at {_TYPES_FILE}"
    assert _unions(), "no string-literal unions parsed — the regex or the file's shape has changed"


@pytest.mark.parametrize("name", sorted(_MIRRORED))
def test_every_mirrored_enum_is_present_in_the_frontend(name: str) -> None:
    """A backend enum the TypeScript file does not declare at all."""
    assert name in _unions(), (
        f"`{name}` is mirrored in `_MIRRORED` but no `export type {name}` exists in "
        f"{_TYPES_FILE.name} — the frontend cannot type a value it has never heard of"
    )


@pytest.mark.parametrize("name", sorted(_MIRRORED))
def test_the_frontend_union_matches_the_backend_enum(name: str) -> None:
    """⚠️ SET EQUALITY IN BOTH DIRECTIONS, because the two failures are different bugs.

    A member in Python and not in TypeScript means the API can send a value the client cannot type —
    the chip renders as an unrecognised string. A member in TypeScript and not in Python means the
    client handles a case the server can never produce, which is dead code that reads as coverage.
    """
    frontend = set(_unions()[name])
    backend = {member.value for member in _MIRRORED[name]}

    missing = backend - frontend
    extra = frontend - backend
    assert not missing, f"{name}: the backend has {sorted(missing)} and the frontend does not"
    assert not extra, f"{name}: the frontend has {sorted(extra)} and the backend does not"


def test_the_stranded_window_agrees() -> None:
    """The second number both sides enforce, and the one that was actually disagreeing (LP-909).

    The client had `5 * 60 * 1000` justified by S1-02's "usually under 30 seconds", which consulted
    neither Celery limit — and 300s is EXACTLY `PARSE_SOFT_LIMIT_SECONDS`, so the tab called a round
    dead at the instant the worker raises `SoftTimeLimitExceeded`, with a minute of hard-limit
    runway left. Now that the server REFUSES a reparse inside its own window, a client that is
    shorter offers a button that reliably 409s.

    ⚠️ READ FROM `app.conditions.limits`, NOT FROM A LITERAL HERE. The server derives the window
    from the timeout it must exceed; pinning against a number typed into this test would make the
    test the third copy of the fact rather than the thing that stops copies drifting.
    """
    from app.conditions.limits import STRANDED_AFTER_SECONDS

    source = _TYPES_FILE_API.read_text(encoding="utf-8")
    match = re.search(r"const STRANDED_AFTER_MS\s*=\s*([0-9_]+)\s*\*\s*1000\s*;", source)
    assert match, (
        "STRANDED_AFTER_MS is not declared in the expected form in "
        f"{_TYPES_FILE_API.name} — if it moved or changed shape this guard is checking nothing"
    )
    assert int(match.group(1).replace("_", "")) == STRANDED_AFTER_SECONDS


def test_the_paste_ceiling_agrees() -> None:
    """The one number both sides enforce. The client counts characters in the textarea (S1-06) and
    the server refuses the body; a disagreement means either a paste refused after it was accepted
    on screen, or a count that promises room the server will not take."""
    source = _TYPES_FILE.read_text(encoding="utf-8")
    match = re.search(r"export const MAX_PASTE_CHARS\s*=\s*([0-9_]+)\s*;", source)
    assert match, "MAX_PASTE_CHARS is not declared in the frontend types"
    assert int(match.group(1).replace("_", "")) == MAX_PASTE_CHARS
