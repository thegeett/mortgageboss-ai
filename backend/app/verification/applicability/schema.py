"""Applicability schema (LP-119) — the DATA shape a rule's applicability is authored in.

Every verification rule carries an ``applicability`` object (stored as JSON on
``verification_rules.applicability``, LP-118) with three parts (ADR-239):

* **scope** — dimensional constraints (``program`` / ``loan_purpose`` / ``refinance_type`` /
  ``occupancy`` / ``property_type``). An empty constraint = *no* constraint (applies to all).
* **triggers** — ``all`` / ``any`` / ``none`` groups of conditions (``entity_exists`` /
  ``field_condition``) that decide whether the rule is *relevant* to this file.
* **required_inputs** — the data the evaluator needs to actually RUN (a ``data_field`` /
  ``document`` / ``derived_field``). NOTE: the thing a rule CHECKS is **not** a required input —
  its absence is the finding (evaluated in LP-120), not an awaiting-data skip.

The engine (:mod:`app.verification.applicability.engine`) reads this as DATA — no rule-specific
logic. This module is just the parsed shape + the three-valued / state enums.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Ternary(StrEnum):
    """Three-valued truth — the core of the honesty contract."""

    TRUE = "true"
    FALSE = "false"
    UNKNOWN = "unknown"  # the data needed to DECIDE is missing → never a silent pass/skip


class ApplicabilityState(StrEnum):
    """The classification of a rule against one file's fact snapshot."""

    DOESNT_APPLY = "doesnt_apply"  # scope/trigger FALSE → irrelevant → silently excluded
    COULDNT_CHECK = "couldnt_check"  # applies but decision/required data missing → surfaced
    READY_TO_RUN = "ready_to_run"  # applies AND data present → eligible for the evaluator (LP-120)


# --------------------------------------------------------------------------- #
# Trigger conditions
# --------------------------------------------------------------------------- #


class EntityExists(BaseModel):
    """ "Does any element of ``collection`` satisfy ``field <op> value``?" — e.g. a gift asset."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    kind: Literal["entity_exists"] = "entity_exists"
    collection: str  # a snapshot collection path, e.g. "assets", "liabilities"
    field: str  # the element field to test, e.g. "is_gift"
    op: str = "eq"
    value: Any = None


class FieldCondition(BaseModel):
    """ "Does the fact at ``path`` satisfy ``<op> value``?" — e.g. file.program in [fha]."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    kind: Literal["field_condition"] = "field_condition"
    path: str  # a snapshot fact path, e.g. "file.program"
    op: str  # eq | ne | in | not_in | gt | lt | gte | lte
    value: Any = None


Condition = Annotated[EntityExists | FieldCondition, Field(discriminator="kind")]


class TriggerGroup(BaseModel):
    """``all`` (AND) / ``any`` (OR) / ``none`` (NOR) groups of conditions, combined with AND.

    An empty group (no conditions anywhere) → the rule has no triggers → always relevant.
    """

    model_config = ConfigDict(frozen=True, populate_by_name=True, extra="forbid")
    all_: list[Condition] = Field(default_factory=list, alias="all")
    any_: list[Condition] = Field(default_factory=list, alias="any")
    none_: list[Condition] = Field(default_factory=list, alias="none")


# --------------------------------------------------------------------------- #
# Required inputs (the data the evaluator needs to RUN)
# --------------------------------------------------------------------------- #


class DataField(BaseModel):
    """A snapshot fact/collection that must be present to run — e.g. ``assets[].is_gift``."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    kind: Literal["data_field"] = "data_field"
    path: str


class DocumentPresent(BaseModel):
    """A document of ``document_type`` must be present on the file — e.g. ``credit_report``."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    kind: Literal["document"] = "document"
    document_type: str


class DerivedField(BaseModel):
    """A computed fact that must be computable — e.g. ``computed.ltv`` (absent → couldn't-check)."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    kind: Literal["derived_field"] = "derived_field"
    path: str


RequiredInput = Annotated[DataField | DocumentPresent | DerivedField, Field(discriminator="kind")]


class Applicability(BaseModel):
    """A rule's parsed applicability (the JSON on ``verification_rules.applicability``).

    A ``None``/empty applicability means: no scope, no triggers, no required inputs → the rule is
    universally relevant and runnable → READY_TO_RUN.
    """

    model_config = ConfigDict(frozen=True, populate_by_name=True, extra="forbid")
    scope: dict[str, list[str]] = Field(default_factory=dict)
    triggers: TriggerGroup = Field(default_factory=TriggerGroup)
    required_inputs: list[RequiredInput] = Field(default_factory=list)


class Classification(BaseModel):
    """The result of classifying one rule — the state + WHY (for the trust surface, LP-140)."""

    model_config = ConfigDict(frozen=True)
    state: ApplicabilityState
    reasons: list[str] = Field(default_factory=list)  # why doesn't-apply / couldn't-check
    missing_inputs: list[str] = Field(default_factory=list)  # named missing inputs/data
