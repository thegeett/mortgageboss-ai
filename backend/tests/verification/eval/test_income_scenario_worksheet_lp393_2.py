"""LP-393-2 — the scenario labeling worksheet for Priya's BLIND labeling.

ANTI-ANCHORING is the ticket: LP-393-1 already ran the real AI on these scenarios and reported its answers, and
CLEARCUT_EXPECTATIONS holds B3-B8's expected values — NEITHER may reach Priya's sheet, or her label measures
agreement-with-what-we-showed-her, not independent judgment. These pin (KEYLESS, deterministic): the sheet has
rows only for the 4 viable tags; every golden cell is EMPTY; the prompt is UNIFORM per tag (so no per-row answer
can be encoded); no prediction/confidence/reasoning column exists; and the generator reads only the snapshot's
facts (no model, no expectations).
"""

from __future__ import annotations

import csv
import inspect
import io
from pathlib import Path

from app.verification.eval import income_scenarios, worksheet
from app.verification.eval.income_scenarios import (
    CLEARCUT_EXPECTATIONS,
    SCENARIO_LABEL_PROMPTS,
    SCENARIO_WORKSHEET_FILE,
    SCENARIO_WORKSHEET_TAGS,
    write_income_scenario_worksheet,
)


def _rows(tmp_path: Path) -> list[dict[str, str]]:
    path = write_income_scenario_worksheet(tmp_path)
    assert path.name == SCENARIO_WORKSHEET_FILE
    return list(csv.DictReader(io.StringIO(path.read_text(encoding="utf-8"))))


# --------------------------------------------------------------------------- #
# ROWS — only the 4 viable tags; the thin / un-exercisable ones excluded (no blank rows)
# --------------------------------------------------------------------------- #
def test_only_the_four_viable_tags_get_rows(tmp_path: Path) -> None:
    rows = _rows(tmp_path)
    by_tag: dict[str, int] = {}
    for r in rows:
        by_tag[r["tag_id"]] = by_tag.get(r["tag_id"], 0) + 1
    assert set(by_tag) == SCENARIO_WORKSHEET_TAGS  # exactly the 4 — nothing else
    # granularity: one row per borrower for the income tags (13 scenario borrowers), one per asset doc (6)
    assert by_tag["income.has_2yr_history"] == 13
    assert by_tag["income.is_declining"] == 13
    assert by_tag["income.same_line_of_work"] == 13
    assert by_tag["asset.liquidation_terms"] == 6
    # the EXCLUDED tags have no rows (continuance_3yr n=1; the already-calibrated extraction tags)
    for excluded in ("income.continuance_3yr", "income.documented_monthly", "income.type"):
        assert excluded not in by_tag


# --------------------------------------------------------------------------- #
# ANTI-ANCHORING — no prediction / expected answer / per-row hint reaches the sheet
# --------------------------------------------------------------------------- #
def test_no_golden_is_pre_filled_and_no_prediction_column_exists(tmp_path: Path) -> None:
    rows = _rows(tmp_path)
    assert rows
    # every answer cell is EMPTY — the labeler supplies the golden; we ship none
    assert all(not (r.get("golden_label") or "").strip() for r in rows)
    assert all(not (r.get("labeler_note") or "").strip() for r in rows)
    # no column carries a model output (prediction / confidence / reasoning)
    cols = {c.lower() for c in rows[0]}
    assert not (cols & {"prediction", "predicted", "confidence", "reasoning", "ai_value"})


def test_prompt_is_uniform_per_tag_so_no_per_row_answer_is_encoded(tmp_path: Path) -> None:
    rows = _rows(tmp_path)
    # the context ends with the tag's prompt; that prompt must be IDENTICAL across every row of a tag — a
    # per-row hint (an answer smuggled into one row's context) would make the tail differ.
    for tag in SCENARIO_WORKSHEET_TAGS:
        tails = {r["context"].rsplit(" | ", 1)[-1] for r in rows if r["tag_id"] == tag}
        assert len(tails) == 1, f"{tag}: prompt/tail varies per row (possible anchoring)"
        (tail,) = tails
        assert tail == SCENARIO_LABEL_PROMPTS[tag]  # exactly the neutral declared prompt


def test_the_generator_cannot_reach_expectations_or_the_model() -> None:
    # the anti-anchoring PROOF at the source: build_worksheet takes only snapshot + facts-shaping params — no
    # expectations, no reasoner; and the scenario writer never passes CLEARCUT_EXPECTATIONS to it.
    params = set(inspect.signature(worksheet.build_worksheet).parameters)
    assert params == {"snapshot", "document_filenames", "only_tags", "label_prompts"}
    writer_src = inspect.getsource(income_scenarios.write_income_scenario_worksheet)
    assert "CLEARCUT_EXPECTATIONS" not in writer_src  # expectations never flow into the sheet
    assert "reasoner" not in writer_src and "materialize" not in writer_src  # no model call


def test_prompts_are_neutral_questions_not_leading() -> None:
    # each prompt asks the OPEN question + lists the allowed values — never asserts an answer ("this looks like…")
    for prompt in SCENARIO_LABEL_PROMPTS.values():
        assert "?" in prompt
        assert "unknown" in prompt  # the honest option is always offered
        low = prompt.lower()
        assert "looks like" not in low and "confirm" not in low and "probably" not in low


# --------------------------------------------------------------------------- #
# COMMITTABLE + DETERMINISTIC + LF-6T3N UNCHANGED
# --------------------------------------------------------------------------- #
def test_no_real_pii_and_deterministic(tmp_path: Path) -> None:
    text = (write_income_scenario_worksheet(tmp_path)).read_text(encoding="utf-8")
    for marker in ("AKASH", "BANSARI", "BofA", "Wells", "Jordan Rivera", "First Springfield"):
        assert marker not in text  # invented identities only — committable, no real PII
    # deterministic + keyless: a second generation is byte-identical (no model, no clock)
    text2 = (write_income_scenario_worksheet(tmp_path / "again")).read_text(encoding="utf-8")
    assert text == text2


def test_lf6t3n_worksheet_generation_is_unchanged() -> None:
    # build_worksheet with default params (the LF-6T3N path) still enumerates EVERY tag — the LP-393-2 params
    # default to None, so the committed fixture worksheet is byte-unchanged (its finalize test still passes).
    from app.verification.eval.lf6t3n_fixture import (
        LF6T3N_DOCUMENT_FILENAMES,
        build_lf6t3n_snapshot,
    )

    tags = {
        r.tag_id
        for r in worksheet.build_worksheet(
            build_lf6t3n_snapshot(), document_filenames=LF6T3N_DOCUMENT_FILENAMES
        )
    }
    # the default sheet is NOT restricted to the scenario's 4 — it carries the full tag set (e.g. txn tags)
    assert "txn.apparent_category" in tags and len(tags) > len(SCENARIO_WORKSHEET_TAGS)
    for e in (
        CLEARCUT_EXPECTATIONS.values()
    ):  # sanity: expectations dict is populated (guards the leak test)
        assert e
