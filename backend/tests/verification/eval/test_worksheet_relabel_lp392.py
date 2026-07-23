"""LP-392 — the real-DB worksheet re-flags a name-match golden for re-label instead of carrying it.

When the worksheet is regenerated from the REAL loan file (real identities) but Priya's prior labels were
judged against the DE-IDENTIFIED fixture, a name-match golden (``stmt.owner_matches_borrower`` — "does this
account holder match the borrower?") CANNOT safely carry: its fixture 'yes' (Jordan==Jordan) is not evidence
the real account self-matches. These pin that such a golden is BLANKED + FLAGGED for re-label (never silently
carried), a normal golden still carries, and the FIXTURE path (no relabel set) is byte-unchanged — all keyless,
no real DB, no PII.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

from app.verification.eval.db_worksheet import RELABEL_ON_REAL_CONTEXT
from app.verification.eval.lf6t3n_fixture import (
    LF6T3N_DOCUMENT_FILENAMES,
    build_lf6t3n_snapshot,
)
from app.verification.eval.worksheet import write_worksheets

# a bank-statement subject the fixture worksheet carries both tags on (same content_id as the DB)
_STMT = "doce9fa604faeb2faaa"
_NAME_MATCH = "stmt.owner_matches_borrower"
_NORMAL = "stmt.is_reserve_eligible"


def _seed(out_dir: Path) -> None:
    # a prior worksheet with two filled goldens on the same subject: a name-match one + a normal one
    rows = [
        {
            "tag_id": _NAME_MATCH,
            "subject_id": _STMT,
            "golden_label": "yes",
            "labeler_note": "matches",
        },
        {"tag_id": _NORMAL, "subject_id": _STMT, "golden_label": "no", "labeler_note": ""},
    ]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=["tag_id", "subject_id", "golden_label", "labeler_note"])
    w.writeheader()
    w.writerows(rows)
    (out_dir / "lf6t3n-labels-judgment.csv").write_text(buf.getvalue(), encoding="utf-8")


def _rows(path: Path) -> dict[tuple[str, str], dict[str, str]]:
    return {
        (r["tag_id"], r["subject_id"]): r
        for r in csv.DictReader(io.StringIO(path.read_text(encoding="utf-8")))
    }


def _write(out_dir: Path, relabel: frozenset[str]) -> dict[tuple[str, str], dict[str, str]]:
    written = write_worksheets(
        build_lf6t3n_snapshot(),
        out_dir,
        document_filenames=LF6T3N_DOCUMENT_FILENAMES,
        relabel_on_context_change=relabel,
    )
    return _rows(written["judgment"])


def test_db_path_flags_owner_matches_borrower_never_carries_it(tmp_path: Path) -> None:
    _seed(tmp_path)
    rows = _write(tmp_path, RELABEL_ON_REAL_CONTEXT)
    name_match = rows[(_NAME_MATCH, _STMT)]
    # the name-match golden is BLANKED and FLAGGED — the prior 'yes' is NOT shipped as a real-data golden
    assert name_match["golden_label"] == ""
    assert "RE-LABEL" in name_match["labeler_note"]
    # a NORMAL golden on the same subject still carries verbatim (its meaning did not change)
    assert rows[(_NORMAL, _STMT)]["golden_label"] == "no"


def test_fixture_path_carries_everything_when_no_relabel_set(tmp_path: Path) -> None:
    _seed(tmp_path)
    rows = _write(tmp_path, frozenset())  # the default fixture path
    # with no relabel set the name-match golden carries UNCHANGED — the fixture path is byte-identical to before
    assert rows[(_NAME_MATCH, _STMT)]["golden_label"] == "yes"
    assert rows[(_NORMAL, _STMT)]["golden_label"] == "no"


def test_the_declared_relabel_set_is_the_name_match_tag() -> None:
    # the real-DB path re-flags exactly the name-match judgment (declared, not a scattered per-call literal)
    assert frozenset({"stmt.owner_matches_borrower"}) == RELABEL_ON_REAL_CONTEXT
