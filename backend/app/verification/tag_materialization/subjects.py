"""Production SUBJECTS (LP-326) — enumerate the things a tag is produced FOR, and read their raw
facts. Registry-resolved, one entry per subject TYPE (transaction / document / loan) — a new family
on an existing subject type needs no new entry here.

Each subject type provides three things the generic producers need:

* ``enumerate`` — the (subject_content_id, raw_object) pairs to produce a tag for.
* ``read_field`` — the raw ``Field`` / ``PiiField`` for a parsed declaration's field name (or None).
* ``build_context`` — the per-subject dict the AI producer sends (the perceiver's context).

The subject content_id is the STABLE key the tag is stored under in ``tags.by_subject`` — the LP-325
gather contract keys id.* facts under the DOCUMENT subject so a gather tag and its filter tag
co-locate.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from app.verification.snapshot.documents_section import _DESC_REDACT, _REDACTED
from app.verification.snapshot.fields import Field
from app.verification.snapshot.model import DocumentEntry, ListRow, Snapshot, TransactionRecord
from app.verification.snapshot.pii import PiiField
from app.verification.snapshot.traversal import all_transactions

# LP-444 — the default per-list row cap: how many rows of a generic list are serialised into an AI
# context before it is capped + MARKED truncated. A cap bounds the token cost (a credit report can carry
# 30-50 tradelines); the truncation marker makes an unmatched item "unknown", never a confirmed absence.
# A group may raise/lower it (``AiGroup.list_row_cap``) — per-group, so a dense report gets more rows.
_DEFAULT_LIST_ROW_CAP = 50


@dataclass(frozen=True)
class ContextOptions:
    """Per-group opt-ins that shape an AI context (LP-444). The DEFAULT changes nothing — a group that
    passes the default gets a byte-identical context, so every existing group is unaffected.

    * ``include_lists`` — serialise a document's generic lists (LP-437 ``entry.lists``) into the context.
    * ``list_row_cap`` — the per-list row cap (default 50), raisable per group for a dense list.
    * ``include_stated_liabilities`` — add the app's file-level MISMO liabilities to a BORROWER context
      (the comparison set a report-vs-app rule like CR-4 matches report tradelines against).
    * ``include_untyped`` — serialise a document's MARKED-UNTYPED section (LP-463 ``entry.untyped_extraction``
      — the Tier-3 scoped free-extraction output) into an AI cross-source context. Opt-in exactly like
      ``include_lists``: a group that leaves it False gets a byte-identical context. This is the ONLY way the
      untyped section reaches a reasoner; NO deterministic rule reads it."""

    include_lists: bool = False
    list_row_cap: int = _DEFAULT_LIST_ROW_CAP
    include_stated_liabilities: bool = False
    include_untyped: bool = False


_DEFAULT_CONTEXT_OPTIONS = ContextOptions()

# The loan-level production subject key (a single subject, like the rule-engine LOAN_SUBJECT).
LOAN_SUBJECT = "loan"

# The classifier's unclassified document-type value (str form; a document may also be None-typed). The
# doc-type filters (here + LP-377-D's dispatcher gate) FAIL OPEN on it — an abstained classification is
# never used to drop a document.
_UNKNOWN_DOC_TYPE = "unknown"

RawField = Field | PiiField
Subject = tuple[str, object]  # (content_id, the raw object to read from)


@dataclass(frozen=True)
class SubjectType:
    """One subject type's production hooks."""

    enumerate: Callable[[Snapshot], list[Subject]]
    read_field: Callable[[object, str], RawField | None]
    # ``applies_to`` (LP-385) = the group's declared document types (or None = all). Only a context that
    # GATHERS documents (the borrower context) uses it — to filter the gathered set to the group's relevant
    # doc-types; every other subject ignores it. ``ContextOptions`` (LP-444) carries the group's list /
    # cap / liabilities opt-ins; the document + borrower builders use them, other subjects ignore them.
    build_context: Callable[[object, frozenset[str] | None, ContextOptions], dict[str, object]]


