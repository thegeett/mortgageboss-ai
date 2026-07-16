"""LP-334 — LIVE calibration: score the REAL AI tag-reasoner against golden labels.

Calibration was KEYLESS until now — labels replayed, trivially perfect (a plumbing check). This runs the
REAL AI producer (``produce_ai_group_tags`` with ``reasoner=None``) over LABELED content and scores
predicted-vs-golden per tag: the unknown-rate + accuracy-when-concrete (reusing LP-317's
``DimensionCalibration`` UNCHANGED), PLUS per-case detail (predicted / golden / confidence / reasoning) so
a WRONG tag is inspectable — a number without the failing cases is not actionable.

THE CONTENT SOURCE IS A SWAPPABLE SEAM (D1). ``calibrate(docs, ...)`` takes any iterable of
:class:`LabeledDoc`. The in-repo :data:`LABELED_DOCS` is clean-field "synthetic-equivalent" content —
because the tag reasoners consume EXTRACTED FIELDS (never raw scans; ``_doc_context`` sends
``document.fields``), it measures the fields→tags reasoning FAITHFULLY; it does NOT measure how the
reasoner handles garbled fields from a bad scan (an extraction-stage concern) nor real-world PII messiness.
A de-identified real set plugs in behind the same interface, pending Geet's privacy approval.

Keyless-safe: pass a stub ``reasoner`` to exercise the plumbing with no key; ``reasoner=None`` runs the
real model (needs ``ANTHROPIC_API_KEY``). CI never depends on a key or a paid call.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

from app.verification.eval.calibration import DimensionCalibration
from app.verification.snapshot.fields import Field, FieldSource
from app.verification.snapshot.model import (
    DocumentEntry,
    DocumentsSection,
    MismoSection,
    Snapshot,
    TagsSection,
)
from app.verification.tag_materialization.ai import Reasoner, produce_ai_group_tags
from app.verification.tag_materialization.declarations import load_ai_groups, load_declarations

_ABSTENTION = {None, "unknown", "n/a"}
_PUNCT = re.compile(r"[^\w\s]")
_WS = re.compile(r"\s+")


def _norm(value: str | None) -> str:
    """The comparison normalizer — casefold + drop punct + collapse ws. So a golden 'Robert J Smith'
    matches a predicted 'Robert J. Smith' (a normalized-name tag has many valid renderings); for an enum
    (residence / yes / no) it is exact anyway."""
    if value is None:
        return ""
    return _WS.sub(" ", _PUNCT.sub("", value.casefold())).strip()


@dataclass(frozen=True)
class LabeledDoc:
    """One labeled content item: the extracted FIELDS + the golden tag values + which AI group to run."""

    doc_id: str
    document_type: str
    group: str
    fields: dict[str, str]
    golden: dict[str, str]  # tag_id -> the expected value


@dataclass(frozen=True)
class ScoredTag:
    """One scored (golden, predicted) pair — with the detail that makes a failure inspectable."""

    doc_id: str
    tag_id: str
    golden: str
    predicted: str | None
    confidence: float | None
    reasoning: str | None

    @property
    def abstained(self) -> bool:
        return self.predicted is None or self.predicted.casefold() in _ABSTENTION

    @property
    def golden_is_abstention(self) -> bool:
        """The correct answer IS to abstain (a doc with no name legitimately yields 'unknown')."""
        return self.golden.casefold() in _ABSTENTION

    @property
    def correct(self) -> bool:
        # A golden-abstention case is correct WHEN the tag abstains (measuring correct abstention, not
        # over-abstention). Otherwise: committed AND matches after normalization.
        if self.golden_is_abstention:
            return self.abstained
        return not self.abstained and _norm(self.predicted) == _norm(self.golden)


def _snapshot(doc: LabeledDoc) -> Snapshot:
    entry = DocumentEntry(
        content_id=doc.doc_id,
        document_type=doc.document_type,
        fields={k: Field.present(v, source=FieldSource.EXTRACTED) for k, v in doc.fields.items()},
    )
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 7, 15, tzinfo=UTC),
        documents=DocumentsSection.present([entry]),
        mismo=MismoSection.present({}),
        tags=TagsSection.present({}),
    )


async def calibrate(docs: list[LabeledDoc], *, reasoner: Reasoner | None = None) -> list[ScoredTag]:
    """Run each doc's AI group over its fields and score every golden tag. ``reasoner=None`` → the REAL
    model (one call per doc); a stub scores the plumbing keyless. One doc's failure never aborts the run."""
    groups = load_ai_groups()
    decls = load_declarations()
    scored: list[ScoredTag] = []
    for doc in docs:
        group = groups[doc.group]
        allowed = {t: decls[t].allowed_values for t in group.tag_ids if t in decls}
        produced = await produce_ai_group_tags(_snapshot(doc), group, allowed, reasoner=reasoner)
        tags = produced.get(doc.doc_id, {})
        for tag_id, golden in doc.golden.items():
            tag = tags.get(tag_id)
            scored.append(
                ScoredTag(
                    doc_id=doc.doc_id,
                    tag_id=tag_id,
                    golden=golden,
                    predicted=None if tag is None else str(tag.value),
                    confidence=None if tag is None else tag.confidence,
                    reasoning=None if tag is None else tag.reasoning,
                )
            )
    return scored


