"""LP-337 — the LF-6T3N labeling worksheet generator (the instrument) + its scoring run.

**THIS IS A BIAS HUNT, NOT VALIDATION.** LF-6T3N is ONE conventional purchase (5 bank statements, 50
transactions). Only ``txn.*`` reaches a real n; everything else is n<=6 or n=0 on this file. A clean
result here does NOT unblock the inert rules — activation needs RATES across varied files + Priya's bars
(see docs/tickets/LP-337.md). LP-334's own conclusion: **n=2-5 finds BIASES, not RATES.**

Two halves, both reusing existing machinery UNCHANGED:

1. THE WORKSHEET (deterministic + KEYLESS). ``build_worksheet(snapshot)`` enumerates every scorable
   AI-tag INSTANCE the file would produce — one row per (tag, subject) — with enough document context to
   label it WITHOUT the file and WITHOUT the model's prediction (a labeler who sees the prediction anchors
   to it, so predictions are kept OUT of the artifact). Rows split by WHO should label:
     * MECHANICAL — a factual read from the document (Geet can label it): ``txn.is_money_in``.
     * JUDGMENT — a domain call (Priya; Geet's label would be another guess): ``txn.apparent_category``
       on an ambiguous wire, ``txn.has_identified_source`` (sourcing), and the free-text tags.
   Free-text tags (``txn.counterparty`` / ``txn.source_reference``) are enumerated for human review but
   marked DEFERRED from % scoring — string equality cannot honestly score them (FINDING-2, LP-334).

2. THE SCORING RUN (live, opt-in). ``calibrate_lf6t3n(snapshot, golden, reasoner=...)`` runs the REAL
   Stage-A structuring reasoner (the ``txn_stage_a`` group — AS-1's UNAUDITED prompt) over the snapshot
   and scores predicted-vs-golden, reusing LP-334's ``ScoredTag`` / ``summarize`` / ``failing_cases``.
   An UNFILLED worksheet → NO numbers + a clear message (the correct outcome, not a failure). Keyless-safe:
   a stub ``reasoner`` exercises the plumbing with no key; ``reasoner=None`` runs the real model.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from pathlib import Path

from app.verification.eval.live_calibration import ScoredTag
from app.verification.rule_engine.registry import ACTIVE_RULE_IDS
from app.verification.snapshot.fields import Field
from app.verification.snapshot.model import Snapshot
from app.verification.tag_materialization.ai import Reasoner, produce_ai_group_tags
from app.verification.tag_materialization.declarations import load_ai_groups, load_declarations

# The Stage-A structuring group (AS-1's txn_stage_a prompt) is the only group the GENERIC producer scores
# on this file; its two enum tags are the clean n=50 measurement this ticket prioritizes.
_STAGE_A_GROUP = "txn_stage_a"
_SCORABLE_STAGE_A = frozenset({"txn.is_money_in", "txn.apparent_category"})
_CREDIT = "credit"


@dataclass(frozen=True)
class TagCoverage:
    """One AI tag's coverage metadata for LF-6T3N — the auditable map that shapes the worksheet + report.

    ``money_in_only``: the Stage-B sourcing tags only exist for money-in CANDIDATES, so they are
    enumerated for credit-direction transactions (production's candidate search keys on ``is_money_in``;
    ``direction == "credit"`` is the deterministic snapshot proxy)."""

    tag_id: str
    subject_kind: str  # "transaction" (the only labelable kind on this file)
    scoring: str  # "enum" | "free_text_deferred"
    bucket: str  # "mechanical" | "judgment"
    producer: str  # a human label of the producing pass
    consuming_rules: tuple[str, ...]
    allowed_values: tuple[str, ...] | None
    money_in_only: bool = False

    @property
    def rule_live(self) -> bool:
        return any(r in ACTIVE_RULE_IDS for r in self.consuming_rules)


# The scorable txn.* family on LF-6T3N. Stage A = the generic txn_stage_a group; Stage B = the separate
# sourcing pass (tag_correlation.reason_stage_b_sourcing) — a DIFFERENT producer signature, enumerated on
# the worksheet but scored by a follow-in (this run scores only the Stage-A enum tags — AS-1's prompt).
COVERAGE: tuple[TagCoverage, ...] = (
    TagCoverage(
        "txn.is_money_in",
        "transaction",
        "enum",
        "mechanical",
        "Stage A (txn_stage_a group)",
        ("AS-1", "AS-7", "AS-8", "AS-12"),
        ("in", "out", "unknown"),
    ),
    TagCoverage(
        "txn.apparent_category",
        "transaction",
        "enum",
        "judgment",
        "Stage A (txn_stage_a group)",
        ("AS-1", "AS-2", "AS-5", "AS-12", "IN-1"),
        (
            "payroll",
            "transfer_own",
            "gift",
            "loan_proceeds",
            "refund",
            "interest",
            "fee",
            "vendor",
            "unknown",
        ),
    ),
    TagCoverage(
        "txn.has_identified_source",
        "transaction",
        "enum",
        "judgment",
        "Stage B (sourcing)",
        ("AS-1", "AS-2", "AS-5"),
        ("yes", "no", "unknown"),
        money_in_only=True,
    ),
    TagCoverage(
        "txn.counterparty",
        "transaction",
        "free_text_deferred",
        "judgment",
        "Stage B (sourcing)",
        ("AS-2", "AS-5", "AS-12", "FR-5"),
        None,
        money_in_only=True,
    ),
    TagCoverage(
        "txn.source_reference",
        "transaction",
        "free_text_deferred",
        "judgment",
        "Stage B (sourcing)",
        ("AS-1", "AS-5"),
        None,
        money_in_only=True,
    ),
)

# Families with NO labelable content on LF-6T3N — reported UNMEASURABLE, never silently dropped. The 5
# bank statements carry EMPTY extracted fields, so stmt.* would abstain (no owner/balance to read); there
# are no id / income / retirement-asset documents at all.
UNMEASURABLE_ON_LF6T3N: tuple[tuple[str, str], ...] = (
    (
        "stmt.owner_matches_borrower / stmt.is_reserve_eligible",
        "5 statements but EMPTY fields -> content-free (all-abstain); not labelable",
    ),
    ("id.*", "n=0 -> no identity documents in LF-6T3N"),
    ("income.*", "n=0 -> no paystub / W-2 / VOE documents"),
    (
        "asset.liquidation_terms / asset.usable_value",
        "n=0 -> no retirement / brokerage account documents",
    ),
)


def _fv(field: Field | None) -> str:
    """A Field's value as a display string ('' when absent/None) — for the context columns."""
    if field is None or field.absent or field.value is None:
        return ""
    return str(field.value)