# --------------------------------------------------------------------------- #
# transaction
# --------------------------------------------------------------------------- #
_TXN_FIELDS = {
    "date": "date",
    "amount": "amount",
    "direction": "direction",
    "description": "description",
}


def _txn_enumerate(snapshot: Snapshot) -> list[Subject]:
    return [(txn.content_id, txn) for txn in all_transactions(snapshot)]


def _txn_read_field(raw: object, field: str) -> RawField | None:
    assert isinstance(raw, TransactionRecord)
    attr = _TXN_FIELDS.get(field)
    return getattr(raw, attr) if attr is not None else None


def _txn_context(
    raw: object, _applies_to: frozenset[str] | None, _opts: ContextOptions
) -> dict[str, object]:
    assert isinstance(raw, TransactionRecord)
    return {
        "date": _field_value(raw.date),
        "amount": _field_value(raw.amount),
        "direction": _field_value(raw.direction),
        "description": _field_value(raw.description),
    }


# --------------------------------------------------------------------------- #
# document
# --------------------------------------------------------------------------- #
def _doc_enumerate(snapshot: Snapshot) -> list[Subject]:
    if snapshot.documents.absent:
        return []
    return [(entry.content_id, entry) for entry in snapshot.documents.entries]


def _doc_read_field(raw: object, field: str) -> RawField | None:
    assert isinstance(raw, DocumentEntry)
    return raw.fields.get(field)


def _doc_context(
    raw: object, _applies_to: frozenset[str] | None, opts: ContextOptions
) -> dict[str, object]:
    assert isinstance(raw, DocumentEntry)
    # Send the document's present fields as {name: value/display} — PiiFields contribute only their
    # MASKED display (never a raw value), so nothing raw-PII leaves in the AI prompt.
    fields: dict[str, object] = {"document_type": raw.document_type}
    for name, field in raw.fields.items():
        if isinstance(field, PiiField):
            fields[name] = field.display if field.is_present else None
        elif field.is_present:
            fields[name] = field.value
    # LP-444 — opt-in: add the document's generic lists (capped, truncation-marked, PII-scrubbed). A group
    # that did not declare include_lists gets a byte-identical context (this branch never runs for it).
    if opts.include_lists and raw.lists:
        fields["lists"] = _serialize_lists(raw, opts.list_row_cap)
    # LP-463 — opt-in: add the document's MARKED-UNTYPED section (Tier-3 scoped free extraction). It is
    # already identifier-scrubbed at snapshot-build time; a group that did not declare include_untyped gets a
    # byte-identical context. This is the ONLY path from the untyped section to a reasoner — never a rule.
    if opts.include_untyped and raw.untyped_extraction:
        fields["untyped_extraction"] = _serialize_untyped(raw.untyped_extraction, opts.list_row_cap)
    return fields


# --------------------------------------------------------------------------- #
# loan (a single subject) — reads MISMO facts
# --------------------------------------------------------------------------- #
def _loan_enumerate(snapshot: Snapshot) -> list[Subject]:
    return [(LOAN_SUBJECT, snapshot)]


def _loan_read_field(raw: object, field: str) -> RawField | None:
    assert isinstance(raw, Snapshot)
    if raw.mismo.absent:
        return None
    return raw.mismo.facts.get(field)


def _loan_context(
    raw: object, _applies_to: frozenset[str] | None, _opts: ContextOptions
) -> dict[str, object]:
    assert isinstance(raw, Snapshot)
    if raw.mismo.absent:
        return {}
    return {name: _field_value(field) for name, field in raw.mismo.facts.items()}


