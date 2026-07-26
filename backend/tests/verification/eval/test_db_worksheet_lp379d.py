"""LP-379-D — the DB-sourced calibration worksheet path + the scorable-now-vs-held split.

Priya labeled the COMMITTED FIXTURE worksheet (her subject_ids are the fixture's), so her labels already join
to the fixture and are scorable there — the "real-DB subject_id mismatch" premise is refuted (pinned below).
This ticket adds a SEPARATE, deliberate DB-sourced path for a future round that labels the real DOCUMENTS,
with two guarantees these tests pin: (1) the real-PII worksheet can NEVER be written to a committable in-repo
path (fail-closed guard), and (2) the held tags (apparent_category / has_identified_source) are excluded from
scoring EXPLICITLY, never silently. The fixture path (worksheet.py) is untouched.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from app.verification.eval import db_worksheet
from app.verification.eval.db_worksheet import (
    HELD_FOR_RELABELING,
    guard_pii_safe_out_dir,
    stable_scorable_goldens,
    write_db_worksheets,
)
from app.verification.eval.lf6t3n_fixture import LF6T3N_DOCUMENT_FILENAMES, build_lf6t3n_snapshot
from app.verification.eval.worksheet import build_worksheet, load_golden

pytestmark = pytest.mark.anyio

_REPO_ROOT = Path(__file__).resolve().parents[4]
_CALIBRATION = _REPO_ROOT / "docs" / "calibration"


# --------------------------------------------------------------------------- #
# PII CONTAINMENT — the real-PII worksheet can never land on a committable path
# --------------------------------------------------------------------------- #
def test_guard_refuses_committable_in_repo_paths() -> None:
    for bad in (_CALIBRATION, _REPO_ROOT / "backend" / "app", _REPO_ROOT):
        with pytest.raises(ValueError, match="refusing to write a real-PII"):
            guard_pii_safe_out_dir(bad)


def test_guard_allows_outside_repo_and_gitignored_calibration_local(tmp_path) -> None:
    assert guard_pii_safe_out_dir(tmp_path) == tmp_path.resolve()  # outside the repo
    local = _REPO_ROOT / "calibration-local" / "run1"
    assert guard_pii_safe_out_dir(local) == local.resolve()  # the gitignored in-repo dir


def test_calibration_local_is_gitignored() -> None:
    # the belt-and-suspenders: even the in-repo allowed dir is ignored by git
    assert "calibration-local/" in (_REPO_ROOT / ".gitignore").read_text(encoding="utf-8")


async def test_write_db_worksheets_writes_to_the_given_pii_safe_dir(tmp_path, monkeypatch) -> None:
    # reuse the SAME generator; only the snapshot source is mocked (no real DB / no real PII in the test).
    loan_file = SimpleNamespace(id=uuid4(), company_id=uuid4(), display_id="LF-6T3N")

    class _Result:
        def scalar_one(self):
            return loan_file

    class _Session:
        async def execute(self, _query):
            return _Result()

    async def _fake_build_snapshot(session, *, loan_file_id, run_id, company_id):
        return build_lf6t3n_snapshot()

    async def _fake_filenames(session, lf):
        return LF6T3N_DOCUMENT_FILENAMES

    monkeypatch.setattr(db_worksheet, "build_snapshot", _fake_build_snapshot)
    monkeypatch.setattr(db_worksheet, "document_filenames_by_content_id", _fake_filenames)

    written = await write_db_worksheets(_Session(), "LF-6T3N", tmp_path)
    assert set(written) == {"mechanical", "judgment"}
    for path in written.values():
        assert (
            path.is_file() and tmp_path in path.parents
        )  # written ONLY under the given PII-safe dir
    # and it reused the generator (real source_document column present)
    header = (tmp_path / "lf6t3n-labels-judgment.csv").read_text().splitlines()[0]
    assert "source_document" in header


async def test_write_db_worksheets_refuses_a_committable_dir() -> None:
    with pytest.raises(ValueError, match="refusing to write a real-PII"):
        await write_db_worksheets(object(), "LF-6T3N", _CALIBRATION)  # guarded before any DB access


# --------------------------------------------------------------------------- #
# THE GATE-OF-RECORD FINDING — Priya's labels join to the FIXTURE she labeled
# --------------------------------------------------------------------------- #
def test_priyas_labels_join_to_the_fixture_worksheet() -> None:
    goldens: dict[tuple[str, str], str] = {}
    for name in ("mechanical", "judgment"):
        goldens.update(load_golden((_CALIBRATION / f"lf6t3n-labels-{name}.csv").read_text()))
    row_keys = {
        (r.tag_id, r.subject_id)
        for r in build_worksheet(
            build_lf6t3n_snapshot(), document_filenames=LF6T3N_DOCUMENT_FILENAMES
        )
    }
    unjoined = [k for k in goldens if k not in row_keys]
    assert goldens and unjoined == []  # every filled label joins to the fixture — nothing to re-map


# --------------------------------------------------------------------------- #
# THE HELD SPLIT — apparent_category / has_identified_source are held EXPLICITLY
# --------------------------------------------------------------------------- #
def test_held_tags_are_excluded_explicitly_not_silently() -> None:
    assert {"txn.apparent_category", "txn.has_identified_source"} == HELD_FOR_RELABELING
    goldens = {
        ("txn.is_money_in", "t1"): "in",
        ("txn.apparent_category", "t1"): "transfer to some one",  # free text — held
        ("txn.has_identified_source", "t1"): "yes",  # held
        ("id.name_normalized", "d1"): "Jordan A Rivera",
    }
    stable = stable_scorable_goldens(goldens)
    assert set(stable) == {("txn.is_money_in", "t1"), ("id.name_normalized", "d1")}
    assert all(k[0] not in HELD_FOR_RELABELING for k in stable)
