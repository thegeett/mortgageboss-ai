"""LP-420 — the combined blind labeling worksheets (the three income-docs tags that passed the D1 census).

Four of the seven blocking tags were EXCLUDED (income.type one-sided + its consuming values structurally
unreachable; txn.is_nsf_or_overdraft n=0; the two loan-subject occupancy tags needing invented loans). Three
passed with a genuine two/multi-sided distribution on LP-418's committed fixtures. These pin: the sheets are
BLIND (no golden/prediction/AI-reasoning), show the allowed VALUES but not the model's decision rules, order the
rows so answers do not cluster, are deterministic + keyless, and are committable (synthetic, no PII). Plus the D1
census guards — so the exclusions cannot silently rot back into "just run a labeling round".
"""

from __future__ import annotations

import csv
import io
import tempfile
from collections import Counter
from pathlib import Path

from app.verification.eval.combined_labeling_worksheet import (
    CONTINUANCE_WORKSHEET_FILE,
    VOE_OFFER_WORKSHEET_FILE,
    build_continuance_rows,
    build_voe_offer_rows,
    write_all,
    write_continuance_worksheet,
    write_voe_offer_worksheet,
)
from app.verification.eval.worksheet import build_worksheet
from app.verification.rule_engine.registry import ACTIVE_RULE_IDS
from tests.expected_active import EXPECTED_ACTIVE_RULE_COUNT

_CALIBRATION_DIR = Path(__file__).resolve().parents[4] / "docs" / "calibration"
_FRESH_DIR = Path(tempfile.mkdtemp())
_VOE_OFFER = write_voe_offer_worksheet(_FRESH_DIR).read_text(encoding="utf-8")
_CONTINUANCE = write_continuance_worksheet(_FRESH_DIR).read_text(encoding="utf-8")


def _rows(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text)))


# ======================================================================= #
# Deterministic, keyless, blank, and the committed files match a fresh generation
# ======================================================================= #
def test_generation_is_deterministic_and_blank(tmp_path: Path) -> None:
    a = write_voe_offer_worksheet(tmp_path).read_text(encoding="utf-8")
    b = write_voe_offer_worksheet(tmp_path).read_text(encoding="utf-8")
    assert a == b == _VOE_OFFER  # deterministic (no AI, no key, no clock)
    c = write_continuance_worksheet(tmp_path).read_text(encoding="utf-8")
    d = write_continuance_worksheet(tmp_path).read_text(encoding="utf-8")
    assert c == d == _CONTINUANCE
    for text in (a, c):
        assert all(
            not (r["golden_label"] or "").strip() and not (r["labeler_note"] or "").strip()
            for r in _rows(text)
        )  # a BLANK template — every label is hers to fill


def test_committed_files_match_a_fresh_generation() -> None:
    # The committed CSVs are the blank templates (Priya has not labeled yet), so they must equal a fresh
    # keyless generation byte-for-byte — a regeneration never silently drifts from what is committed.
    assert (_CALIBRATION_DIR / VOE_OFFER_WORKSHEET_FILE).read_text(encoding="utf-8") == _VOE_OFFER
    assert (_CALIBRATION_DIR / CONTINUANCE_WORKSHEET_FILE).read_text(
        encoding="utf-8"
    ) == _CONTINUANCE


# ======================================================================= #
# Row counts + the three tags (the D1 include set)
# ======================================================================= #
def test_row_counts_and_tags() -> None:
    vo = _rows(_VOE_OFFER)
    assert len(vo) == 24  # 12 voe_present + 12 offer_letter_present
    assert Counter(r["tag_id"] for r in vo) == {
        "income.voe_present": 12,
        "income.offer_letter_present": 12,
    }
    cont = _rows(_CONTINUANCE)
    assert len(cont) == 6
    assert {r["tag_id"] for r in cont} == {"income.continuance_3yr"}


# ======================================================================= #
# Blind: allowed values shown; no prediction / AI reasoning; prompt omits the model's decision rules
# ======================================================================= #
def test_allowed_values_shown_per_tag() -> None:
    by_tag = {r["tag_id"]: r["allowed_values"] for r in _rows(_VOE_OFFER) + _rows(_CONTINUANCE)}
    assert by_tag["income.voe_present"] == "yes | no"
    assert by_tag["income.offer_letter_present"] == "yes | no | n/a"
    assert by_tag["income.continuance_3yr"] == "yes | no | unknown"


def test_no_prediction_or_ai_reasoning_columns() -> None:
    # The header carries no prediction/confidence/reasoning column; the context is facts + a neutral prompt only.
    header = _VOE_OFFER.splitlines()[0]
    for banned in ("predict", "confidence", "reasoning", "ai_", "expected"):
        assert banned not in header.lower()
    # and no row encodes an answer in a stray column (golden/note blank, asserted above)


def test_prompt_shows_values_not_the_models_decision_rules() -> None:
    # The prompt asks the core question + the allowed values; it must NOT restate HOW the model decides (that
    # hands her the answer key — the LP-399 line). These are model RULE phrases, not value names.
    text = (_VOE_OFFER + _CONTINUANCE).lower()
    for rule_phrase in (
        "signed by the employer",  # voe rule
        "issued within",  # voe/offer recency rule
        "must state",  # offer rule
        "annual salary",  # offer rule (the field, not the question)
        "defined end date",  # continuance rule
        "indefinitely",  # continuance rule
        "guaranteed to continue",  # continuance rule
        "documented history",  # continuance rule
    ):
        assert rule_phrase not in text, rule_phrase