# --------------------------------------------------------------------------- #
# liability (LP-483)
#
# ⚠️ WHY THIS FAMILY DID NOT EXIST, AND WHAT IT UNBLOCKS. ``KNOWN_SUBJECTS`` held only
# transaction/document/loan/borrower, so a tag declared with ``entity: liability`` had nowhere to be
# produced — the loader rejects an unknown subject. That is why ALL 14 ``liab.*`` tags sit in
# ``fact_tags.csv`` DECLARED AND UNPRODUCED (account_type, balance, dti_payment, in_application,
# is_disputed, monthly_payment, heloc_credit_limit, derogatory_date/_type, excluded_paid_off,
# has_open_judgment_lien, is_derogatory, payment_status, representative_score). This family is therefore
# NOT CR-1 overhead — it is the missing floor under the whole credit tag vocabulary.
#
# ⚠️ IDENTITY. The subject ids MUST equal what the rule-engine's ``per_liability`` enumerator emits, or a
# tag materialises under an id no rule reads. Both call ``liability_rows`` (rule_engine/enumerators.py) —
# ONE derivation, so they cannot drift.
# --------------------------------------------------------------------------- #

# The two sources name the same fact differently. This maps a DECLARATION's canonical field name to each
# source's own column. ⚠️ It normalises NAMES ONLY — never values: mapping a bureau's ``REV`` to the
# vocabulary's ``revolving`` would be the open-vocabulary CLASSIFICATION that ADR-353 defers to Priya,
# which is why ``liab.account_type`` has no parsed producer (see LP-483's ticket doc).
_LIABILITY_FIELD_ALIASES: dict[str, dict[str, str]] = {
    # credit-report tradeline row (LP-479 ListSpec field names)
    "credit_report_reported": {
        "account_type": "account_type",
        "monthly_payment": "monthly_payment",
        "balance": "balance",
        "creditor_name": "creditor_name",
        "is_disputed": "is_disputed",
        "payment_status": "payment_status",
        # ⚠️ `heloc_credit_limit` was REMOVED here (reported finding). It aliased the vocabulary's
        # HELOC-specific limit onto `credit_limit_or_high_credit`, which every REVOLVING tradeline
        # populates — so the mapping is only true when the account IS a HELOC, and deciding that is the
        # open-vocabulary classification this very block says it refuses to do. It was unconditional, and
        # the D5 guard treats these keys as the legal universe, so declaring
        # `liab.heloc_credit_limit: {mode: parsed, subject: liability}` would have passed every check and
        # fed HCLTV a credit card's limit as a HELOC limit. Restore only behind an account-type classifier.
    },
    # MISMO stated liability (the four fields mismo_section projects — no account number exists)
    "mismo_stated": {
        "account_type": "type",
        "monthly_payment": "monthly_payment",
        "balance": "unpaid_balance",
        "creditor_name": "holder_name",
    },
}


def _liability_enumerate(snapshot: Snapshot) -> list[Subject]:
    # LAZY IMPORT — load-bearing, do NOT hoist (the rule_engine ↔ tag_materialization init-order
    # cycle ``derived.py`` already navigates the same way).
    from app.verification.rule_engine.enumerators import liability_rows

    return [(row.subject_id, row) for row in liability_rows(snapshot)]


def _liability_read_field(raw: object, field: str) -> RawField | None:
    """The raw field for a declaration's canonical name, resolved through the source's alias map.

    An unknown canonical name, or a name the source does not carry (the MISMO leg has no
    ``is_disputed``), yields None → an ABSENT tag. Fail-closed: absent ≠ empty ≠ a default.
    """
    from app.verification.rule_engine.enumerators import LiabilityRow

    assert isinstance(raw, LiabilityRow)
    column = _LIABILITY_FIELD_ALIASES.get(raw.source, {}).get(field)
    return raw.fields.get(column) if column is not None else None


