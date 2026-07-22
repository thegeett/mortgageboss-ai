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

import asyncio
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from app.verification.eval.calibration import (
    SCORING_HUMAN_REVIEW,
    SCORING_NORMALIZED,
    DimensionCalibration,
    normalized_match,
    scoring_mode,
)
from app.verification.snapshot.fields import Field, FieldSource
from app.verification.snapshot.model import (
    DocumentEntry,
    DocumentsSection,
    MismoSection,
    Snapshot,
    TagsSection,
)
from app.verification.tag_materialization.ai import Reasoner, produce_ai_group_tags
from app.verification.tag_materialization.declarations import (
    AiGroup,
    load_ai_groups,
    load_declarations,
)

_MAX_CONCURRENCY = 4

_ABSTENTION = {None, "unknown", "n/a"}
_PUNCT = re.compile(r"[^\w\s]")
_WS = re.compile(r"\s+")


def _norm(value: str | None) -> str:
    """The EXACT-path string normalizer — casefold + DELETE punct + collapse ws. Used ONLY by
    ``_values_match``'s string fallback, i.e. enum tags (residence / yes / no), where deleting punct
    mirrors ID-1/ID-4's ``drop_punct`` exact bookend. It is NOT the free-text path: names/addresses score
    via ``calibration.normalized_match`` (punctuation as a word BOUNDARY, LP-342) — this deletes punct
    instead, so the two INTENTIONALLY differ (they agree on the punctuation-free enums this actually sees).
    NUMERIC tags must NOT use this — see _values_match (dropping the '.' collides different numbers)."""
    if value is None:
        return ""
    return _WS.sub(" ", _PUNCT.sub("", value.casefold())).strip()


def _as_decimal(value: str | None) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(value.strip())
    except (InvalidOperation, ValueError):
        return None


def _values_match(golden: str, predicted: str | None) -> bool:
    """Compare a predicted tag value to its golden. When BOTH parse as numbers, compare as Decimals —
    income.documented_monthly (which feeds IN-1's deterministic fraud verdict) is a numeric tag, and the
    string normalizer would strip its decimal point and collide different magnitudes ('4333.33' vs
    '43333.3' both → '433333', a 10x error scored correct; '6000' vs '6000.00' scored wrong). Production
    compares these numerically (compare_values on Decimal operands), so calibration must too — with a
    cent-level tolerance for rounding, which still catches order-of-magnitude errors. Otherwise fall back
    to the string normalizer (names/enums)."""
    if predicted is None:
        return False
    g_num, p_num = _as_decimal(golden), _as_decimal(predicted)
    if g_num is not None and p_num is not None:
        return abs(g_num - p_num) <= max(Decimal("0.01"), abs(g_num) * Decimal("0.001"))
    return _norm(predicted) == _norm(golden)


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
    def needs_review(self) -> bool:
        """A ``human_review`` tag (no defensible golden) — recorded, never %-scored (LP-342)."""
        return scoring_mode(self.tag_id) == SCORING_HUMAN_REVIEW

    @property
    def correct(self) -> bool:
        # A human_review tag has NO defensible golden, so it is never a scored pass — recorded via
        # review_cases, never %-scored (guard here so `correct` can't be misused on a mixed list; callers
        # also filter on needs_review). A golden-abstention case is correct WHEN the tag abstains (measuring
        # correct abstention, not over-abstention). Otherwise: committed AND matches — by the tag's DECLARED
        # scoring method (LP-342): `normalized` for free-text names/addresses (format-only, punctuation as a
        # word boundary), else the numeric/normalized `exact` path (BYTE-IDENTICAL for every enum/number).
        if self.needs_review:
            return False
        if self.golden_is_abstention:
            return self.abstained
        if self.abstained:
            return False
        if scoring_mode(self.tag_id) == SCORING_NORMALIZED:
            return normalized_match(self.golden, self.predicted)
        return _values_match(self.golden, self.predicted)


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