def summarize(scored: list[ScoredTag]) -> list[DimensionCalibration]:
    """Aggregate per tag → the LP-317 DimensionCalibration (unknown-rate + accuracy-when-concrete)."""
    by_tag: dict[str, list[ScoredTag]] = {}
    for s in scored:
        by_tag.setdefault(s.tag_id, []).append(s)
    out: list[DimensionCalibration] = []
    for tag_id, group in sorted(by_tag.items()):
        unknown = sum(1 for s in group if s.abstained)
        concrete = [s for s in group if not s.abstained]
        correct = sum(1 for s in concrete if s.correct)
        out.append(DimensionCalibration(tag_id, len(group), unknown, len(concrete), correct))
    return out


def failing_cases(scored: list[ScoredTag]) -> list[ScoredTag]:
    """The actionable part — every case the tag got WRONG: over-abstained on an answerable doc, or
    committed to a value that doesn't match the golden. A correct abstention (golden is 'unknown') is NOT
    a failure."""
    return [s for s in scored if not s.correct]


def format_report(scored: list[ScoredTag], *, live: bool) -> str:
    mode = "LIVE MODEL" if live else "STUB (plumbing check — not a real measurement)"
    lines = ["=" * 78, f"LIVE CALIBRATION — {mode}", "=" * 78]
    lines.append(f"{'tag':<34} {'n':>3} {'unknown%':>9} {'acc-concrete%':>14}")
    for c in summarize(scored):
        lines.append(
            f"{c.dimension:<34} {c.total:>3} {c.unknown_rate * 100:>8.1f}% "
            f"{c.accuracy_when_concrete * 100:>13.1f}%"
        )
    fails = failing_cases(scored)
    lines.append("-" * 78)
    lines.append(f"FAILING CASES ({len(fails)}) — predicted vs golden:")
    for s in fails:
        verdict = "ABSTAINED" if s.abstained else "WRONG"
        lines.append(
            f"  [{verdict}] {s.tag_id} @ {s.doc_id}: predicted={s.predicted!r} golden={s.golden!r}"
        )
        if s.reasoning:
            lines.append(f"           reasoning: {s.reasoning[:90]}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# THE DEFAULT SOURCE — in-repo labeled fields (clean, no PII). Prioritizes the LIVE + auto-shipping tags:
# id.* feed ACTIVE rules (ID-1/4/7/9). Income tags are included for breadth (their rules are inert). A
# de-identified real set replaces this behind the same LabeledDoc interface (D1, pending approval).
# --------------------------------------------------------------------------- #
LABELED_DOCS: list[LabeledDoc] = [
    # id.name_normalized (id_name) — ID-1, fuzzy consistency (ratification-pending)
    LabeledDoc(
        "dl_name_1",
        "drivers_license",
        "id_name",
        {"full_name": "Robert J. Smith"},
        {"id.name_normalized": "Robert J Smith"},
    ),
    LabeledDoc(
        "dl_name_2",
        "drivers_license",
        "id_name",
        {"full_name": "MARIA GARCIA-LOPEZ"},
        {"id.name_normalized": "Maria Garcia Lopez"},
    ),
    LabeledDoc(
        "dl_name_3",
        "drivers_license",
        "id_name",
        {"full_name": "Wm. O'Brien III"},
        {"id.name_normalized": "William OBrien III"},
    ),
    LabeledDoc(
        "dl_name_4", "drivers_license", "id_name", {}, {"id.name_normalized": "unknown"}
    ),  # no name → abstain
    # id.address_normalized + id.current_address_type (id_address) — ID-4
    LabeledDoc(
        "dl_addr_1",
        "drivers_license",
        "id_address",
        {"address": "123 N Main St, Apt 4, Springfield IL 62704"},
        {
            "id.address_normalized": "123 North Main Street Apt 4 Springfield IL 62704",
            "id.current_address_type": "residence",
        },
    ),
    LabeledDoc(
        "mail_1",
        "bank_statement",
        "id_address",
        {"mailing_address": "PO Box 88, Springfield IL 62704"},
        {
            "id.address_normalized": "PO Box 88 Springfield IL 62704",
            "id.current_address_type": "mailing",
        },
    ),
    # id.title_vesting_consistent (id_title) — ID-7, DETERMINISTIC / AUTO-SHIPPING (highest-risk id tag)
    LabeledDoc(
        "title_1",
        "title_commitment",
        "id_title",
        {"vesting": "John Smith, a married man", "marital_status": "married"},
        {"id.title_vesting_consistent": "yes"},
    ),
    LabeledDoc(
        "title_2",
        "title_commitment",
        "id_title",
        {"vesting": "Jane Doe, a single person", "marital_status": "married"},
        {"id.title_vesting_consistent": "no"},
    ),
    # id.poa_present_and_acceptable (id_poa) — ID-9, judgment (ratification-pending)
    LabeledDoc(
        "poa_1",
        "power_of_attorney",
        "id_poa",
        {
            "attorney_in_fact": "Jane Smith (spouse)",
            "note_date": "2026-05-01",
            "poa_date": "2026-04-01",
        },
        {"id.poa_present_and_acceptable": "yes"},
    ),
    LabeledDoc(
        "poa_2",
        "power_of_attorney",
        "id_poa",
        {
            "attorney_in_fact": "Bob Agent (loan officer)",
            "note_date": "2026-05-01",
            "poa_date": "2026-04-01",
        },
        {"id.poa_present_and_acceptable": "no"},
    ),  # interested party
    # income.documented_monthly + income.type (income_amounts) — feeds IN-1's DETERMINISTIC FRAUD verdict
    LabeledDoc(
        "ps_1",
        "pay_stub",
        "income_amounts",
        {"gross_pay": "3000", "pay_frequency": "semimonthly", "ytd_gross": "30000"},
        {"income.documented_monthly": "6000", "income.type": "base"},
    ),
    LabeledDoc(
        "ps_2",
        "pay_stub",
        "income_amounts",
        {"gross_pay": "2000", "pay_frequency": "biweekly"},
        {"income.documented_monthly": "4333.33", "income.type": "base"},
    ),  # 2000x26/12 (golden was mis-rounded)
    # income.employer_normalized (income_employer) — IN-5
    LabeledDoc(
        "ps_emp_1",
        "pay_stub",
        "income_employer",
        {"employer": "Acme Corporation, Inc."},
        {"income.employer_normalized": "Acme Corporation"},
    ),
]


@dataclass
class CalibrationRun:
    """The result bundle for the report/tests."""

    scored: list[ScoredTag] = field(default_factory=list)
    live: bool = False

    @property
    def dimensions(self) -> list[DimensionCalibration]:
        return summarize(self.scored)

    @property
    def failures(self) -> list[ScoredTag]:
        return failing_cases(self.scored)


__all__ = [
    "LABELED_DOCS",
    "CalibrationRun",
    "LabeledDoc",
    "ScoredTag",
    "calibrate",
    "failing_cases",
    "format_report",
    "summarize",
]