def _liability_context(
    raw: object, _applies_to: frozenset[str] | None, _opts: ContextOptions
) -> dict[str, object]:
    """This liability's own facts, under the family's CANONICAL names, PII-scrubbed.

    Two reported findings shaped this:

    * **Canonical names, not the source's own columns.** Both legs of the union arrive under ONE subject
      family, so splatting ``raw.fields`` verbatim gave a prompt two different schemas — ``type`` /
      ``unpaid_balance`` / ``holder_name`` from MISMO against ``account_type`` / ``balance`` /
      ``creditor_name`` from a tradeline — and a single group would silently under-read one leg. The
      alias map is applied INVERTED here, so the two legs are comparable. A column with no canonical
      name (a tradeline field no declaration reads) is still passed through under its own name rather
      than dropped, so nothing is hidden from a reasoner.
    * **The universal PII backstop.** Values go through :func:`_scrub_list_value`, like every other
      list-derived context. A ``ListRow.fields`` value is a plain ``Field``, never a ``PiiField``, and
      ``ListSpec.redact`` covers only the fields a spec NAMED — so an account number a bureau prints
      inside ``creditor_name`` would otherwise reach the model unscrubbed.

    ⚠️ There is deliberately NO ``include_stated_liabilities`` opt-in. The docstring previously promised
    one "the SAME opt-in the borrower context uses", but the body never read ``opts`` and never could:
    ``load_ai_groups`` raises ``DeclarationError`` for any non-borrower group that sets that flag. A
    liability-subject group wanting the app's stated set is a real design question (this family already
    carries BOTH sources as sibling subjects), not a flag to smuggle in.
    """
    from app.verification.rule_engine.enumerators import LiabilityRow

    assert isinstance(raw, LiabilityRow)
    canonical = {
        column: name for name, column in _LIABILITY_FIELD_ALIASES.get(raw.source, {}).items()
    }
    return {
        "liability_source": raw.source,
        **{
            canonical.get(column, column): _scrub_list_value(_field_value(field))
            for column, field in sorted(raw.fields.items())
        },
    }


def _field_value(field: RawField) -> object:
    if isinstance(field, PiiField):
        return field.display if field.is_present else None
    return field.value if field.is_present else None


# --------------------------------------------------------------------------- #
# LP-444 — serialise a document's GENERIC LISTS (LP-437) into an AI context, opt-in.
# --------------------------------------------------------------------------- #
def _scrub_list_value(value: object) -> object:
    """Belt-and-braces PII scrub for one list-row value before it reaches a reasoner (LP-444 A4).

    A ``ListRow.fields`` value is a PLAIN ``Field`` (model.py) — NEVER a ``PiiField`` — so unlike a
    document's top-level fields (which contribute only a PiiField's MASKED display), a list-row value
    carries whatever the extractor stored (list-row PII is not ``_PII_FIELDS``-routed). The snapshot layer
    already applies a PER-LIST DECLARED redact to the known account/SSN row fields (the LP-443 review
    backstop — ``ListSpec.redact`` on ``_TRADELINES_LIST`` etc.), but that only covers the fields a spec
    named. THIS is the UNIVERSAL backstop at the context boundary — the last gate before an AI reasoner,
    where a leak is worst (sending an unmasked account/SSN to a reasoner is worse than the unmasked
    catch-all, which never leaves the database). Every string value is run through the SAME 9+-digit scrub
    the snapshot uses (``documents_section._DESC_REDACT``), so even an UNDECLARED field or a future list
    cannot leak: a masked last-4 / date / short id is kept (an honest signal), a long identifier becomes
    ``[redacted]``. Non-string values (numbers/bools) pass through — they cannot carry an identifier string."""
    if isinstance(value, str):
        return _DESC_REDACT.sub(_REDACTED, value)
    return value


