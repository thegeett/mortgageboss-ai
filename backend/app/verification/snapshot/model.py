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
from app.verification.snapshot.tag import Tag

# The on-disk snapshot shape version. Bump when the structure changes so a reader
# always knows which shape it holds (readers branch on this; see ADR-241).
# v2 (LP-302a) — DocumentEntry gains a nested ``transactions`` list (bank statements).
# v3 (LP-312) — raw facts gain a stable ``content_id``; a ``tags`` layer is added alongside
#   the raw sections; ``CalcBreakdownLine`` gains ``from_tag``. v2 is superseded, not
#   supported — no production snapshot was ever persisted (LP-310), so a clean bump is safe.
# v4 (LP-318) — ``CalcBreakdownLine.from_tag`` is populated (calc lineage); ``CalculationEntry``
#   gains ``gated`` / ``gate_reason`` / ``confidence`` (fail-closed through the calculators).
# LP-421 — DocumentEntry gains nested ``schedule_c`` / ``schedule_e`` (tax returns), the ADR-061
#   first-class-typed-path pattern. This is a BACKWARD-COMPATIBLE ADDITIVE change (both fields default
#   ``None``), so the version is NOT bumped: a v4 snapshot without the fields still validates (they default
#   absent), and — unlike the v2 transactions bump — a committed golden fixture (lf6t3n_tagged_snapshot.json,
#   v4) must keep loading. Bumping would trip the strict version validator on it, and the additive change
#   preserves the byte-identical equivalence (D6) that a bump would break.
SNAPSHOT_VERSION = 4

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

    ``content_id`` (LP-312) is a STABLE, run-independent id derived from the transaction's
    content (scoped under its parent document's id, with a duplicate tiebreak) — what a tag's
    ``source_facts`` / a finding's ``subject_key`` reference. Built by
    :mod:`app.verification.snapshot.content_id`; see ADR-251.
    """

    model_config = {"frozen": True}

    content_id: str = PydField(min_length=1)
    date: Field
    amount: Field
    direction: Field
    description: Field


class ScheduleCRecord(BaseModel):
    """One Schedule C (self-employment business) surfaced into the snapshot (LP-421).

    The tax-return extractor already produces Schedule C as TYPED CORE
    (``ScheduleC`` / ``_SCHEDULE_C_SPEC``), but ``build_document_fields`` dropped it
    (a nested structure ``_scalar`` can't flatten). This is the first-class typed path
    (ADR-061, as bank-statement transactions got), so a producer can read the
    self-employment signal (IN-12) from the snapshot. Each field is an ordinary
    :class:`Field` (nullable confidence, absent≠empty) — ``business_name`` /
    ``net_profit`` are the consumer-relevant figures; ``gross_receipts`` /
    ``total_expenses`` complete the record (the extractor's spec). No ``content_id``:
    a schedule is document-level (read off the parent :class:`DocumentEntry`), not a
    subject a rule enumerates — unlike a transaction.
    """

    model_config = {"frozen": True}

    business_name: Field
    gross_receipts: Field
    total_expenses: Field
    net_profit: Field  # the self-employment heart (IN-12)


class ScheduleEPropertyRecord(BaseModel):
    """One rental property on Schedule E (LP-421) — the inner level of the two-level shape."""

    model_config = {"frozen": True}

    address: Field
    rents_received: Field  # the rental signal (IN-13)
    total_expenses: Field
    net_income: Field


class ScheduleERecord(BaseModel):
    """Schedule E (rental / supplemental income) surfaced into the snapshot (LP-421).

    The TWO-LEVEL shape (the one most likely to be flattened): a ``properties`` tuple
    of :class:`ScheduleEPropertyRecord` PLUS scalar totals. ``properties`` is a
    ``tuple`` for immutability (the LP-204 frozen-nested lesson); it may be **empty**
    (a Schedule E present with per-property detail absent) — distinct from the whole
    Schedule E being absent (then ``DocumentEntry.schedule_e`` is ``None``, never a
    fabricated empty record). Feeds the rental signal (IN-13).
    """

    model_config = {"frozen": True}

    properties: tuple[ScheduleEPropertyRecord, ...]
    total_net_rental_income: Field
    depreciation: Field


class ListRow(BaseModel):
    """One row of a GENERIC nested list (LP-437) — the same typed shape as a document's flat fields.

    ``fields`` is a ``{name: Field}`` map, exactly like :attr:`DocumentEntry.fields`, so a row field
    keeps its value + confidence + provenance ``source`` (page/snippet are not carried into the snapshot
    ``Field`` for a row any more than for a flat field or a transaction — the fidelity matches a bespoke
    list). ``row_id`` is a STABLE content-derived id (via :func:`assign_content_ids`), populated ONLY where
    a list declares ``stable_row_id`` (a list whose rows a rule enumerates as finding subjects, like
    transactions); ``None`` otherwise (a list read only in aggregate needs no per-row id).

    This is the generic counterpart to the bespoke :class:`TransactionRecord` / :class:`ScheduleCRecord`:
    the three legacy nested attributes (``transactions`` / ``schedule_c`` / ``schedule_e``) are UNTOUCHED
    (they feed live AS-1 / IN-12 / IN-13); ``lists`` is for the 66 NEW lists only (LP-436 coexist ruling)."""

    model_config = {"frozen": True}

    fields: dict[str, Field]
    row_id: str | None = None


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

    ``content_id`` (LP-312) is a STABLE, run-independent id derived from the document's
    content (type + resolved borrowers + fields + an order-independent fingerprint of its
    transactions, with a duplicate tiebreak) — what a tag's ``source_facts`` / a finding's
    ``subject_key`` reference. Built by :mod:`app.verification.snapshot.content_id`; see ADR-251.
    """

    model_config = {"frozen": True}

    content_id: str = PydField(min_length=1)
    document_type: str | None = None
    belongs_to: tuple[BorrowerRef, ...] | None = None
    fields: dict[str, SnapshotField] = PydField(default_factory=dict)
    transactions: tuple[TransactionRecord, ...] | None = None
    # LP-421 — tax-return schedules, surfaced via the ADR-061 typed path (dropped by
    # ``build_document_fields`` before). ``None`` = absent (not a tax return, or the return
    # carried no such schedule) — NEVER a fabricated empty record (absent≠empty). ``schedule_c``
    # is a non-empty tuple when present (the self-employment signal, IN-12); ``schedule_e`` a
    # single record whose own ``properties`` may be empty (the rental signal, IN-13). ``k1s`` is
    # NOT surfaced — no consumer today (LP-421 D2).
    schedule_c: tuple[ScheduleCRecord, ...] | None = None
    schedule_e: ScheduleERecord | None = None
    # LP-437 — the GENERIC nested-list channel: ``{list_name: (ListRow, ...)}``, one attribute for any
    # number of lists. ADDITIVE with a default (present-empty ``{}`` for every document today), the LP-421
    # precedent EXACTLY — so SNAPSHOT_VERSION is NOT bumped and the committed v4 golden fixture (which
    # carries no ``lists`` key) still validates (the default fills it). Coexists with the three legacy
    # attributes above, which are left untouched (they feed live rules). List data is deliberately NOT
    # surfaced to the AI context builders (``_doc_context`` reads only ``fields``) — the same catch-all
    # boundary that gated IH-1, a known and separate decision (LP-436 step 8 / ADR).
    lists: dict[str, tuple[ListRow, ...]] = PydField(default_factory=dict)

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

    ``from_tag`` (LP-312) is the fact-tag ``content_id`` / vocabulary id that produced this
    line's value, so a calculator line traces to the tag behind it (§3D). ``None`` for now —
    the calculator-tag wrapping (LP-318) populates it; shipped in this version bump to avoid
    a second one.
    """

    model_config = {"frozen": True}

    key: str
    label: str
    amount: str | None = None  # money serialized as an exact string
    source: str
    overridden: bool = False
    from_tag: str | None = None


class CalculationEntry(BaseModel):
    """One calculator's output: headline ``value`` map + itemized ``breakdown``.

    ``value`` holds stringified headline numbers (e.g. ``{"back_end_dti": "43.10"}``)
    so the blob serializes exactly. The container never computes — it holds what a
    calculator produced (LP-207 maps them in).

    ``gated`` / ``gate_reason`` / ``confidence`` (LP-318) make the calculator a fail-closed,
    confidence-propagating tag consumer like every other (§3D). A calc built on a REQUIRED input
    that is unknown/absent (a breakdown line tracing to an unknown fact-tag — e.g. no insurance
    binder) is ``gated``: its headline ratio is nulled (not a confident-but-wrong number) and
    ``gate_reason`` names the tag that caused it — a rule reading it degrades to couldnt_check.
    ``confidence`` is the min of the feeding tags' confidences (ignoring parsed/derived
    passthroughs, per the LP-315 convention); ``None`` when nothing but passthroughs feed it.
    """

    model_config = {"frozen": True}

    value: dict[str, str | bool | None] = PydField(default_factory=dict)
    breakdown: list[CalcBreakdownLine] = PydField(default_factory=list)
    gated: bool = False
    gate_reason: str | None = None  # PII-safe: names the fact-tag(s) that gated it, never raw data
    confidence: float | None = None

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


class TagsSection(BaseModel):
    """The tags layer (LP-312, §3D) — AI-structured fact-tags OVER the raw layer.

    The snapshot is one artifact with two layers: the RAW layer (``mismo`` / ``documents`` /
    ``calculations`` — exactly what Stage 1 builds, unchanged, now the substrate) and this
    TAGS layer produced over it, every tag citing raw facts by their stable ``content_id``.

    ``by_subject`` maps a raw fact's ``content_id`` (a transaction / document) to the tags
    ABOUT that fact, keyed by vocabulary tag id (e.g. ``"txn.is_money_in"``). It is
    **present-empty** today — this ticket ships the shape; LP-313/314 produce the tags. As
    with the raw sections, ``absent`` (not-built/failed) is distinct from present-empty
    (built, no tags yet).
    """

    model_config = {"frozen": True}

    # raw-fact content_id → { vocabulary tag id → Tag }.
    by_subject: dict[str, dict[str, Tag]] = PydField(default_factory=dict)
    absent: bool = False
    reason: str | None = None  # PII-safe failure explanation (only when absent)

    @model_validator(mode="after")
    def _absent_is_empty(self) -> TagsSection:
        if self.absent and self.by_subject:
            raise ValueError("an absent TagsSection carries no tags")
        if not self.absent and self.reason is not None:
            raise ValueError("a present TagsSection carries no reason")
        return self

    @classmethod
    def present(cls, by_subject: dict[str, dict[str, Tag]] | None = None) -> TagsSection:
        return cls(by_subject=by_subject or {}, absent=False)

    @classmethod
    def missing(cls) -> TagsSection:
        return cls(absent=True)

    @classmethod
    def failed(cls, reason: str) -> TagsSection:
        """An absent layer because tag production could not build it (with a reason)."""
        return cls(absent=True, reason=reason)

    @property
    def is_present(self) -> bool:
        return not self.absent


class Snapshot(BaseModel):
    """The per-run snapshot — a raw layer + a tags layer + metadata.

    Frozen: re-assigning an attribute raises (the contained collections are
    immutable by convention — see the module docstring). The RAW layer is the three
    independent sections ``mismo`` / ``documents`` / ``calculations`` (each present-empty by
    default); the ``tags`` layer (LP-312) is produced over it, present-empty for now. No field
    correlates the raw sections — a cross-section link cannot be expressed as a *field*
    (equal-value matching via ``PiiField.match_hash`` is a deliberate downstream capability,
    not a field here); the tags layer is where cross-fact correlation will live instead.
    """

    model_config = {"frozen": True}

    loan_file_id: UUID
    run_id: UUID
    created_at: datetime
    snapshot_version: int = SNAPSHOT_VERSION

    # Raw layer — exactly what Stage 1 builds (unchanged, the substrate).
    mismo: MismoSection = PydField(default_factory=MismoSection)
    documents: DocumentsSection = PydField(default_factory=DocumentsSection)
    calculations: CalculationsSection = PydField(default_factory=CalculationsSection)

    # Tags layer — AI-structured fact-tags over the raw layer (present-empty until LP-313/314).
    tags: TagsSection = PydField(default_factory=TagsSection)

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
