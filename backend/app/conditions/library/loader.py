"""Load and validate the condition library (LP-918).

REFUSES RATHER THAN GUESSES. The library decides plans (principle 5), so a malformed row is not a
warning: it is a plan the app would propose on bad data. Every check below raises `LibraryError`, and
the test suite loads the shipped file, so a bad edit fails CI instead of a processor's round.

What is checked, and why each one:

- **Ids match `XX-00`** and are unique. The shape keeps a verification-rule id (`IN-7`) from being pasted
  in; uniqueness is what makes `canonical_type_id` a key.
- **Performers, options and checks are the closed vocabularies** in `app.models.condition_vocabulary`,
  so the library and the columns that will store them cannot drift.
- **Document types are ones the classifier can produce** (the `document_type` of a schema spec, or the
  classifier's `custom`/`miscellaneous_document`). A type naming a document the app never files is an
  "already in the file" check that can never succeed.
- **An agency citation is one the Stage 3 plan cites** (`AGENCY_CITATIONS`). Anything else is
  `lender_requirement`. A processor quotes these to underwriters; an invented section is worse than none.
- **A type with no items has a `default_option`** of `lender_doing_it` or `information_only`, and a type
  with items has none (its items carry their own options) — so every type yields a plan.
- **`waits_on_type` names a type that exists.**
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import StrEnum
from functools import cache
from pathlib import Path
from typing import Any

import yaml

from app.models.condition_vocabulary import EvidenceCheck, Performer, PlanOption

_HERE = Path(__file__).resolve().parent
_TYPES_FILE = _HERE / "types.yaml"
_SPECS_DIR = _HERE.parents[1] / "schema_specs"

_ID = re.compile(r"^[A-Z]{2}-\d{2}$")

#: The only agency sections the library may cite: the ones the Stage 3 plan itself cites (§2.3 and its
#: Sources). Adding one means adding the source to the plan first.
AGENCY_CITATIONS: frozenset[str] = frozenset(
    {
        "Fannie Mae B3-4.2-02",
        "Fannie Mae B3-4.3-09",
        "Fannie Mae B3-3.1-04",
        "Fannie Mae B3-2-10",
        "Fannie Mae B7-3-07 / B7-3-08",
        "Reg Z 1026.36(c)(3)",
    }
)

#: Document types the classifier emits without a schema spec of their own.
_EXTRA_DOCUMENT_TYPES = frozenset({"custom", "miscellaneous_document"})

#: The options a condition with no items may carry: nothing to collect, so either the lender acts or
#: there is nothing to do.
_ITEMLESS_OPTIONS = frozenset({PlanOption.LENDER_DOING_IT, PlanOption.INFORMATION_ONLY})


class LibraryError(ValueError):
    """The library file is malformed; the message names the type and the field."""


class TypeCategory(StrEnum):
    ASSETS = "assets"
    CREDIT = "credit"
    INCOME = "income"
    INSURANCE = "insurance"
    PROPERTY = "property"
    IDENTITY = "identity"
    TITLE = "title"
    CLOSING = "closing"
    DISCLOSURE = "disclosure"
    INVOICE = "invoice"
    LENDER = "lender"


@dataclass(frozen=True)
class TypeRule:
    """The rule behind a type: an agency section the plan cites, or the lender's own requirement."""

    kind: str  # "agency" | "lender_requirement"
    citation: str | None
    note: str | None

    @property
    def label(self) -> str:
        return self.citation if self.citation else "Lender requirement"


@dataclass(frozen=True)
class LibraryItem:
    """One thing a condition of this type usually asks for."""

    key: str
    name: str
    acceptable: str
    performer: Performer
    option: PlanOption
    documents: tuple[str, ...]
    checks: tuple[EvidenceCheck, ...]
    #: A name that states the lender's amount ("Source of the {amount}"), used when the lender's text
    #: carries one. CODE fills `{amount}` from the text (LP-919); the model never writes it.
    name_with_amount: str | None = None
    #: Words that tell THIS document from others of the same type when looking for one the file already
    #: holds ("credit" for a credit report invoice against a processing invoice). Matched by code
    #: against the document's name; LP-920's "Already in the file".
    match_words: tuple[str, ...] = ()


@dataclass(frozen=True)
class ConditionType:
    id: str
    name: str
    category: TypeCategory
    rule: TypeRule
    playbook: str
    items: tuple[LibraryItem, ...]
    default_option: PlanOption | None
    waits_on_type: str | None

    @property
    def label(self) -> str:
        """`AS-04 Earnest money` — how S3-01's library chip names it."""
        return f"{self.id} {self.name}"

    @property
    def options(self) -> tuple[PlanOption, ...]:
        """The condition's proposed next steps: each item's option once, in item order."""
        if not self.items:
            assert self.default_option is not None
            return (self.default_option,)
        seen: list[PlanOption] = []
        for item in self.items:
            if item.option not in seen:
                seen.append(item.option)
        return tuple(seen)


@dataclass(frozen=True)
class Library:
    version: int
    types: dict[str, ConditionType]

    def get(self, type_id: str | None) -> ConditionType | None:
        return self.types.get(type_id) if type_id else None