def _serialize_lists(entry: DocumentEntry, cap: int) -> dict[str, object]:
    """A document's generic lists serialised for an AI context (LP-444) — opt-in, capped, scrubbed, marked.

    Each list becomes ``{"rows": [...], ["truncated": true, "shown": M, "total": N]}``. The rows are the
    first ``cap`` (the group's ``list_row_cap``, a token bound); when a list is longer the ``truncated``
    MARKER is added so a reasoner knows an item it cannot match may be beyond the shown rows — the prompt
    turns that into "answer unknown, never a confirmed absence" (the count-cross-check discipline applied
    to reasoning). Every value is PII-scrubbed (:func:`_scrub_list_value`). Absent row fields are omitted
    (absent≠empty). An empty ``lists`` map yields ``{}`` — a document with no wired list adds nothing."""
    out: dict[str, object] = {}
    for name, rows in entry.lists.items():
        shown = rows[:cap]
        serial_rows = [_serialize_row(row) for row in shown]
        block: dict[str, object] = {"rows": serial_rows}
        if len(rows) > cap:
            block["truncated"] = True
            block["shown"] = len(shown)
            block["total"] = len(rows)
        out[name] = block
    return out


def _serialize_untyped(untyped: dict[str, object], cap: int) -> dict[str, object]:
    """The marked-untyped section for an AI context (LP-463) — capped + truncation-marked like the lists.

    ``untyped`` is already identifier-scrubbed at snapshot-build time. Any LIST-valued member longer than
    ``cap`` (the group's ``list_row_cap``) is trimmed to the first ``cap`` items with a parallel
    ``<name>__truncated`` marker (shown/total) — so a reasoner knows an item may lie beyond what's shown,
    the same count-cross-check discipline the lists use. Scalar members (a type guess, a summary) pass through."""
    out: dict[str, object] = {}
    for name, value in untyped.items():
        if isinstance(value, list) and len(value) > cap:
            out[name] = value[:cap]
            out[f"{name}__truncated"] = {"shown": cap, "total": len(value)}
        else:
            out[name] = value
    return out


_LIABILITY_KEY = re.compile(r"^liability\.(\d+)\.(.+)$")


def _stated_liabilities(snapshot: Snapshot) -> list[dict[str, object]]:
    """The app's FILE-LEVEL stated liabilities (MISMO ``liability.{k}.*``) grouped by index (LP-444).

    The comparison set a report-vs-app rule (CR-4: undisclosed tradeline) matches report tradelines
    against. File-level (shared across borrowers, no per-borrower attribution in the flat MISMO facts), so
    each borrower context that opts in sees the full set. Values go through ``_field_value`` (a masked
    PiiField display only) — though stated liabilities carry no account-number column (mismo_section), so
    there is no raw identifier here. Sorted by index for a deterministic, run-independent context."""
    if snapshot.mismo.absent:
        return []
    by_index: dict[int, dict[str, object]] = {}
    for name, field in snapshot.mismo.facts.items():
        m = _LIABILITY_KEY.match(name)
        if m is not None:
            by_index.setdefault(int(m.group(1)), {})[m.group(2)] = _field_value(field)
    return [by_index[k] for k in sorted(by_index)]


def _serialize_row(row: ListRow) -> dict[str, object]:
    """One list row → ``{field: scrubbed value}`` (present fields only)."""
    return {
        name: _scrub_list_value(field.value)
        for name, field in row.fields.items()
        if field.is_present
    }


# --------------------------------------------------------------------------- #
# borrower (LP-332) — one subject per borrower, keyed by borrower_id, reading MISMO borrower.{n}.*
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class BorrowerSubject:
    """A borrower production subject: the resolved id + its MISMO index + the snapshot to read from.

    The id is the ``belongs_to`` UUID (from the LP-332 ``borrower.{n}.borrower_id`` link), so a tag
    keyed under it MEETS the LP-331 consumer (``_per_borrower`` reads ``by_subject[borrower_id]``). The
    index is how this borrower's facts are read (``borrower.{index}.<field>``); the snapshot lets a
    borrower recipe also gather this borrower's DOCUMENTS (its ``belongs_to`` facts)."""

    borrower_id: str
    index: int
    snapshot: Snapshot


_BORROWER_ID_KEY = re.compile(r"^borrower\.(\d+)\.borrower_id$")