@dataclass(frozen=True)
class WorksheetRow:
    """One (tag, transaction) instance a human labels. Carries document context, NOT the AI prediction."""

    bucket: str
    tag_id: str
    subject_id: str
    scoring: str
    allowed_values: str
    consuming_rules: str
    rule_status: str  # "LIVE" or "inert" — so a labeler knows which rows actually matter today
    statement_id: str
    txn_date: str
    txn_amount: str
    txn_direction: str
    txn_description: str
    golden_label: str = ""  # EMPTY — the human fills this
    labeler_note: str = ""  # EMPTY — the human's rationale / uncertainty


_HEADERS = (
    "tag_id",
    "subject_id",
    "scoring",
    "allowed_values",
    "consuming_rules",
    "rule_status",
    "statement_id",
    "txn_date",
    "txn_amount",
    "txn_direction",
    "txn_description",
    "golden_label",
    "labeler_note",
)


def build_worksheet(snapshot: Snapshot) -> list[WorksheetRow]:
    """Enumerate every labelable AI-tag instance LF-6T3N produces — deterministically, from the SNAPSHOT
    (no AI, no key). One row per (tag, transaction); Stage-B sourcing tags only on money-in candidates."""
    rows: list[WorksheetRow] = []
    for doc in snapshot.documents.entries:
        for txn in doc.transactions or ():
            direction = _fv(txn.direction)
            is_candidate = direction == _CREDIT
            for cov in COVERAGE:
                if cov.money_in_only and not is_candidate:
                    continue
                allowed = " | ".join(cov.allowed_values) if cov.allowed_values else "(free text)"
                rows.append(
                    WorksheetRow(
                        bucket=cov.bucket,
                        tag_id=cov.tag_id,
                        subject_id=txn.content_id,
                        scoring=cov.scoring,
                        allowed_values=allowed,
                        consuming_rules=", ".join(cov.consuming_rules),
                        rule_status="LIVE" if cov.rule_live else "inert",
                        statement_id=doc.content_id,
                        txn_date=_fv(txn.date),
                        txn_amount=_fv(txn.amount),
                        txn_direction=direction,
                        txn_description=_fv(txn.description),
                    )
                )
    return rows


