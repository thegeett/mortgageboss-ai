"""LF-6T3N labeling worksheet generator + scoring run (LP-337, corrected by LP-338).

**THIS IS A BIAS HUNT, NOT VALIDATION.** A clean result does NOT unblock the inert rules — activation needs
RATES across VARIED files + Priya's bars (see docs/tickets/LP-337.md / LP-338.md).

LP-338 fixed a conflation bug. LP-337's coverage function statically hardcoded the txn.* family and
declared id.* / income.* / asset.* "UNMEASURABLE" — it measured *what the fixture happened to contain*
(and even that only for txn.*), then LABELLED that as the file's inherent capacity and drew a false
conclusion (*"txn.* is the calibration ceiling; other families need files that don't exist"*). Two distinct
numbers were conflated. This module now reports THREE separate facts per AI tag (absent != empty != unwired
— the invariant this project handles at every other level, now at the coverage level):

1. **FILE CAPACITY** — how many instances the SNAPSHOT could support for the tag's DECLARED subject
   (`tag_production.yaml`). The labeling ceiling. Independent of wiring / ACTIVE_RULE_IDS.
2. **PIPELINE YIELD** — how many the wired pipeline produces today (a declared AI tag runs; a vocabulary
   tag with no tag_production declaration does not). A wiring fact, not a file fact.
3. **CONTENT-EMPTINESS** — a subject that EXISTS but carries no usable fields (a brokerage_statement with
   `fields = {}`) genuinely cannot be labeled — distinct from "no subject" and from "not wired".

Status per tag: ``labelable`` (capacity>0, wired) · ``wiring_gap`` (capacity>0, yield=0 — LP-333 bucket B,
reported not fixed) · ``content_empty`` (subjects exist but all field-empty) · ``no_subject`` (0 subjects).

Both halves reuse existing machinery UNCHANGED (LP-317 ``DimensionCalibration``; LP-334 ``ScoredTag`` /
``summarize``). Deterministic + KEYLESS for generation; the live scoring run is opt-in (``LP334_LIVE=1``).
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, replace
from pathlib import Path

from app.verification.eval.live_calibration import ScoredTag
from app.verification.rule_engine.registry import ACTIVE_RULE_IDS
from app.verification.snapshot.fields import Field
from app.verification.snapshot.model import DocumentEntry, Snapshot, TransactionRecord
from app.verification.snapshot.pii import PiiField
from app.verification.snapshot.tag import Tag
from app.verification.tag_materialization.ai import Reasoner, produce_ai_group_tags
from app.verification.tag_materialization.declarations import (
    ProductionMode,
    TagDeclaration,
    load_ai_groups,
    load_declarations,
)

_CREDIT = "credit"
_FREE_TEXT = frozenset({"txn.counterparty", "txn.source_reference"})


@dataclass(frozen=True)
class _TagMeta:
    """Per-tag eval metadata (bucket + scoring + rules). ``wired`` marks a tag the DECLARED tag-production
    pipeline produces; a vocabulary AI tag with no declaration (the Stage-B sourcing tags) is wired=False
    -> a wiring gap, not an unmeasurable tag."""

    tag_id: str
    scoring: str  # "enum" | "string" | "free_text_deferred"
    bucket: str  # "mechanical" | "judgment"
    consuming_rules: tuple[str, ...]
    money_in_only: bool = False
    wired: bool = True


@dataclass(frozen=True)
class _Group:
    """An AI group's coverage metadata: its subject kind + (for document tags) the document_types whose
    content the group's tags can be labeled from. The doc-type applicability is eval metadata — the
    architecture keys AI groups by subject only and relies on the prompt to abstain off-type."""

    subject_kind: str  # "transaction" | "document"
    applicable_types: tuple[str, ...]  # () for transaction (all txns)
    tags: tuple[_TagMeta, ...]


# The coverage map. Document-subject applicability is the honest capacity proxy (which doc types carry the
# fields a tag is labeled from). Buckets: MECHANICAL = a factual read (Geet); JUDGMENT = a domain call
# (Priya) — incl. id.current_address_type, the REAL-DL check of LP-335's FINDING-1 fix.
_GROUPS: tuple[_Group, ...] = (
    _Group(
        "transaction",
        (),
        (
            _TagMeta("txn.is_money_in", "enum", "mechanical", ("AS-1", "AS-7", "AS-8", "AS-12")),
            _TagMeta(
                "txn.apparent_category",
                "enum",
                "judgment",
                ("AS-1", "AS-2", "AS-5", "AS-12", "IN-1"),
            ),
        ),
    ),
    # Stage-B sourcing tags: vocabulary AI tags with NO tag_production declaration (produced by the
    # separate tag_correlation pass, not the generic pipeline) -> wired=False -> a wiring gap.
    _Group(
        "transaction",
        (),
        (
            _TagMeta(
                "txn.has_identified_source",
                "enum",
                "judgment",
                ("AS-1", "AS-2", "AS-5"),
                money_in_only=True,
                wired=False,
            ),
            _TagMeta(
                "txn.counterparty",
                "free_text_deferred",
                "judgment",
                ("AS-2", "AS-5", "AS-12", "FR-5"),
                money_in_only=True,
                wired=False,
            ),
            _TagMeta(
                "txn.source_reference",
                "free_text_deferred",
                "judgment",
                ("AS-1", "AS-5"),
                money_in_only=True,
                wired=False,
            ),
        ),
    ),
    _Group(
        "document",
        ("drivers_license", "passport", "state_id"),
        (_TagMeta("id.name_normalized", "string", "mechanical", ("ID-1",)),),
    ),
    _Group(
        "document",
        ("drivers_license", "passport", "state_id"),
        (
            _TagMeta("id.address_normalized", "string", "mechanical", ("ID-4",)),
            _TagMeta(
                "id.current_address_type", "enum", "judgment", ("ID-4",)
            ),  # LP-335 real-DL check (high value)
        ),
    ),
    _Group(
        "document",
        ("title_commitment",),
        (_TagMeta("id.title_vesting_consistent", "enum", "judgment", ("ID-7",)),),
    ),
    _Group(
        "document",
        ("power_of_attorney",),
        (_TagMeta("id.poa_present_and_acceptable", "enum", "judgment", ("ID-9",)),),
    ),
    _Group(
        "document",
        ("pay_stub", "w2"),
        (
            _TagMeta("income.type", "enum", "judgment", ("IN-1",)),
            _TagMeta("income.documented_monthly", "string", "mechanical", ("IN-1",)),
            _TagMeta("income.qualifying_monthly", "string", "judgment", ("IN-1",)),
        ),
    ),
    _Group(
        "document",
        ("pay_stub", "w2", "voe", "employment_offer_letter"),
        (_TagMeta("income.employer_normalized", "string", "mechanical", ("IN-5",)),),
    ),
    _Group(
        "document",
        ("voe", "employment_offer_letter"),
        (
            _TagMeta("income.voe_present", "enum", "judgment", ("IN-2",)),
            _TagMeta("income.future_employment", "enum", "judgment", ("IN-2",)),
            _TagMeta("income.offer_letter_present", "enum", "judgment", ("IN-2",)),
        ),
    ),
    _Group(
        "document",
        ("pay_stub", "w2"),
        (
            _TagMeta("income.has_2yr_history", "enum", "judgment", ("IN-3",)),
            _TagMeta("income.is_declining", "enum", "judgment", ("IN-1",)),
            _TagMeta("income.same_line_of_work", "enum", "judgment", ("IN-3",)),
            _TagMeta("income.continuance_3yr", "enum", "judgment", ("IN-4",)),
        ),
    ),
    _Group(
        "document",
        ("bank_statement", "investment_account", "brokerage_statement"),
        (
            _TagMeta("stmt.owner_matches_borrower", "enum", "judgment", ("AS-6",)),
            _TagMeta("stmt.is_reserve_eligible", "enum", "judgment", ("AS-4",)),
        ),
    ),
    _Group(
        "document",
        ("investment_account", "brokerage_statement", "retirement_account"),
        (
            _TagMeta("asset.liquidation_terms", "enum", "judgment", ("AS-11",)),
            _TagMeta("asset.usable_value", "string", "judgment", ("AS-4",)),
        ),
    ),
)


def _fv(field: object) -> str:
    # A PiiField contributes only its MASKED display (never a raw value) — safe context for the labeler,
    # not dropped. A plain Field contributes its value; absent/None → "".
    if isinstance(field, PiiField):
        return (field.display or "") if field.is_present else ""
    if not isinstance(field, Field) or field.absent or field.value is None:
        return ""
    return str(field.value)


def _doc_has_content(doc: DocumentEntry) -> bool:
    return bool(doc.fields)


def _txn_context(txn: TransactionRecord) -> str:
    parts = {
        "date": txn.date,
        "amount": txn.amount,
        "direction": txn.direction,
        "description": txn.description,
    }
    return "; ".join(f"{k}={_fv(v)}" for k, v in parts.items())


def _doc_context(doc: DocumentEntry) -> str:
    return "; ".join(f"{k}={_fv(v)}" for k, v in doc.fields.items())


@dataclass(frozen=True)
class TagCapacity:
    """The three facts for one AI tag on this file — never conflated (LP-338)."""

    tag_id: str
    subject_kind: str
    scoring: str
    bucket: str
    consuming_rules: tuple[str, ...]
    capacity: int  # labelable instances (subject present + content present)
    content_empty: int  # subjects present but field-empty (cannot be labeled)
    wired: bool  # produced by the declared tag-production pipeline today

    @property
    def rule_live(self) -> bool:
        return any(r in ACTIVE_RULE_IDS for r in self.consuming_rules)

    @property
    def pipeline_yield(self) -> int:
        return self.capacity if self.wired else 0

    @property
    def status(self) -> str:
        if self.capacity > 0:
            return "labelable" if self.wired else "wiring_gap"
        if self.content_empty > 0:
            return "content_empty"
        return "no_subject"


def _transactions(snapshot: Snapshot) -> list[TransactionRecord]:
    return [t for doc in snapshot.documents.entries for t in (doc.transactions or ())]


def compute_capacity(snapshot: Snapshot) -> list[TagCapacity]:
    """Per AI tag: file_capacity (labelable subjects) · content_empty (subjects present but field-empty) ·
    wired. Deterministic + KEYLESS (from the snapshot + the declared subjects; no AI, no key). Capacity is
    a FILE fact (does the subject + its content exist), yield a WIRING fact — never conflated."""
    docs_by_type: dict[str, list[DocumentEntry]] = {}
    for d in snapshot.documents.entries:
        docs_by_type.setdefault(d.document_type or "", []).append(d)
    txns = _transactions(snapshot)
    credits = [t for t in txns if _fv(t.direction) == _CREDIT]

    out: list[TagCapacity] = []
    for group in _GROUPS:
        for meta in group.tags:
            if group.subject_kind == "transaction":
                pool = credits if meta.money_in_only else txns
                cap = sum(1 for t in pool if _fv(t.description) or _fv(t.amount))
                empty = len(pool) - cap
            else:
                applicable = [d for t in group.applicable_types for d in docs_by_type.get(t, [])]
                cap = sum(1 for d in applicable if _doc_has_content(d))
                empty = sum(1 for d in applicable if not _doc_has_content(d))
            out.append(
                TagCapacity(
                    meta.tag_id,
                    group.subject_kind,
                    meta.scoring,
                    meta.bucket,
                    meta.consuming_rules,
                    cap,
                    empty,
                    meta.wired,
                )
            )
    return out


# --------------------------------------------------------------------------- #
# The worksheet rows (one per labelable instance) — context-bearing, prediction-free
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class WorksheetRow:
    bucket: str
    tag_id: str
    subject_id: str
    subject_kind: str
    document_type: str
    scoring: str
    allowed_values: str
    consuming_rules: str
    rule_status: str  # "LIVE" | "inert"
    context: str  # enough to label WITHOUT the file
    golden_label: str = ""
    labeler_note: str = ""


_HEADERS = (
    "tag_id",
    "subject_id",
    "subject_kind",
    "document_type",
    "scoring",
    "allowed_values",
    "consuming_rules",
    "rule_status",
    "context",
    "golden_label",
    "labeler_note",
)


def _allowed_str(tag_id: str, decls: dict[str, TagDeclaration]) -> str:
    decl = decls.get(tag_id)
    if decl is not None and decl.allowed_values:
        return " | ".join(decl.allowed_values)
    return "(free text)"


def build_worksheet(snapshot: Snapshot) -> list[WorksheetRow]:
    """Enumerate every LABELABLE AI-tag instance (subject present + content present) — deterministically,
    from the snapshot (no AI, no key). One row per (tag, subject); document rows carry the document's
    fields as context, txn rows carry date/amount/direction/description. Content-empty subjects (a
    brokerage_statement with no fields) are NOT rows — they cannot be labeled (reported in the coverage)."""
    decls = load_declarations()
    docs_by_type: dict[str, list[DocumentEntry]] = {}
    for d in snapshot.documents.entries:
        docs_by_type.setdefault(d.document_type or "", []).append(d)

    rows: list[WorksheetRow] = []
    for group in _GROUPS:
        for meta in group.tags:
            allowed = _allowed_str(meta.tag_id, decls)
            rule_status = (
                "LIVE" if any(r in ACTIVE_RULE_IDS for r in meta.consuming_rules) else "inert"
            )
            if group.subject_kind == "transaction":
                for doc in snapshot.documents.entries:
                    for txn in doc.transactions or ():
                        if meta.money_in_only and _fv(txn.direction) != _CREDIT:
                            continue
                        if not (_fv(txn.description) or _fv(txn.amount)):
                            continue
                        rows.append(
                            WorksheetRow(
                                meta.bucket,
                                meta.tag_id,
                                txn.content_id,
                                "transaction",
                                doc.document_type or "",
                                meta.scoring,
                                allowed,
                                ", ".join(meta.consuming_rules),
                                rule_status,
                                _txn_context(txn),
                            )
                        )
            else:
                for dtype in group.applicable_types:
                    for doc in docs_by_type.get(dtype, []):
                        if not _doc_has_content(doc):
                            continue
                        rows.append(
                            WorksheetRow(
                                meta.bucket,
                                meta.tag_id,
                                doc.content_id,
                                "document",
                                dtype,
                                meta.scoring,
                                allowed,
                                ", ".join(meta.consuming_rules),
                                rule_status,
                                _doc_context(doc),
                            )
                        )
    return rows


def render_csv(rows: list[WorksheetRow]) -> str:
    buf = io.StringIO()
    writer = csv.writer(
        buf, lineterminator="\n"
    )  # "\n" — matches the repo's mixed-line-ending hook
    writer.writerow(_HEADERS)
    for r in rows:
        writer.writerow(
            [
                r.tag_id,
                r.subject_id,
                r.subject_kind,
                r.document_type,
                r.scoring,
                r.allowed_values,
                r.consuming_rules,
                r.rule_status,
                r.context,
                r.golden_label,
                r.labeler_note,
            ]
        )
    return buf.getvalue()


def _existing_labels(path: Path) -> dict[tuple[str, str], tuple[str, str]]:
    """Read a previously-written worksheet -> {(tag_id, subject_id): (golden_label, labeler_note)} for the
    FILLED rows, so a regeneration never clobbers human labels already entered."""
    if not path.is_file():
        return {}
    kept: dict[tuple[str, str], tuple[str, str]] = {}
    for row in csv.DictReader(io.StringIO(path.read_text(encoding="utf-8"))):
        label = (row.get("golden_label") or "").strip()
        note = (row.get("labeler_note") or "").strip()
        if label or note:
            kept[(row["tag_id"].strip(), row["subject_id"].strip())] = (label, note)
    return kept


def write_worksheets(snapshot: Snapshot, out_dir: Path) -> dict[str, Path]:
    """Write the split worksheets (mechanical = Geet, judgment = Priya), PRESERVING any labels already
    filled in the existing files (merge by the stable (tag_id, subject_id) key)."""
    rows = build_worksheet(snapshot)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    for bucket, name in (
        ("mechanical", "lf6t3n-labels-mechanical.csv"),
        ("judgment", "lf6t3n-labels-judgment.csv"),
    ):
        path = out_dir / name
        prior = _existing_labels(path)
        merged = [
            replace(r, golden_label=prior[key][0], labeler_note=prior[key][1])
            if (key := (r.tag_id, r.subject_id)) in prior
            else r
            for r in rows
            if r.bucket == bucket
        ]
        path.write_text(render_csv(merged), encoding="utf-8")
        written[bucket] = path
    return written


def coverage_report(snapshot: Snapshot) -> str:
    """The corrected coverage: per AI tag -> capacity | yield | status | scoring | live? -- capacity and
    yield NEVER conflated. Deterministic (from the snapshot; no AI)."""
    lines = [
        "=" * 104,
        "LF-6T3N COVERAGE (LP-338) — capacity != yield != content-empty. A BIAS HUNT, not validation.",
        "=" * 104,
    ]
    lines.append(
        f"{'tag':<30} {'cap':>4} {'yield':>6} {'empty':>6}  {'status':<13} {'scoring':<18} {'live?':<6} rules"
    )
    for c in sorted(compute_capacity(snapshot), key=lambda x: x.tag_id):
        lines.append(
            f"{c.tag_id:<30} {c.capacity:>4} {c.pipeline_yield:>6} {c.content_empty:>6}  "
            f"{c.status:<13} {c.scoring:<18} {('LIVE' if c.rule_live else 'inert'):<6} {', '.join(c.consuming_rules)}"
        )
    lines.append("-" * 104)
    lines.append(
        "capacity>0 & yield=0 = WIRING GAP (LP-333 bucket B — reported, not fixed). "
        "capacity=0 & empty>0 = content-empty (e.g. brokerage_statement fields={})."
    )
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# PHASE 2 — the scoring run (live, opt-in; keyless via stub). Reuses LP-334's ScoredTag/summarize.
# --------------------------------------------------------------------------- #
def load_golden(csv_text: str) -> dict[tuple[str, str], str]:
    """A FILLED worksheet -> {(tag_id, subject_id): golden_label}; unlabeled rows skipped."""
    golden: dict[tuple[str, str], str] = {}
    for row in csv.DictReader(io.StringIO(csv_text)):
        label = (row.get("golden_label") or "").strip()
        if label:
            golden[(row["tag_id"].strip(), row["subject_id"].strip())] = label
    return golden


async def calibrate_lf6t3n(
    snapshot: Snapshot,
    golden: dict[tuple[str, str], str],
    *,
    reasoner: Reasoner | None = None,
) -> list[ScoredTag]:
    """Score the REAL reasoner over LF-6T3N against the filled worksheet — for every DECLARED AI enum/
    string tag with labels (not just txn.*: id/income/stmt/asset too, now the fixture supports them).
    Returns [] with no such labels (the correct outcome for an unfilled worksheet — NOT a crash). Free-text
    (FINDING-2) and Stage-B tags (not declared -> a separate producer) are NOT %-scored here."""
    decls = load_declarations()
    scorable = {
        t
        for (t, _s) in golden
        if t in decls and decls[t].mode is ProductionMode.AI and t not in _FREE_TEXT
    }
    if not scorable:
        return []
    groups = load_ai_groups()
    produced: dict[str, dict[str, Tag]] = {}
    for group_key in sorted({decls[t].data for t in scorable}):
        group = groups[group_key]
        allowed = {t: decls[t].allowed_values for t in group.tag_ids if t in decls}
        for sid, tags in (
            await produce_ai_group_tags(snapshot, group, allowed, reasoner=reasoner)
        ).items():
            produced.setdefault(sid, {}).update(tags)

    scored: list[ScoredTag] = []
    for (tag_id, subject_id), gold in sorted(golden.items()):
        if tag_id not in scorable:
            continue
        tag = produced.get(subject_id, {}).get(tag_id)
        scored.append(
            ScoredTag(
                doc_id=subject_id,
                tag_id=tag_id,
                golden=gold,
                predicted=None if tag is None else str(tag.value),
                confidence=None if tag is None else tag.confidence,
                reasoning=None if tag is None else tag.reasoning,
            )
        )
    return scored


__all__ = [
    "TagCapacity",
    "WorksheetRow",
    "build_worksheet",
    "calibrate_lf6t3n",
    "compute_capacity",
    "coverage_report",
    "load_golden",
    "render_csv",
    "write_worksheets",
]