def _borrower_enumerate(snapshot: Snapshot) -> list[Subject]:
    """One subject per MISMO borrower that carries the LP-332 id link, keyed by that borrower_id.

    A borrower group WITHOUT a ``borrower_id`` fact is SKIPPED (no attribution is safe → its
    borrower-keyed tags stay absent → the rule couldnt_checks; never a name-guessed attribution).

    Enumerates EVERY ``borrower.{n}.borrower_id`` fact present (sorted by index) rather than assuming
    contiguous indices from 1 — a gap (a co-borrower dropped mid-build, an emitter change) must not
    silently truncate the borrower set, which would leave a real borrower un-checked with no signal."""
    if snapshot.mismo.absent:
        return []
    indices = sorted(
        int(m.group(1)) for name in snapshot.mismo.facts if (m := _BORROWER_ID_KEY.match(name))
    )
    subjects: list[Subject] = []
    seen: set[str] = set()
    for index in indices:
        id_field = snapshot.mismo.facts[f"borrower.{index}.borrower_id"]
        borrower_id = str(_field_value(id_field) or "")  # None/PII-display-safe extraction
        if (
            borrower_id and borrower_id not in seen
        ):  # a duplicate/blank id is unsafe → skip (fail-closed)
            seen.add(borrower_id)
            subjects.append((borrower_id, BorrowerSubject(borrower_id, index, snapshot)))
    return subjects


def _borrower_read_field(raw: object, field: str) -> RawField | None:
    assert isinstance(raw, BorrowerSubject)
    if raw.snapshot.mismo.absent:
        return None
    return raw.snapshot.mismo.facts.get(f"borrower.{raw.index}.{field}")


def _borrower_context(
    raw: object, applies_to: frozenset[str] | None, opts: ContextOptions
) -> dict[str, object]:
    """The per-borrower AI context: this borrower's MISMO facts PLUS the documents ATTRIBUTED to them
    (LP-385). The generic per-borrower-over-documents primitive: a group asking a CROSS-document question
    (income_stability's 2-year history / decline / continuance) sees all of ONE borrower's documents at
    once — the per-document framing that made those questions structurally unanswerable (LP-378: 0/120).

    Attribution is by ``belongs_to`` — the LP-202 EVIDENCE-based document→borrower link (the SSN/name
    resolved at upload), NEVER a guess. A document with no ``belongs_to`` (unattributed) is NOT gathered
    for any borrower — the context is honestly incomplete and the tag abstains with a reason, never a
    trend fabricated from a mis-attributed document (LP-332/LP-336: "never a guessed attribution"). Fields
    carry PiiField MASKED displays only (via ``_field_value``) — no raw PII leaves in the prompt.

    ``applies_to`` (the group's declared doc-types, LP-385 generalizing LP-377-D) filters the gathered set
    to the group's relevant document types, so a non-income document (a bank statement / tax bill / ID) is
    NOT sent to income_stability — the prompt's "ignore non-income" instruction is not a load-bearing
    filter (LP-378 measured that backstop failing: ~20 fabricated income values). FAILS OPEN exactly like
    the LP-377-D gate: an unknown / ``None`` type is kept (the classifier abstained — never dropped on a
    guess); only a KNOWN, confident type outside ``applies_to`` is excluded. ``applies_to=None`` → keep all.
    """
    assert isinstance(raw, BorrowerSubject)
    snapshot = raw.snapshot
    mismo: dict[str, object] = {}
    if not snapshot.mismo.absent:
        prefix = f"borrower.{raw.index}."
        mismo = {
            name[len(prefix) :]: _field_value(field)
            for name, field in snapshot.mismo.facts.items()
            if name.startswith(prefix)
        }
    documents: list[dict[str, object]] = []
    if not snapshot.documents.absent:
        for entry in snapshot.documents.entries:
            attributed = entry.belongs_to is not None and any(
                str(ref.borrower_id) == raw.borrower_id for ref in entry.belongs_to
            )
            if not attributed:
                continue  # unattributed → not this borrower's → the context is honestly incomplete
            # Fail-open doc-type filter (LP-385): drop only a KNOWN, confident type the group's applies_to
            # excludes; keep None/"unknown" (classifier abstained) and everything when applies_to is None.
            if (
                applies_to is not None
                and entry.document_type not in (None, _UNKNOWN_DOC_TYPE)
                and entry.document_type not in applies_to
            ):
                continue
            doc: dict[str, object] = {
                "document_type": entry.document_type,
                "fields": {name: _field_value(field) for name, field in entry.fields.items()},
            }
            # LP-444 — opt-in: a gathered document's generic lists (e.g. a credit report's tradelines).
            # Only when the group declared include_lists → an existing borrower group is byte-unchanged.
            if opts.include_lists and entry.lists:
                doc["lists"] = _serialize_lists(entry, opts.list_row_cap)
            documents.append(doc)
    context: dict[str, object] = {"borrower_mismo": mismo, "documents": documents}
    # LP-444 — opt-in: the app's file-level stated liabilities (the CR-4 comparison set). Off by default,
    # so an existing borrower group (income_stability) is byte-unchanged; only a group that declares it
    # (credit_profile) sees the liabilities alongside the gathered documents' lists.
    if opts.include_stated_liabilities:
        context["stated_liabilities"] = _stated_liabilities(snapshot)
    return context