def render_csv(rows: list[WorksheetRow]) -> str:
    """One bucket's rows → CSV text (deterministic order: as enumerated). Predictions are NOT a column."""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")  # "\n" (not the csv default "\r\n") — matches the
    # repo's mixed-line-ending pre-commit hook, so a regenerated worksheet is byte-identical (no churn).
    writer.writerow(_HEADERS)
    for r in rows:
        writer.writerow(
            [
                r.tag_id,
                r.subject_id,
                r.scoring,
                r.allowed_values,
                r.consuming_rules,
                r.rule_status,
                r.statement_id,
                r.txn_date,
                r.txn_amount,
                r.txn_direction,
                r.txn_description,
                r.golden_label,
                r.labeler_note,
            ]
        )
    return buf.getvalue()


def write_worksheets(snapshot: Snapshot, out_dir: Path) -> dict[str, Path]:
    """Write the split worksheets: mechanical (Geet) + judgment (Priya). Returns the paths written."""
    rows = build_worksheet(snapshot)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    for bucket, name in (
        ("mechanical", "lf6t3n-labels-mechanical.csv"),
        ("judgment", "lf6t3n-labels-judgment.csv"),
    ):
        path = out_dir / name
        path.write_text(render_csv([r for r in rows if r.bucket == bucket]), encoding="utf-8")
        written[bucket] = path
    return written


def coverage_report(snapshot: Snapshot) -> str:
    """The Phase-0 deliverable: every AI tag -> n on THIS file -> enum/free-text -> consuming rule live?
    Plus the UNMEASURABLE families, stated plainly. Deterministic (from the snapshot; no AI)."""
    rows = build_worksheet(snapshot)
    counts: dict[str, int] = {}
    for r in rows:
        counts[r.tag_id] = counts.get(r.tag_id, 0) + 1
    lines = [
        "=" * 92,
        "LF-6T3N COVERAGE — a BIAS HUNT, not validation (a clean result does NOT unblock inert rules)",
        "=" * 92,
    ]
    lines.append(f"{'tag':<28} {'n':>4}  {'scoring':<20} {'live?':<6} {'producer':<24} rules")
    for cov in COVERAGE:
        n = counts.get(cov.tag_id, 0)
        flag = "n>=20" if n >= 20 else ("n=0" if n == 0 else "bias-hunt")
        lines.append(
            f"{cov.tag_id:<28} {n:>4}  {cov.scoring:<20} {('LIVE' if cov.rule_live else 'inert'):<6} "
            f"{cov.producer:<24} {', '.join(cov.consuming_rules)}   [{flag}]"
        )
    lines.append("-" * 92)
    lines.append("UNMEASURABLE on LF-6T3N (reported, not dropped):")
    for name, why in UNMEASURABLE_ON_LF6T3N:
        lines.append(f"  {name}: {why}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# PHASE 2 — the scoring run (live, opt-in). Reuses LP-334's ScoredTag/summarize/failing_cases.
# --------------------------------------------------------------------------- #
def load_golden(csv_text: str) -> dict[tuple[str, str], str]:
    """Read a FILLED worksheet -> {(tag_id, subject_id): golden_label}. Rows with an empty golden_label
    are skipped (unlabeled). This is how the human's truth enters the scoring run."""
    golden: dict[tuple[str, str], str] = {}
    for row in csv.DictReader(io.StringIO(csv_text)):
        label = (row.get("golden_label") or "").strip()
        if not label:
            continue
        golden[(row["tag_id"].strip(), row["subject_id"].strip())] = label
    return golden


async def calibrate_lf6t3n(
    snapshot: Snapshot,
    golden: dict[tuple[str, str], str],
    *,
    reasoner: Reasoner | None = None,
) -> list[ScoredTag]:
    """Score the REAL Stage-A reasoner over LF-6T3N against the filled worksheet. Returns [] when there
    are no Stage-A golden labels yet (the correct outcome for an unfilled worksheet — NOT a crash, NOT a
    fabricated score). Free-text + Stage-B tags in the golden are intentionally NOT %-scored here
    (FINDING-2 / separate producer) — they are the human-review + follow-in surface."""
    stage_a_golden = {k: v for k, v in golden.items() if k[0] in _SCORABLE_STAGE_A}
    if not stage_a_golden:
        return []
    groups = load_ai_groups()
    decls = load_declarations()
    group = groups[_STAGE_A_GROUP]
    allowed = {t: decls[t].allowed_values for t in group.tag_ids if t in decls}
    produced = await produce_ai_group_tags(snapshot, group, allowed, reasoner=reasoner)
    scored: list[ScoredTag] = []
    for (tag_id, subject_id), gold in sorted(stage_a_golden.items()):
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
    "COVERAGE",
    "UNMEASURABLE_ON_LF6T3N",
    "TagCoverage",
    "WorksheetRow",
    "build_worksheet",
    "calibrate_lf6t3n",
    "coverage_report",
    "load_golden",
    "render_csv",
    "write_worksheets",
]