async def _score_doc(
    doc: LabeledDoc,
    group: AiGroup,
    allowed: dict[str, tuple[str, ...] | None],
    reasoner: Reasoner | None,
) -> list[ScoredTag]:
    """Score one doc's golden tags. A failure (a live transport error / timeout) records the doc's tags as
    abstentions WITH the reason, so one doc never aborts the batch (the resilience the module promises)."""
    try:
        produced = await produce_ai_group_tags(_snapshot(doc), group, allowed, reasoner=reasoner)
        tags = produced.get(doc.doc_id, {})
    except Exception as exc:  # a per-doc failure (live transport/timeout) never aborts the run
        reason = f"scoring failed: {type(exc).__name__}"
        return [
            ScoredTag(doc.doc_id, tag_id, golden, None, None, reason)
            for tag_id, golden in doc.golden.items()
        ]
    scored: list[ScoredTag] = []
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


async def calibrate(
    docs: list[LabeledDoc],
    *,
    reasoner: Reasoner | None = None,
    max_concurrency: int = _MAX_CONCURRENCY,
) -> list[ScoredTag]:
    """Run each doc's AI group over its fields and score every golden tag. ``reasoner=None`` → the REAL
    model (one call per doc, run BOUNDED-CONCURRENTLY — the docs are independent). A stub scores the
    plumbing keyless. One doc's failure never aborts the run (a failed call → abstentions with the
    reason); results preserve input order."""
    groups = load_ai_groups()
    decls = load_declarations()
    sem = asyncio.Semaphore(max_concurrency)

    async def _bounded(doc: LabeledDoc) -> list[ScoredTag]:
        group = groups[doc.group]
        allowed = {t: decls[t].allowed_values for t in group.tag_ids if t in decls}
        async with sem:
            return await _score_doc(doc, group, allowed, reasoner)

    per_doc = await asyncio.gather(*(_bounded(doc) for doc in docs))
    return [s for doc_scored in per_doc for s in doc_scored]


def summarize(scored: list[ScoredTag]) -> list[DimensionCalibration]:
    """Aggregate per tag → the LP-317 DimensionCalibration (unknown-rate + accuracy-when-concrete). The
    unknown-rate is measured over ANSWERABLE docs only: a doc whose golden IS an abstention (abstaining is
    correct) is excluded, so correct abstentions can never trip over_abstaining. A wrong such case (the
    model COMMITTED where it should have abstained) is still surfaced by failing_cases."""
    by_tag: dict[str, list[ScoredTag]] = {}
    for s in scored:
        by_tag.setdefault(s.tag_id, []).append(s)
    out: list[DimensionCalibration] = []
    for tag_id, group in sorted(by_tag.items()):
        answerable = [s for s in group if not s.golden_is_abstention]
        if scoring_mode(tag_id) == SCORING_HUMAN_REVIEW:
            # No defensible golden → answerable cases are recorded for review, no % claimed (LP-342).
            out.append(
                DimensionCalibration(tag_id, len(answerable), 0, 0, 0, review=len(answerable))
            )
            continue
        unknown = sum(1 for s in answerable if s.abstained)
        concrete = [s for s in answerable if not s.abstained]
        correct = sum(1 for s in concrete if s.correct)
        out.append(DimensionCalibration(tag_id, len(answerable), unknown, len(concrete), correct))
    return out


def failing_cases(scored: list[ScoredTag]) -> list[ScoredTag]:
    """The actionable part — every case the tag got WRONG: over-abstained on an answerable doc, or
    committed to a value that doesn't match the golden (by its DECLARED scoring method). A correct
    abstention (golden is 'unknown') is NOT a failure; a ``human_review`` tag is neither pass nor fail —
    excluded here, listed under review_cases instead (LP-342)."""
    return [s for s in scored if not s.needs_review and not s.correct]


def review_cases(scored: list[ScoredTag]) -> list[ScoredTag]:
    """The ``human_review`` tags' answerable cases — recorded with their per-case detail for a human, never
    %-scored (a free-form wire memo has no canonical golden). LP-342."""
    return [s for s in scored if s.needs_review and not s.golden_is_abstention]


