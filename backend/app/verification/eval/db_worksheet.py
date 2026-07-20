"""LP-379-D — the DB-SOURCED calibration worksheet path (real loan file, for a HUMAN labeling round).

The FIXTURE path (``worksheet.py`` + ``build_lf6t3n_snapshot``) is the deterministic, keyless CI path — it is
UNTOUCHED by this module. This ADDS a second, clearly separated path that generates the worksheet from the
REAL DB loan file (``build_snapshot`` + the governed real ``original_filename`` map), so a domain expert labels
the actual documents she recognizes rather than the de-identified fixture (Jordan/Taylor).

⚠️ THE OUTPUT CARRIES REAL BORROWER PII (names, addresses, masked accounts) and MUST NEVER be committed — the
LP-210 posture (real-loan artifacts are generated locally for review only, `.gitignore`-d). A guard refuses any
in-repo, non-gitignored ``out_dir``, fail-closed. This path is DELIBERATE — never invoked by CI or a normal run.

Gate-of-record note (LP-379-D Phase 0): Priya's EXISTING 122 labels join to the FIXTURE worksheet 100% (she
labeled the committed fixture CSVs; her transaction labels are on verbatim transactions, her document labels
use the fixture context) — so they are already scorable against the fixture (``calibrate_lf6t3n``). This DB
path is for a FUTURE round that labels the real DOCUMENTS (income/id), where the fixture is synthetic.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.loan_file import LoanFile
from app.verification.eval.worksheet import write_worksheets
from app.verification.snapshot.builder import build_snapshot
from app.verification.snapshot.documents_section import document_filenames_by_content_id

# The repo root (…/mortgageboss-ai): db_worksheet.py is at backend/app/verification/eval/.
_REPO_ROOT = Path(__file__).resolve().parents[4]
# The gitignored path segment a real-PII worksheet may live under IN the repo (see .gitignore, LP-379-D).
_PII_SAFE_SEGMENT = "calibration-local"

# LP-379-D: tags HELD from scoring pending a re-label pass against the LP-379-E-widened enum. Priya's current
# apparent_category goldens are FREE TEXT ("transfer to some one", "Credit card payment"), not enum values;
# they need mapping to the widened enum before scoring. has_identified_source is unlabeled. The hold is
# EXPLICIT (this named set), reported in the calibration output — never a silent skip.
HELD_FOR_RELABELING = frozenset({"txn.apparent_category", "txn.has_identified_source"})


def stable_scorable_goldens(
    goldens: dict[tuple[str, str], str],
) -> dict[tuple[str, str], str]:
    """Priya's goldens MINUS the HELD tags — the stable-vocabulary labels scorable today. The exclusion is
    explicit (``HELD_FOR_RELABELING``), so a held tag is visibly held, never silently dropped from a run."""
    return {k: v for k, v in goldens.items() if k[0] not in HELD_FOR_RELABELING}


def guard_pii_safe_out_dir(out_dir: Path) -> Path:
    """A DB worksheet carries real PII — refuse to write it anywhere it could be committed. Allowed ONLY:
    OUTSIDE the repo tree, or under a gitignored ``calibration-local`` directory. Fail-closed — raises rather
    than writing PII to a committable path. Returns the resolved, approved path."""
    resolved = out_dir.resolve()
    try:
        resolved.relative_to(_REPO_ROOT)
    except ValueError:
        return resolved  # outside the repo tree — safe
    if _PII_SAFE_SEGMENT in resolved.parts:
        return resolved  # inside the repo but under the gitignored calibration-local/ — safe
    raise ValueError(
        f"refusing to write a real-PII DB calibration worksheet into the repo at {resolved} — choose a path "
        f"OUTSIDE the repo, or under a gitignored '{_PII_SAFE_SEGMENT}/' directory (LP-210 PII posture)"
    )


async def write_db_worksheets(
    session: AsyncSession, display_id: str, out_dir: Path
) -> dict[str, Path]:
    """Generate the calibration worksheets from the REAL DB loan file ``display_id`` into ``out_dir`` (which
    MUST be PII-safe — see :func:`guard_pii_safe_out_dir`). Reuses ``build_snapshot`` + the governed
    ``document_filenames_by_content_id`` + ``write_worksheets`` — the SAME generator as the fixture path, only
    the snapshot source differs. DELIBERATE: never called by CI or a normal run. Returns the written paths."""
    safe = guard_pii_safe_out_dir(out_dir)
    loan_file = (
        await session.execute(select(LoanFile).where(LoanFile.display_id == display_id))
    ).scalar_one()
    snapshot = await build_snapshot(
        session,
        loan_file_id=loan_file.id,
        run_id=uuid4(),
        company_id=loan_file.company_id,
    )
    filenames = await document_filenames_by_content_id(session, loan_file)
    return write_worksheets(snapshot, safe, document_filenames=filenames)


__all__ = [
    "HELD_FOR_RELABELING",
    "guard_pii_safe_out_dir",
    "stable_scorable_goldens",
    "write_db_worksheets",
]