def known_document_types() -> frozenset[str]:
    """Every `document_type` a schema spec declares, plus the classifier's two catch-alls."""
    found: set[str] = set(_EXTRA_DOCUMENT_TYPES)
    for path in _SPECS_DIR.glob("[0-9]*.json"):
        value = json.loads(path.read_text()).get("document_type")
        if isinstance(value, str):
            found.add(value)
    return frozenset(found)


def _enum[EnumT: StrEnum](enum_cls: type[EnumT], value: Any, where: str) -> EnumT:
    try:
        return enum_cls(value)
    except ValueError:
        allowed = ", ".join(member.value for member in enum_cls)
        raise LibraryError(f"{where}: {value!r} is not one of {allowed}") from None


def _text(raw: dict[str, Any], field: str, where: str) -> str:
    value = raw.get(field)
    if not isinstance(value, str) or not value.strip():
        raise LibraryError(f"{where}: {field} must be non-empty text")
    return value.strip()


def _rule(raw: Any, where: str) -> TypeRule:
    if not isinstance(raw, dict):
        raise LibraryError(f"{where}: rule must be a mapping")
    kind = raw.get("kind")
    if kind == "agency":
        citation = raw.get("citation")
        if citation not in AGENCY_CITATIONS:
            raise LibraryError(
                f"{where}: {citation!r} is not a citation the Stage 3 plan makes; "
                "use kind: lender_requirement, or add the source to the plan first"
            )
        return TypeRule(kind="agency", citation=citation, note=raw.get("note"))
    if kind == "lender_requirement":
        if raw.get("citation"):
            raise LibraryError(f"{where}: a lender_requirement carries no citation")
        return TypeRule(kind="lender_requirement", citation=None, note=raw.get("note"))
    raise LibraryError(f"{where}: rule.kind must be agency or lender_requirement, not {kind!r}")


def _name_with_amount(value: Any, where: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or "{amount}" not in value:
        raise LibraryError(f"{where}: name_with_amount must be text containing {{amount}}")
    return value


def _item(raw: Any, where: str, documents_known: frozenset[str]) -> LibraryItem:
    if not isinstance(raw, dict):
        raise LibraryError(f"{where}: an item must be a mapping")
    documents = tuple(raw.get("documents") or ())
    unknown = [doc for doc in documents if doc not in documents_known]
    if unknown:
        raise LibraryError(f"{where}: documents {unknown} are not document types the app files")
    return LibraryItem(
        key=_text(raw, "key", where),
        name=_text(raw, "name", where),
        acceptable=_text(raw, "acceptable", where),
        performer=_enum(Performer, raw.get("performer"), f"{where} performer"),
        option=_enum(PlanOption, raw.get("option"), f"{where} option"),
        documents=documents,
        checks=tuple(
            _enum(EvidenceCheck, check, f"{where} check") for check in (raw.get("checks") or ())
        ),
        name_with_amount=_name_with_amount(raw.get("name_with_amount"), where),
        match_words=tuple(str(word).lower() for word in raw.get("match_words") or ()),
    )


def parse_library(data: Any, *, documents_known: frozenset[str] | None = None) -> Library:
    """Validate a parsed library document. Separate from `load_library` so tests can feed bad data."""
    documents_known = documents_known if documents_known is not None else known_document_types()
    if not isinstance(data, dict) or not isinstance(data.get("types"), list):
        raise LibraryError("the library must be a mapping with a `types` list")
    version = data.get("version")
    if not isinstance(version, int):
        raise LibraryError("the library must carry an integer `version`")

    types: dict[str, ConditionType] = {}
    for raw in data["types"]:
        type_id = raw.get("id") if isinstance(raw, dict) else None
        if not isinstance(type_id, str) or not _ID.match(type_id):
            raise LibraryError(
                f"type id {type_id!r} must look like AS-04 (two letters, two digits)"
            )
        if type_id in types:
            raise LibraryError(f"type id {type_id} appears twice")
        where = f"type {type_id}"
        items = tuple(
            _item(item, f"{where} item {index + 1}", documents_known)
            for index, item in enumerate(raw.get("items") or ())
        )
        keys = [item.key for item in items]
        if len(keys) != len(set(keys)):
            raise LibraryError(f"{where}: item keys repeat ({keys})")
        default_raw = raw.get("default_option")
        default_option = (
            _enum(PlanOption, default_raw, f"{where} default_option") if default_raw else None
        )
        if not items and default_option not in _ITEMLESS_OPTIONS:
            raise LibraryError(
                f"{where}: a type with no items needs default_option lender_doing_it or information_only"
            )
        if items and default_option is not None:
            raise LibraryError(
                f"{where}: a type with items takes its options from them, not default_option"
            )
        types[type_id] = ConditionType(
            id=type_id,
            name=_text(raw, "name", where),
            category=_enum(TypeCategory, raw.get("category"), f"{where} category"),
            rule=_rule(raw.get("rule"), where),
            playbook=_text(raw, "playbook", where),
            items=items,
            default_option=default_option,
            waits_on_type=raw.get("waits_on_type"),
        )

    for condition_type in types.values():
        waits = condition_type.waits_on_type
        if waits is not None and waits not in types:
            raise LibraryError(f"type {condition_type.id}: waits_on_type {waits!r} is not a type")
    return Library(version=version, types=types)


@cache
def load_library() -> Library:
    """The shipped library, validated once per process."""
    return parse_library(yaml.safe_load(_TYPES_FILE.read_text()))