def loan_borrower_roster(snapshot: Snapshot) -> list[str]:
    """The loan's borrower display names (LP-390-8a) — the comparison roster a DOCUMENT group needs to judge
    whether a document's stated party is a borrower on the loan (``stmt.owner_matches_borrower``: the
    ``_doc_context`` sends only the statement's OWN fields, so without this the group had no names to compare
    against and abstained structurally on every file — LP-390-5/LP-396's 5/5 ``unknown``).

    REUSES the LP-332 borrower resolution (``_borrower_enumerate`` + ``_borrower_read_field``) — no second
    identity path — and the PII-safe ``_field_value`` (a masked PiiField contributes only its masked display,
    never raw PII; a fully-masked name simply gives the model less to match on, an honest degrade to
    abstention, never a leak). A borrower with no readable name is skipped. Order follows the MISMO index."""
    names: list[str] = []
    for _borrower_id, subject in _borrower_enumerate(snapshot):
        parts = [
            _field_value(field)
            for name in ("first_name", "middle_name", "last_name")
            if (field := _borrower_read_field(subject, name)) is not None
        ]
        full = " ".join(str(p) for p in parts if p not in (None, ""))
        if full:
            names.append(full)
    return names


_SUBJECT_TYPES: dict[str, SubjectType] = {
    "transaction": SubjectType(_txn_enumerate, _txn_read_field, _txn_context),
    "document": SubjectType(_doc_enumerate, _doc_read_field, _doc_context),
    "loan": SubjectType(_loan_enumerate, _loan_read_field, _loan_context),
    "borrower": SubjectType(_borrower_enumerate, _borrower_read_field, _borrower_context),
    # LP-483 — the liability family (see its section above): the missing floor under all 14 liab.* tags.
    "liability": SubjectType(_liability_enumerate, _liability_read_field, _liability_context),
}

KNOWN_CONTEXT_BUILDERS = frozenset(_SUBJECT_TYPES)


def subject_type(key: str) -> SubjectType:
    """Resolve a subject-type key (raises on an unknown key)."""
    st = _SUBJECT_TYPES.get(key)
    if st is None:
        raise KeyError(f"unknown production subject {key!r} (known: {sorted(_SUBJECT_TYPES)})")
    return st


__all__ = [
    "KNOWN_CONTEXT_BUILDERS",
    "LOAN_SUBJECT",
    "RawField",
    "Subject",
    "SubjectType",
    "loan_borrower_roster",
    "subject_type",
]
