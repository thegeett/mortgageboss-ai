"""The frozen three-section snapshot model (LP-204, ADR-241).

The container for a per-run snapshot, built on LP-203's ``Field`` / ``PiiField``
primitives. Nothing populates it yet — the assemblers (LP-205/206/207) and the
builder (LP-208) come later; this is the schema they code against and the shape
persisted as JSON (LP-209).

**Immutability is shallow (by design of pydantic ``frozen``).** Re-assigning any
model attribute raises; but ``frozen`` does *not* deep-freeze the contained
collections (``facts`` / ``entries`` / ``breakdown`` / ``value``) — a caller could
still ``snapshot.mismo.facts[k] = ...`` in place. The contract is therefore:
assemblers build each section's collection ONCE and never mutate a built snapshot;
the snapshot is treated as immutable by convention, not deep-enforced.

Three independent sections, **deliberately un-linkable**:

* ``mismo`` — a flat ``key → Field|PiiField`` map of parsed 1003/MISMO facts.
* ``documents`` — an ordered list of :class:`DocumentEntry`, each the extracted
  fields of one document plus a *resolved* ``belongs_to`` borrower reference
  (LP-202). The document's raw asserted name stays as an ordinary entry in
  ``fields``; ``belongs_to`` is the resolved link, never the raw name.
* ``calculations`` — the four calculators' output as ``{value, breakdown}``, each
  breakdown line keeping the calculator's own per-line source tag.

**No cross-section correlation.** There is no field anywhere that references
another section's keys/entries — so a link *between* sections cannot even be
expressed. Correlating MISMO vs document facts is a downstream job, excluded here
by construction (ADR-241).

**Absent ≠ empty** survives at both levels: a ``Field``/``PiiField`` no source
supplied is absent (LP-203); a whole section can likewise be ``absent`` (not built
/ failed), distinct from present-but-empty (e.g. "no documents yet" = a present,
empty list). Both survive JSON round-trip losslessly.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, field_validator, model_validator
from pydantic import Field as PydField

from app.verification.snapshot.fields import Field
from app.verification.snapshot.pii import PiiField

# The on-disk snapshot shape version. Bump when the structure changes so a reader
# always knows which shape it holds (readers branch on this; see ADR-241).
# v2 (LP-302a) — DocumentEntry gains a nested ``transactions`` list (bank statements).
SNAPSHOT_VERSION = 2

# A snapshot cell is either a plain fact or a masked PII fact. The two are
# mutually exclusive under LP-203's ``extra="forbid"`` (``value`` vs
# ``display``/``match_hash``), so the union round-trips unambiguously.
SnapshotField = Field | PiiField


class BorrowerRef(BaseModel):
    """A resolved document→borrower reference (LP-202, option-2): id + name.

    Carries the borrower id plus the borrower's resolved *name* so a reader needs
    no DB join. This references a borrower *entity*, not another snapshot section —
    the one allowed correlation, and the deliberate opposite of matching raw names
    across sections at read time. The match provenance (confidence/method) is NOT
    surfaced here — it lives in the ``document_borrower_links`` row; the snapshot
    carries the resolved identity. Distinct from the RAW asserted name a document
    printed, which stays as an ordinary ``fields`` entry (``asserted_name``).
    """

    model_config = {"frozen": True}

    borrower_id: UUID
    name: str


class MismoSection(BaseModel):
    """The parsed-MISMO facts: a flat ``key → Field|PiiField`` map.

    ``absent`` marks the section as not-built/failed (distinct from a present-empty
    map — no MISMO facts). When a build FAILED, ``reason`` carries a PII-safe
    explanation (LP-208): ``absent + reason`` = couldn't build; ``absent`` alone =
    simply not built. Keys are free strings (e.g. ``"borrower.1.income.base_monthly"``)
    — deliberately unconstrained so new facts never need a schema change.
    """

    model_config = {"frozen": True}

    facts: dict[str, SnapshotField] = PydField(default_factory=dict)
    absent: bool = False
    reason: str | None = None  # PII-safe failure explanation (only when absent)

    @model_validator(mode="after")
    def _absent_is_empty(self) -> MismoSection:
        if self.absent and self.facts:
            raise ValueError("an absent MismoSection carries no facts")
        if not self.absent and self.reason is not None:
            raise ValueError("a present MismoSection carries no reason")
        return self

    @classmethod
    def present(cls, facts: dict[str, SnapshotField] | None = None) -> MismoSection:
        return cls(facts=facts or {}, absent=False)

    @classmethod
    def missing(cls) -> MismoSection:
        return cls(absent=True)

    @classmethod
    def failed(cls, reason: str) -> MismoSection:
        """An absent section because its assembler could not build it (with a reason)."""
        return cls(absent=True, reason=reason)

    @property
    def is_present(self) -> bool:
        return not self.absent


class TransactionRecord(BaseModel):
    """One bank-statement transaction row (LP-302a) — the per-deposit facts a
    per-transaction rule (AS-1 large-deposit, later NSF/chaining/recurring) reads
    FROM THE SNAPSHOT.

    ``date`` / ``amount`` / ``direction`` / ``description`` are ordinary
    :class:`Field`\\s (nullable confidence, absent≠empty) — so a row the extractor read
    without a date carries ``date`` = an absent Field, distinct from a present-null one.
    ``date`` / ``amount`` / ``description`` are ``source=extracted``; ``direction`` is
    ``source=derived`` — it is ``credit`` / ``debit`` COMPUTED from the extraction's
    ``transaction_type`` (the extractor stores ``amount`` positive, so the amount sign
    carries no direction), or an **absent** Field when the type is unclassifiable (never
    a fabricated ``credit`` — that would forge a deposit and trip AS-1 on every unlabelled
    withdrawal). ``description`` has any 9+-digit identifier (incl. space/dash-grouped
    accounts/cards) / SSN pattern redacted so it is PII-safe at rest (never a raw
    account/id in the blob), while keeping the sourcing signal (PAYROLL / TRANSFER / VENMO).

    The statement's masked account is NOT duplicated onto every row — it lives once on the
    parent :class:`DocumentEntry`'s ``fields["account_number_masked"]`` (a pre-masked,
    non-matchable :class:`PiiField`); a per-transaction rule reads it from the entry it is
    already iterating. The deposit↔MISMO-asset account cross-section match is unavailable
    on this branch (extraction holds no raw account to hash); see ADR-248 / LP-302a.
    """

    model_config = {"frozen": True}

    date: Field
    amount: Field
    direction: Field
    description: Field


class DocumentEntry(BaseModel):
    """One document's contribution: type + resolved borrower(s) + extracted fields.

    ``belongs_to`` is ``None`` when no borrower resolved, or a **non-empty** tuple of
    :class:`BorrowerRef` (one, or many for a joint document). It is a ``tuple`` so a
    built entry's resolved-borrower list is itself immutable (not just the attribute
    reassignment). The document's raw asserted name is NOT here — it stays as an
    ordinary entry in ``fields`` (``asserted_name``).

    ``transactions`` (LP-302a) is a nested list for bank statements — a ``tuple`` for
    immutability (the LP-204 frozen-nested lesson). **``None`` = not surfaced/absent**
    (a non-bank document, or a statement whose extraction carried no transaction
    list); **an empty tuple = a statement present with zero transactions**
    (present-empty). The two are deliberately distinct (absent≠empty).
    """

    model_config = {"frozen": True}

    document_type: str | None = None
    belongs_to: tuple[BorrowerRef, ...] | None = None
    fields: dict[str, SnapshotField] = PydField(default_factory=dict)
    transactions: tuple[TransactionRecord, ...] | None = None

    @model_validator(mode="after")
    def _belongs_to_null_or_nonempty(self) -> DocumentEntry:
        # None = no borrower resolved (unresolved / no-match / unprocessable); a tuple
        # must carry at least one ref (use None for none), so "resolved to nobody"
        # can't masquerade as an empty list.
        if self.belongs_to is None:
            return self
        if len(self.belongs_to) == 0:
            raise ValueError("belongs_to is None (no borrower) or a non-empty tuple — never ()")
        # One ref per borrower — the DB enforces UNIQUE(document_id, borrower_id),
        # so a document must not claim the same borrower twice.
        ids = [ref.borrower_id for ref in self.belongs_to]
        if len(ids) != len(set(ids)):
            raise ValueError("belongs_to must not repeat a borrower_id (one ref per borrower)")
        return self


class DocumentsSection(BaseModel):
    """The ordered documents. An empty ``entries`` list is PRESENT ("no documents
    yet"); ``absent`` marks the section not-built/failed — a distinct state.
    """

    model_config = {"frozen": True}

    entries: list[DocumentEntry] = PydField(default_factory=list)
    absent: bool = False
    reason: str | None = None  # PII-safe failure explanation (only when absent)

    @model_validator(mode="after")
    def _absent_is_empty(self) -> DocumentsSection:
        if self.absent and self.entries:
            raise ValueError("an absent DocumentsSection carries no entries")
        if not self.absent and self.reason is not None:
            raise ValueError("a present DocumentsSection carries no reason")
        return self

    @classmethod
    def present(cls, entries: list[DocumentEntry] | None = None) -> DocumentsSection:
        return cls(entries=entries or [], absent=False)

    @classmethod
    def missing(cls) -> DocumentsSection:
        return cls(absent=True)

    @classmethod
    def failed(cls, reason: str) -> DocumentsSection:
        """An absent section because its assembler could not build it (with a reason)."""
        return cls(absent=True, reason=reason)

    @property
    def is_present(self) -> bool:
        return not self.absent


class CalcBreakdownLine(BaseModel):
    """One itemized calculator input, keeping the calculator's own source tag.

    ``source`` is the calculator vocabulary (``stated`` / ``computed`` /
    ``extracted`` / ``manual`` / ``override``) — a free string, NOT the
    ``FieldSource`` used elsewhere, and deliberately unconstrained so a new tag
    round-trips.
    """

    model_config = {"frozen": True}

    key: str
    label: str
    amount: str | None = None  # money serialized as an exact string
    source: str
    overridden: bool = False


class CalculationEntry(BaseModel):
    """One calculator's output: headline ``value`` map + itemized ``breakdown``.

    ``value`` holds stringified headline numbers (e.g. ``{"back_end_dti": "43.10"}``)
    so the blob serializes exactly. The container never computes — it holds what a
    calculator produced (LP-207 maps them in).
    """

    model_config = {"frozen": True}

    value: dict[str, str | bool | None] = PydField(default_factory=dict)
    breakdown: list[CalcBreakdownLine] = PydField(default_factory=list)

    @field_validator("value", mode="before")
    @classmethod
    def _values_are_str_bool_or_none(cls, v: object) -> object:
        """Reject a raw number instead of coercing it — pydantic would silently turn
        an unstringified ``int`` (a count, a 0/1 flag) into ``bool`` (``1`` → ``True``).

        Headline numbers must be stringified by the calculator (``"43.10"``); ``bool``
        stays allowed (a genuine flag), but a real ``int``/``float``/``Decimal`` fails
        loudly here rather than corrupting the blob (mirrors ``Field.value``).
        """
        if isinstance(v, dict):
            for key, item in v.items():
                if item is not None and not isinstance(item, (str, bool)):
                    raise ValueError(
                        f"CalculationEntry.value[{key!r}] must be str/bool/None, not "
                        f"{type(item).__name__} — the calculator must stringify numbers"
                    )
        return v


class CalculationsSection(BaseModel):
    """The four calculators (DTI / LTV / MI / reserves). Cash-to-close is NOT here.

    Each entry is ``None`` when that calculator's output is absent; ``absent`` marks
    the whole section not-built.
    """

    model_config = {"frozen": True}

    dti: CalculationEntry | None = None
    ltv: CalculationEntry | None = None
    mi: CalculationEntry | None = None
    reserves: CalculationEntry | None = None
    absent: bool = False
    reason: str | None = None  # PII-safe failure explanation (only when absent)

    @classmethod
    def present(
        cls,
        *,
        dti: CalculationEntry | None = None,
        ltv: CalculationEntry | None = None,
        mi: CalculationEntry | None = None,
        reserves: CalculationEntry | None = None,
    ) -> CalculationsSection:
        return cls(dti=dti, ltv=ltv, mi=mi, reserves=reserves, absent=False)

    @classmethod
    def missing(cls) -> CalculationsSection:
        return cls(absent=True)

    @classmethod
    def failed(cls, reason: str) -> CalculationsSection:
        """An absent section because its assembler could not build it (with a reason)."""
        return cls(absent=True, reason=reason)

    @model_validator(mode="after")
    def _absent_is_empty(self) -> CalculationsSection:
        if self.absent and any((self.dti, self.ltv, self.mi, self.reserves)):
            raise ValueError("an absent CalculationsSection carries no calculators")
        if not self.absent and self.reason is not None:
            raise ValueError("a present CalculationsSection carries no reason")
        return self

    @property
    def is_present(self) -> bool:
        return not self.absent


class Snapshot(BaseModel):
    """The per-run snapshot — three independent sections + metadata.

    Frozen: re-assigning an attribute raises (the contained collections are
    immutable by convention — see the module docstring). ``mismo`` / ``documents`` /
    ``calculations`` default to present-empty sections. No field correlates sections
    — a cross-section link cannot be expressed as a *field* (equal-value matching via
    ``PiiField.match_hash`` is a deliberate downstream capability, not a field here).
    """

    model_config = {"frozen": True}

    loan_file_id: UUID
    run_id: UUID
    created_at: datetime
    snapshot_version: int = SNAPSHOT_VERSION

    mismo: MismoSection = PydField(default_factory=MismoSection)
    documents: DocumentsSection = PydField(default_factory=DocumentsSection)
    calculations: CalculationsSection = PydField(default_factory=CalculationsSection)

    @field_validator("created_at")
    @classmethod
    def _created_at_is_tz_aware(cls, v: datetime) -> datetime:
        """A per-run timestamp must be timezone-aware, so runs order unambiguously."""
        if v.tzinfo is None:
            raise ValueError("created_at must be timezone-aware (e.g. datetime.now(UTC))")
        return v

    @model_validator(mode="after")
    def _known_snapshot_version(self) -> Snapshot:
        """Reject a snapshot whose version this reader doesn't understand.

        The version travels with the artifact so a reader knows the shape it holds;
        an unrecognized version is a hard failure, not a silent mis-read (extra
        fields of a future shape would otherwise be dropped and the blob accepted).
        """
        if self.snapshot_version != SNAPSHOT_VERSION:
            raise ValueError(
                f"unsupported snapshot_version {self.snapshot_version} "
                f"(this reader supports {SNAPSHOT_VERSION})"
            )
        return self
