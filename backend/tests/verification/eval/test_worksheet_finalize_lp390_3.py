"""LP-390-3 / 3a — the income calibration worksheet, finalized for Priya's session.

The worksheet is the instrument: if it's wrong her hours produce noise. Fixes pinned here: the SOURCE-TRACE
framing that makes has_identified_source a distinct question (facts first, plain ASCII — LP-390-3a), the
id.address_normalized correction (a name where an address belongs), and the drop of the non-labelable orphan
sourcing tags (counterparty / source_reference). The reframing WORKED: LP-390-3a adopted Priya's active
labeling copy, in which she labeled all 16 has_identified_source (she had skipped them as duplicates), so the
committed golden now holds 148 labels (78 judgment + 70 mechanical) + 35 notes. No tag / rule / spec / producer
changed; only the worksheet's presentation. (The real-name DB copy she cross-checks against lives in the
gitignored calibration-local/ — never committed.)
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

from app.verification.eval.lf6t3n_fixture import (
    LF6T3N_DOCUMENT_FILENAMES,
    build_lf6t3n_snapshot,
)
from app.verification.eval.worksheet import build_worksheet

_ROOT = Path(__file__).resolve().parents[4]
_JUDGMENT = _ROOT / "docs/calibration/lf6t3n-labels-judgment.csv"
_MECHANICAL = _ROOT / "docs/calibration/lf6t3n-labels-mechanical.csv"


def _rows(path: Path) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(path.read_text(encoding="utf-8"))))


# --------------------------------------------------------------------------- #
# D1 — the SOURCE-TRACE reframing: has_identified_source reads as a DISTINCT question (the generator)
# --------------------------------------------------------------------------- #
def test_generator_frames_has_identified_source_distinctly_from_category() -> None:
    rows = build_worksheet(build_lf6t3n_snapshot(), document_filenames=LF6T3N_DOCUMENT_FILENAMES)
    src = [r for r in rows if r.tag_id == "txn.has_identified_source"]
    cat = {r.subject_id: r for r in rows if r.tag_id == "txn.apparent_category"}
    assert src, "has_identified_source produces no rows"
    for r in src:
        # LP-390-3a: the transaction IDENTITY leads (like apparent_category — no boilerplate-first repeat),
        # THEN a short distinct SOURCE-TRACE question naming the ORIGIN/traceable framing.
        assert r.context.startswith("date=")  # facts first
        assert "SOURCE-TRACE" in r.context and "ORIGIN" in r.context
        assert r.context.isascii()  # LP-390-3a: plain ASCII — no mojibake em-dashes
        # on the SAME transaction, the two rows now differ (the redundancy Priya saw is gone).
        same_txn = cat.get(r.subject_id)
        assert same_txn is not None and r.context != same_txn.context


def test_only_the_sourcing_tag_carries_the_question_every_other_context_is_facts_only() -> None:
    # The prompt is opt-in per tag: apparent_category (and every non-sourcing tag) keeps its facts-only
    # context — the reframe is surgical, not a blanket change. Every txn row leads with the facts now.
    rows = build_worksheet(build_lf6t3n_snapshot(), document_filenames=LF6T3N_DOCUMENT_FILENAMES)
    for r in rows:
        if r.tag_id != "txn.has_identified_source":
            assert "SOURCE-TRACE" not in r.context


# --------------------------------------------------------------------------- #
# The committed sheet — the instrument Priya opens
# --------------------------------------------------------------------------- #
def test_committed_has_identified_source_rows_carry_the_framing() -> None:
    src = [r for r in _rows(_JUDGMENT) if r["tag_id"] == "txn.has_identified_source"]
    assert src
    for r in src:
        assert r["context"].startswith("date=")  # LP-390-3a: identity leads, not boilerplate
        assert "SOURCE-TRACE" in r["context"]  # the distinct question is present
        assert r["context"].isascii()  # LP-390-3a: no mojibake
    # and it stays a DIFFERENT question from apparent_category on the same transaction.
    cat = {r["subject_id"]: r for r in _rows(_JUDGMENT) if r["tag_id"] == "txn.apparent_category"}
    assert all(r["context"] != cat.get(r["subject_id"], {}).get("context") for r in src)


# --------------------------------------------------------------------------- #
# D2 — the address correction: a NAME where an address belongs is fixed to the address
# --------------------------------------------------------------------------- #
def test_address_goldens_are_addresses_not_names() -> None:
    addr = [r for r in _rows(_MECHANICAL) if r["tag_id"] == "id.address_normalized"]
    names = {r["golden_label"] for r in _rows(_MECHANICAL) if r["tag_id"] == "id.name_normalized"}
    assert len(addr) == 2
    for r in addr:
        g = r["golden_label"]
        assert g and g not in names  # no borrower NAME sitting in the address golden
        assert any(ch.isdigit() for ch in g)  # a real street address carries a number
        # the golden is the address the source document states (recoverable from the row's own context).
        assert g in r["context"]


# --------------------------------------------------------------------------- #
# THE GOVERNING RULE — every filled label + note survives (122 goldens, 35 notes)
# --------------------------------------------------------------------------- #
def test_all_priya_labels_and_notes_are_preserved() -> None:
    jrows, mrows = _rows(_JUDGMENT), _rows(_MECHANICAL)
    goldens = sum(1 for r in jrows + mrows if r.get("golden_label", "").strip())
    notes = sum(1 for r in jrows if r.get("Note", "").strip())
    # LP-390-3a adopted Priya's active labeling copy: 78 judgment (she labeled all 16 has_identified_source
    # once reframed, + owner_matches_borrower + has_2yr_history) + 70 mechanical = 148, and the 35 notes.
    assert goldens == 148
    assert notes == 35


def test_orphan_sourcing_tags_are_dropped_from_the_worksheet() -> None:
    # LP-390-3a: txn.counterparty / txn.source_reference are free_text_deferred AND orphans (no producer) —
    # non-labelable, so they add only noise. Dropped from the generator (and the committed sheet).
    tags = {r.tag_id for r in build_worksheet(build_lf6t3n_snapshot())}
    assert "txn.counterparty" not in tags and "txn.source_reference" not in tags
    assert "txn.has_identified_source" in tags  # the labelable, producer-backed sourcing tag stays
    assert not any(
        r["tag_id"] in ("txn.counterparty", "txn.source_reference") for r in _rows(_JUDGMENT)
    )


# --------------------------------------------------------------------------- #
# The deferred rules (LP-390-2a) add no separately-labelable row; their tags serve calibration-ready siblings
# --------------------------------------------------------------------------- #
def test_deferred_in12_as5_add_no_new_labelable_tag() -> None:
    tags = {r.tag_id for r in build_worksheet(build_lf6t3n_snapshot())}
    # IN-12 / AS-5 are producer-blocked (LP-390-2a); their tags are labeled for the READY consumers
    # (has_2yr_history for IN-11, apparent_category for AS-2) — no IN-12/AS-5-only tag exists to add.
    assert "income.has_2yr_history" in tags and "txn.apparent_category" in tags
