"""Snapshot field primitive (LP-203, ADR-240).

``Field`` is the shared shape every snapshot fact uses: a value, its origin, and
(reusing LP-201's model exactly) a nullable, never-fabricated confidence. The PII
variant lives in :mod:`app.verification.snapshot.pii`.

**Absent != empty — the load-bearing distinction.** A field that *no source
supplied* (absent) is not the same as a field a source supplied as null/empty/zero
(present-but-empty). Collapsing the two would let the snapshot silently treat
"MISMO never carried this" the same as "MISMO carried a blank" — a correctness
hazard for downstream rules. The mechanism is an explicit ``absent`` marker with
two factories:

* ``Field.present(value, source=..., confidence=...)`` — a source supplied this
  fact; ``value`` may legitimately be ``None`` / ``""`` / ``0`` (present-but-empty).
* ``Field.missing()`` — **no** source supplied this fact; carries no value, source,
  or confidence.

``is_present`` / ``absent`` read the distinction; a validator enforces that the two
states never blur (an absent field has nothing; a present field has a source).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, field_validator, model_validator

from app.models.extraction import ConfidenceSource

# A JSON-safe scalar. Decimals/dates are normalized to strings by the assemblers
# (later tickets) before they reach a Field, so a snapshot serializes cleanly.
JsonScalar = str | int | float | bool


class FieldSource(StrEnum):
    """Where a snapshot fact came from (its data origin — not its confidence tag)."""

    PARSED = "parsed"  # deterministic MISMO / 1003 parse
    EXTRACTED = "extracted"  # an AI document extraction


class Field(BaseModel):
    """One snapshot fact: a value + its origin + a nullable confidence.

    Frozen and closed (``extra="forbid"``). ``confidence`` reuses LP-201's model —
    a genuine number or ``None`` (``not_provided``), never a fabricated default —
    and the provenance tag is *derived* (:attr:`confidence_source`), never stored,
    so the two can't disagree.
    """

    model_config = {"frozen": True, "extra": "forbid"}

    value: JsonScalar | None = None
    confidence: float | None = None
    source: FieldSource | None = None
    # Explicit "no source supplied this" marker — distinct from a present null value.
    absent: bool = False

    @field_validator("value", mode="before")
    @classmethod
    def _value_must_be_a_json_scalar(cls, v: object) -> object:
        """Reject non-JSON-scalar inputs (e.g. Decimal, date) instead of lossy-coercing.

        Pydantic would silently coerce a ``Decimal`` (money) to ``float`` and lose
        precision. The contract is that assemblers stringify ``Decimal``/``date``
        first; enforce it here so a violation fails loudly at the primitive rather
        than corrupting a value that only surfaces downstream. (``bool`` is allowed —
        it is a ``JsonScalar`` member and an ``int`` subclass.)
        """
        if v is not None and not isinstance(v, (str, int, float, bool)):
            raise ValueError(
                f"Field.value must be a JSON scalar (str/int/float/bool) or None, not "
                f"{type(v).__name__} — assemblers must stringify Decimal/date first"
            )
        return v

    @model_validator(mode="after")
    def _absent_and_present_never_blur(self) -> Field:
        if self.absent:
            if self.value is not None or self.source is not None or self.confidence is not None:
                raise ValueError("an absent Field carries no value, source, or confidence")
        elif self.source is None:
            raise ValueError("a present Field must carry a source")
        return self

    @classmethod
    def present(
        cls,
        value: JsonScalar | None,
        *,
        source: FieldSource,
        confidence: float | None = None,
    ) -> Field:
        """A fact a source supplied (``value`` may be null/empty — that's present-but-empty)."""
        return cls(value=value, source=source, confidence=confidence, absent=False)

    @classmethod
    def missing(cls) -> Field:
        """A fact NO source supplied — absent, distinct from a present null value."""
        return cls(absent=True)

    @property
    def is_present(self) -> bool:
        """True when a source supplied this fact (even if the value is null/empty)."""
        return not self.absent

    @property
    def confidence_source(self) -> ConfidenceSource:
        """The derived confidence provenance (LP-201's single derivation rule)."""
        return ConfidenceSource.for_confidence(self.confidence)