# ======================================================================= #
# Non-grouping row order (answers do not cluster)
# ======================================================================= #
def test_voe_offer_order_alternates_not_clustered() -> None:
    # The insertion order is 6 voe then 6 offer (all yes-shaped then all no-shaped). The sheet interleaves so the
    # two source types ALTERNATE within each tag block — no run of same-type rows telegraphs the answer.
    voe_block = [r for r in _rows(_VOE_OFFER) if r["tag_id"] == "income.voe_present"]
    types = [r["document_type"] for r in voe_block]
    assert types[:4] == ["voe", "employment_offer_letter", "voe", "employment_offer_letter"]
    # no run of 3 identical source types anywhere in the block
    assert not any(types[i] == types[i + 1] == types[i + 2] for i in range(len(types) - 2))


def test_voe_offer_grouped_by_tag_so_a_docs_two_rows_sit_far_apart() -> None:
    # LP-401: group BY TAG (all voe_present, then all offer_letter_present) so a document's two tag-rows are 12
    # apart — one answer cannot reflexively bias the same document's other tag.
    tags = [r["tag_id"] for r in _rows(_VOE_OFFER)]
    assert tags[:12] == ["income.voe_present"] * 12
    assert tags[12:] == ["income.offer_letter_present"] * 12


def test_continuance_order_is_not_the_insertion_order() -> None:
    # The fixture's insertion order is pension, alimony, child_support, disability, SS, note. The sheet reorders
    # to a fixed non-grouping permutation so the likely-continuing types are not clustered apart from the
    # time-limited ones (the labels are hers — the order telegraphs nothing).
    def _kind(r: dict[str, str]) -> str:
        return r["context"].split("other_income_type=", 1)[1].split(";", 1)[0]

    kinds = [_kind(r) for r in _rows(_CONTINUANCE)]
    assert kinds == [
        "pension",
        "child_support",
        "social_security",
        "note_receivable",
        "disability",
        "alimony",
    ]
    assert kinds != [
        "pension",
        "alimony",
        "child_support",
        "disability",
        "social_security",
        "note_receivable",
    ]


# ======================================================================= #
# Committable: synthetic, no PII
# ======================================================================= #
def test_no_real_pii_markers() -> None:
    text = _VOE_OFFER + _CONTINUANCE
    # plain ASCII (renders in Excel/Sheets); no SSN/masked-account shapes; only invented names (Dana Brooks etc.)
    assert text.isascii()
    for marker in ("SSN", "***-**-", "xxx-xx", "@"):
        assert marker not in text


# ======================================================================= #
# D1 CENSUS GUARDS — the four exclusions, pinned so they cannot silently rot
# ======================================================================= #
def test_income_type_is_one_sided_on_the_fixtures() -> None:
    # income.type has rows, but they are one-sided base wage — self_employment (IN-12) and rental (IN-13) are
    # STRUCTURALLY unreachable from pay_stub/w2 (income_amounts' only doc types). So it was EXCLUDED; a base-only
    # worksheet would not unblock IN-12/IN-13. If a future fixture adds typed income docs this guard flips.
    from app.verification.eval.income_scenarios import build_income_calibration_snapshot

    rows = [
        r for r in build_worksheet(build_income_calibration_snapshot()) if r.tag_id == "income.type"
    ]
    assert len(rows) >= 6  # enough by COUNT — but...
    has_self_employment = any("self_employ" in r.context.lower() for r in rows)
    assert not has_self_employment  # ...the value IN-12 needs cannot appear here


def test_the_two_occupancy_tags_are_loan_subject_and_have_no_fixture_rows() -> None:
    # Loan-subject (one row per loan) with no occupancy/rental fixture → n=0. Reaching n>=6 would mean authoring
    # 6+ whole loan files with the very (in)consistency Priya would judge → STOP (labeling our own invention).
    from app.verification.tag_materialization.declarations import load_declarations

    decls = load_declarations()
    for tag in ("occupancy.rental_support", "occupancy.consistent_with_signals"):
        assert decls[tag].subject == "loan"


def test_nsf_tag_has_no_labelable_rows_in_any_fixture() -> None:
    # txn.is_nsf_or_overdraft: no fixture carries NSF/overdraft transactions, so it produces no worksheet rows
    # (it is not in the worksheet coverage map, and no fixture would feed it) → EXCLUDED, needs real statements.
    from app.verification.eval.fire_path_scenarios import build_statement_break_snapshot

    rows = [
        r
        for r in build_worksheet(build_statement_break_snapshot())
        if r.tag_id == "txn.is_nsf_or_overdraft"
    ]
    assert rows == []


# ======================================================================= #
# Equivalence: no rule change; existing worksheets untouched
# ======================================================================= #
def test_no_rule_activation_changed() -> None:
    assert len(ACTIVE_RULE_IDS) == EXPECTED_ACTIVE_RULE_COUNT  # 30 — worksheets only


def test_write_all_emits_exactly_the_two_files(tmp_path: Path) -> None:
    written = write_all(tmp_path)
    assert set(written) == {VOE_OFFER_WORKSHEET_FILE, CONTINUANCE_WORKSHEET_FILE}
    assert all(p.is_file() for p in written.values())
    # build_* helpers are pure (no write) and match the written content's row counts
    assert len(build_voe_offer_rows()) == 24 and len(build_continuance_rows()) == 6