def format_report(scored: list[ScoredTag], *, live: bool) -> str:
    mode = "LIVE MODEL" if live else "STUB (plumbing check — not a real measurement)"
    lines = ["=" * 78, f"LIVE CALIBRATION — {mode}", "=" * 78]
    lines.append(f"{'tag':<34} {'n':>3} {'unknown%':>9} {'acc-concrete%':>14}")
    for c in summarize(scored):
        acc = "  HUMAN-REVIEW" if c.is_human_review else f"{c.accuracy_when_concrete * 100:>13.1f}%"
        unk = "" if c.is_human_review else f"{c.unknown_rate * 100:>8.1f}%"
        lines.append(f"{c.dimension:<34} {c.total:>3} {unk:>9} {acc:>14}")
    reviews = review_cases(scored)
    if reviews:
        lines.append("-" * 78)
        lines.append(f"HUMAN REVIEW ({len(reviews)}) — no canonical golden, inspect the detail:")
        for s in reviews:
            lines.append(
                f"  [REVIEW] {s.tag_id} @ {s.doc_id}: predicted={s.predicted!r} golden={s.golden!r}"
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
    # id.address_normalized + id.current_address_type (id_address) — ID-4. BOTH DIRECTIONS (LP-335): a DL
    # states the residence of record → "residence" (the FINDING-1 fix); a PO-box / marked-former / no-address
    # doc must still resolve mailing / prior / unknown (the over-correction guards).
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
        "dl_addr_2",
        "drivers_license",
        "id_address",
        {"address": "742 Evergreen Terrace, Springfield IL 62704"},
        {"id.current_address_type": "residence"},  # a plain DL address → residence of record
    ),
    LabeledDoc(
        "mail_1",
        "bank_statement",
        "id_address",
        {"mailing_address": "PO Box 88, Springfield IL 62704"},
        {
            "id.address_normalized": "PO Box 88 Springfield IL 62704",
            "id.current_address_type": "mailing",  # GUARD: PO box → mailing
        },
    ),
    LabeledDoc(
        "prior_1",
        "drivers_license",
        "id_address",
        {"address": "10 Old Farm Rd, Peoria IL 61602", "address_label": "PREVIOUS ADDRESS"},
        # SYNTHETIC probe of the "explicitly-marked-former → prior" branch. Real DL extraction emits
        # only `address` (no former-marker field exists in any extraction schema), so in production a DL
        # never types "prior" — it types "residence" and ID-4 surfaces any genuine mismatch (LP-335).
        # This case validates the prompt's reasoning on a marked-former field, not a producible input.
        {"id.current_address_type": "prior"},
    ),
    LabeledDoc(
        "noaddr_1",
        "drivers_license",
        "id_address",
        {},
        {
            "id.address_normalized": "unknown",
            "id.current_address_type": "unknown",  # GUARD: no address → unknown, not forced to residence
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


def score_snapshot_against_golden(
    snapshot: Snapshot, golden: dict[tuple[str, str], str]
) -> tuple[list[ScoredTag], list[tuple[str, str]]]:
    """LP-390-5 — join a MATERIALIZED snapshot's predicted tags to golden labels by the stable
    ``(tag_id, subject_id)`` key and score each (reusing ``ScoredTag``). Unlike ``calibrate`` (one AI-group
    per single-document snapshot), this scores a WHOLE materialized snapshot — so transaction-subject
    (apparent_category), borrower-subject (income_stability), and Stage-B (has_identified_source) tags are
    scored together with the document-subject ones, exactly where each producer places them.

    Returns ``(scored, unmatched)``: a labeled ``(tag_id, subject_id)`` with NO produced tag is REPORTED in
    ``unmatched``, never silently dropped (a missing prediction is a finding — the producer didn't run there
    or the subject id drifted). Deterministic given the snapshot: the only non-determinism is the live model
    that produced the snapshot's tags."""
    by = {} if snapshot.tags.absent else snapshot.tags.by_subject
    scored: list[ScoredTag] = []
    unmatched: list[tuple[str, str]] = []
    for (tag_id, subject_id), golden_value in golden.items():
        tag = by.get(subject_id, {}).get(tag_id)
        if tag is None:
            unmatched.append((tag_id, subject_id))
            continue
        scored.append(
            ScoredTag(
                subject_id, tag_id, golden_value, str(tag.value), tag.confidence, tag.reasoning
            )
        )
    return scored, unmatched


__all__ = [
    "LABELED_DOCS",
    "CalibrationRun",
    "LabeledDoc",
    "ScoredTag",
    "calibrate",
    "failing_cases",
    "format_report",
    "score_snapshot_against_golden",
    "summarize",
]
