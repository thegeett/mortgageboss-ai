"""Read the shipped lender code maps, and refuse a malformed one loudly (LP-910, ADR-407).

Pure: no database, no network. It turns two YAML files into validated rows; putting them INTO
`lender_condition_codes` is the seed step's job (`app/scripts/seed_lender_codes.py`), and the
separation is what lets the whole file be checked by a test with no database at all.

WHAT THIS REFUSES, AND WHY EACH ONE IS WORTH AN EXCEPTION RATHER THAN A SKIP:

* **A non-string code.** This is the one that would otherwise cost months. YAML reads an unquoted
  `0006` as the integer `6`, and `6` matches nothing — a lender code keeps its leading zeros because
  it is an identifier printed on a document, not a number. Coercing with `str(value)` would turn the
  mistake into `"6"`, which is worse: it looks right. So a non-string is an error naming the file and
  the code.
* **A duplicate code within one file.** Two rows for `7086` means one silently wins, and which one
  depends on dict ordering. The map is reviewed by a person; a duplicate is an editing accident that
  should stop them, not resolve itself.
* **An unknown bucket kind or owner hint.** These are enum values the readers and the import path
  act on. A typo (`prior_to_doc`) would load fine, match no `BucketKind`, and quietly downgrade every
  condition carrying that code to `UNKNOWN`.
* **A missing or empty `lender_key`.** The key is what the seed matches on
  (`lenders.canonical_lender_key`); a file without one can only ever seed nothing, and doing that
  quietly is how a code map appears to ship and does not.

A `@cache` on the parse, following `distrust.py`: the files do not change at runtime, and both the
seed step and the tests read them repeatedly.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import yaml

from app.models.condition import BucketKind, OwnerHint

#: The shipped maps, by the key the seed matches on. Paths are built with `with_name` so they
#: resolve against THIS module rather than a working directory or a repo layout — see the packaging
#: note in this package's `__init__`.
_FILES: dict[str, Path] = {
    "uwm": Path(__file__).with_name("uwm.yaml"),
    "champions": Path(__file__).with_name("champions.yaml"),
}


class LenderCodeSeedError(Exception):
    """A shipped code map is malformed, or names something that does not exist."""


@dataclass(frozen=True)
class LenderCodeRow:
    """One validated row: what this lender's code means.

    `canonical_type_id` is absent from both shipped files and is therefore always ``None`` today.
    That is deliberate rather than unfinished — the taxonomy it refers to
    (`phase4.5-appendix-C-condition-taxonomy`) is not in this repository, and the rule ids that look
    like it in `docs/rule-engine.md` are a different vocabulary. Stage 3 fills it.
    """

    code: str
    label: str
    default_bucket_kind: BucketKind | None
    default_owner_hint: OwnerHint | None
    info_only: bool
    canonical_type_id: str | None


def _enum_or_none[EnumT](
    raw: Any, enum_cls: type[EnumT], *, field: str, code: str, source: str
) -> EnumT | None:
    """Resolve an optional enum value, refusing an unrecognised one.

    Null is legitimate — a code whose bucket or owner nobody has decided yet — and is different from
    a typo, which this raises on. Collapsing the two would make `prior_to_doc` behave exactly like
    "not decided", which is the failure this whole function exists to prevent.
    """
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise LenderCodeSeedError(f"{source}: code {code!r} has a non-string {field}: {raw!r}")
    try:
        return enum_cls(raw)  # type: ignore[call-arg]
    except ValueError as exc:
        permitted = ", ".join(sorted(member.value for member in enum_cls))  # type: ignore[attr-defined]
        raise LenderCodeSeedError(
            f"{source}: code {code!r} has {field}={raw!r}, which is not one of: {permitted}"
        ) from exc


def _row(raw: Any, *, source: str) -> LenderCodeRow:
    if not isinstance(raw, dict):
        raise LenderCodeSeedError(f"{source}: every entry under `codes:` must be a mapping")

    code = raw.get("code")
    # ⚠️ THE LEADING-ZERO GUARD. Unquoted `0006` parses as the integer 6, and `str(6)` would give
    # `"6"` — an identifier that looks plausible and matches nothing. Refused, never coerced.
    if not isinstance(code, str):
        raise LenderCodeSeedError(
            f"{source}: code {raw.get('code')!r} is {type(raw.get('code')).__name__}, not a string. "
            "Quote it in the YAML — an unquoted 0006 becomes the integer 6 and loses the zeros that "
            "make it an identifier."
        )
    if not code.strip():
        raise LenderCodeSeedError(f"{source}: a code is empty")

    label = raw.get("label")
    if not isinstance(label, str) or not label.strip():
        raise LenderCodeSeedError(f"{source}: code {code!r} has no label")

    canonical = raw.get("canonical_type_id")
    if canonical is not None and not isinstance(canonical, str):
        raise LenderCodeSeedError(f"{source}: code {code!r} has a non-string canonical_type_id")

    return LenderCodeRow(
        code=code,
        label=label.strip(),
        default_bucket_kind=_enum_or_none(
            raw.get("default_bucket_kind"),
            BucketKind,
            field="default_bucket_kind",
            code=code,
            source=source,
        ),
        default_owner_hint=_enum_or_none(
            raw.get("default_owner_hint"),
            OwnerHint,
            field="default_owner_hint",
            code=code,
            source=source,
        ),
        info_only=bool(raw.get("info_only", False)),
        canonical_type_id=canonical,
    )


@cache
def load_seed(lender_key: str) -> tuple[LenderCodeRow, ...]:
    """Every validated row for one lender, in file order.

    Raises :class:`LenderCodeSeedError` for an unknown key or a malformed file. File order is kept
    rather than sorted: the YAML is maintained by a person and reads in the order a sheet prints,
    which is worth preserving in anything that reports on it.
    """
    path = _FILES.get(lender_key)
    if path is None:
        known = ", ".join(sorted(_FILES))
        raise LenderCodeSeedError(f"no shipped code map for {lender_key!r} (have: {known})")

    source = path.name
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise LenderCodeSeedError(f"{source}: the file must be a mapping at its root")

    declared_key = document.get("lender_key")
    if not isinstance(declared_key, str) or not declared_key.strip():
        raise LenderCodeSeedError(f"{source}: no `lender_key`, so this file can only seed nothing")
    if declared_key != lender_key:
        # The filename and the declared key disagreeing means one of them is a rename nobody
        # finished, and the seed would match on the key while a reader looked at the filename.
        raise LenderCodeSeedError(
            f"{source}: declares lender_key {declared_key!r} but is loaded as {lender_key!r}"
        )

    entries = document.get("codes")
    if not isinstance(entries, list) or not entries:
        raise LenderCodeSeedError(f"{source}: `codes:` must be a non-empty list")

    rows = tuple(_row(entry, source=source) for entry in entries)

    seen: set[str] = set()
    duplicates = sorted({row.code for row in rows if row.code in seen or seen.add(row.code)})  # type: ignore[func-returns-value]
    if duplicates:
        raise LenderCodeSeedError(
            f"{source}: duplicate codes {duplicates}. One would silently win, and which one depends "
            "on ordering."
        )
    return rows


def seeded_lender_keys() -> tuple[str, ...]:
    """The lender keys this build ships a map for, sorted.

    What the seed step iterates, and what a test asserts against `lenders.canonical_lender_key` so a
    renamed key cannot leave a map that matches no lender.
    """
    return tuple(sorted(_FILES))
