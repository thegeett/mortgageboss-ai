"""LP-404 — AS-6 becomes the FIRST multi-tag rule: it reads the three calibrated statement-holder tags
(owner_matches_borrower / holder_name_variance / non_borrower_co_holder) and combines them into Priya's
three outcomes.

Priya's ruling:
  * a CERTAIN match (owner=yes), no non-borrower co-holder      -> satisfied     (counts silently)
  * PLAUSIBLE-but-unconfirmed (owner=unknown)                   -> needs_review  (counts, SURFACED)
  * a non-borrower co-holder (co_holder=yes) on a yes match     -> needs_review  (counts, SURFACED)
  * a genuine NON-match (owner=no)                              -> fired         (an open finding)
  * the holder facts unreadable/absent                          -> couldnt_check (honest abstention)

The heart of the ruling is the MIDDLE rows: SURFACE, don't reject — the document STILL COUNTS. That is
needs_review (not fired, which is the open-finding/exclude verdict; not couldnt_check, which is a data gap).

Deterministic (no AI): tag values are hand-set. The LIVE re-score on the LP-401 scenario fixture + the 5
real LF-6T3N statements is reported in docs/tickets/LP-404.md (reported, not asserted here).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.verification.rule_engine.deterministic import evaluate_deterministic_rule
from app.verification.rule_engine.registry import ACTIVE_RULE_IDS
from app.verification.rule_engine.result import RuleEvaluation, Verdict
from app.verification.rules.specs import load_rule_spec
from app.verification.snapshot.model import (
    BorrowerRef,
    DocumentEntry,
    DocumentsSection,
    MismoSection,
    Snapshot,
    TagsSection,
)
from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage

_O = "stmt.owner_matches_borrower"
_V = "stmt.holder_name_variance"
_C = "stmt.non_borrower_co_holder"


def _tag(value: str, *, conf: float | None = 0.9) -> Tag:
    return Tag(
        value=value,
        confidence=conf,
        reasoning="fixture",
        source_facts=("raw",),
        produced_by=TagProducedBy.AI,
        tag_role=TagRole.STRUCTURAL_FACT,
        stage=TagStage.A,
    )


def _doc(cid: str, dtype: str = "bank_statement") -> DocumentEntry:
    return DocumentEntry(
        content_id=cid,
        document_type=dtype,
        belongs_to=(BorrowerRef(borrower_id=uuid4(), name="Sam"),),
    )


def _snap(
    by_subject: dict[str, dict[str, Tag]], *, docs: list[DocumentEntry] | None = None
) -> Snapshot:
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 7, 26, tzinfo=UTC),
        documents=DocumentsSection.present(docs if docs is not None else [_doc("bs")]),
        mismo=MismoSection.present({}),
        tags=TagsSection.present(by_subject),
    )


def _eval(
    owner: str | None, variance: str | None = "none", co_holder: str | None = "no"
) -> RuleEvaluation:
    tags: dict[str, Tag] = {}
    if owner is not None:
        tags[_O] = _tag(owner)
    if variance is not None:
        tags[_V] = _tag(variance)
    if co_holder is not None:
        tags[_C] = _tag(co_holder)
    return evaluate_deterministic_rule(load_rule_spec("AS-6"), _snap({"bs": tags}))[0]


# --------------------------------------------------------------------------- #
# D1 — all three tags are on AS-6's subject (per_document / document subject); not structurally dead
# --------------------------------------------------------------------------- #
def test_all_three_tags_are_on_as6s_subject() -> None:
    spec = load_rule_spec("AS-6")
    assert spec.deterministic is not None
    assert spec.subject_enumeration == "per_document"
    # AS-6 reads all three; they are DECLARED on subject `document` (checked in the tag_materialization
    # suite) and AS-6 enumerates per_document — same subject, so every tag reaches every statement.
    assert set(spec.deterministic.load_bearing_tags) == {_O, _V, _C}
    # a fully-populated statement reaches a verdict (the tags materialize onto the subject AS-6 reads)
    assert _eval("yes").verdict is not Verdict.NOT_APPLICABLE


# --------------------------------------------------------------------------- #
# The three-outcome routing (Priya's table)
# --------------------------------------------------------------------------- #
def test_certain_match_counts_silently() -> None:
    assert _eval("yes", "none", "no").verdict is Verdict.SATISFIED


def test_benign_dropped_middle_still_satisfies_not_flagged() -> None:
    # a `yes` match with a name variance (a dropped middle) is a CERTAIN match — it counts silently.
    # Routing on the match confidence (not on the variance) keeps a genuine borrower's own account from
    # being false-flagged. This is the 5-real-LF-6T3N shape (holder "Jordan A Rivera" vs "Jordan Rivera").
    assert _eval("yes", "middle_absent", "no").verdict is Verdict.SATISFIED


def test_plausible_unconfirmed_match_surfaces_and_counts() -> None:
    # SURFACED (needs_review), NOT an open finding (fired) — the document STILL COUNTS.
    assert _eval("unknown", "nickname", "no").verdict is Verdict.NEEDS_REVIEW


def test_non_borrower_co_holder_surfaces_and_counts() -> None:
    # SURFACED (needs_review), NOT an open finding (fired) — the joint account STILL COUNTS.
    assert _eval("yes", "none", "yes").verdict is Verdict.NEEDS_REVIEW


def test_genuine_non_match_is_an_open_finding() -> None:
    assert _eval("no", "middle_differs", "no").verdict is Verdict.FIRED  # a different person
    assert _eval("no", "none", "no").verdict is Verdict.FIRED  # a trust/LLC/unrelated


def test_absent_or_unreadable_holder_facts_couldnt_check() -> None:
    assert _eval("yes", variance=None).verdict is Verdict.COULDNT_CHECK  # variance absent
    assert _eval(None, None, None).verdict is Verdict.COULDNT_CHECK  # nothing produced
    assert _eval("yes", "unknown", "no").verdict is Verdict.COULDNT_CHECK  # name unreadable


# --------------------------------------------------------------------------- #
# The MIDDLE row COUNTS the document AND surfaces (the heart of the ruling)
# --------------------------------------------------------------------------- #
def test_the_flag_rows_count_the_document_they_are_not_the_exclude_verdict() -> None:
    # `fired` is AS-6's exclude/open-finding verdict (a third-party account, does NOT count). The flag
    # rows are needs_review, a DISTINCT verdict: the statement surfaces for review but is NOT excluded
    # from the borrower's assets, and is NOT a couldnt_check data gap.
    assert _eval("unknown", "nickname").verdict is Verdict.NEEDS_REVIEW  # plausible-match flag
    assert _eval("yes", "none", "yes").verdict is Verdict.NEEDS_REVIEW  # co-holder flag
    # contrast: the exclude verdict is reserved for a genuine non-match; the couldnt_check for a data gap
    assert _eval("no", "none").verdict is Verdict.FIRED
    assert _eval("yes", variance=None).verdict is Verdict.COULDNT_CHECK


# --------------------------------------------------------------------------- #
# D4 — the reason strings NAME the specific cause in plain language (LP-376-C); no dotted tag ids
# --------------------------------------------------------------------------- #
def test_reason_strings_are_plain_language_naming_the_cause() -> None:
    unk = _eval("unknown", "nickname").reasoning or ""
    coh = _eval("yes", "none", "yes").reasoning or ""
    no = _eval("no", "middle_differs").reasoning or ""
    assert "plausibly matches a borrower" in unk and "still counts" in unk
    assert "nickname" in unk or "former surname" in unk  # names why it is unconfirmed
    assert "joint account" in coh and "not a borrower" in coh and "still counts" in coh
    assert "does not resolve to a borrower" in no and "third-party account" in no
    # no dotted tag ids leak into the processor-facing text
    for text in (unk, coh, no):
        assert "stmt." not in text and "owner_matches" not in text


# --------------------------------------------------------------------------- #
# The 5 real LF-6T3N genuine matches must NOT be false-flagged (the FP harm)
# --------------------------------------------------------------------------- #
def test_the_real_lf6t3n_shape_stays_satisfied_no_false_flag() -> None:
    # the 5 real goldens are owner=yes / variance=middle_absent ("Jordan A Rivera" vs roster "Jordan
    # Rivera") / co_holder=no — a CERTAIN match. It must be satisfied, never a needs_review/fired flag.
    assert _eval("yes", "middle_absent", "no").verdict is Verdict.SATISFIED


# --------------------------------------------------------------------------- #
# EQUIVALENCE — only AS-6 changed; it is NOT activated (its bar is Priya's, still pending)
# --------------------------------------------------------------------------- #
def test_as6_is_not_active_only_the_rule_changed() -> None:
    # LP-404 changes the RULE, not the activation bar (validated:false → inert). ACTIVE stays 24.
    assert "AS-6" not in ACTIVE_RULE_IDS
    assert len(ACTIVE_RULE_IDS) == 27  # +AS-8 (LP-406-2b); AS-6 still not active (asserted above)


def test_the_fired_branch_scopes_to_bank_statements_only() -> None:
    docs = [_doc("bs", "bank_statement"), _doc("dl", "drivers_license")]
    by = {
        r.subject_id: r.verdict
        for r in evaluate_deterministic_rule(
            load_rule_spec("AS-6"),
            _snap({"bs": {_O: _tag("no"), _V: _tag("none"), _C: _tag("no")}}, docs=docs),
        )
    }
    assert by["bs"] is Verdict.FIRED
    assert by["dl"] is Verdict.NOT_APPLICABLE  # a non-statement is out of scope
