"""The visual-check harness must never open the dev database (LP-934 review).

WHY THIS EXISTS. `scripts/visual-check/seed.py` writes a whole loan file — a processor, a borrower,
a round, conditions — and `run.sh` drops and re-creates the database it is given first. Pointed at
`mortgageboss_dev` that is not a bad screenshot, it is the dev database gone. The guard that prevents
it is four lines, and until this test nothing would have failed if a later edit had removed them: the
refusal was checked by hand when the harness was written and by nothing afterwards.

IT READS THE REAL MODULE, not a copy of its rule. `seed.py` runs the guard at import time only under
`__main__`, so importing it here is safe and gives the function itself to call.

BOTH DIRECTIONS, because a test that only asserts a refusal passes just as well on a guard that
refuses everything — including the scratch databases the harness is supposed to use.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

_SEED = Path(__file__).resolve().parents[3] / "scripts" / "visual-check" / "seed.py"


@pytest.fixture(scope="module")
def seed() -> ModuleType:
    """`seed.py` imported as a module, so `__name__ != "__main__"` and the guard does not run."""
    spec = importlib.util.spec_from_file_location("visual_check_seed", _SEED)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _url(database: str) -> str:
    return f"postgresql+asyncpg://user:pw@localhost:5432/{database}"  # pragma: allowlist secret


@pytest.mark.parametrize(
    "database",
    ["mortgageboss_dev", "mortgageboss_dev_test", "postgres", "", "mbai_visual"],
)
def test_a_database_that_is_not_a_visual_scratch_is_refused(
    seed: ModuleType, database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Anything without the `mbai_visual_` prefix stops the harness before it opens a connection.

    `mbai_visual` is in the list on purpose: it is the prefix without its underscore, the near miss a
    typo produces.
    """
    monkeypatch.setenv("DATABASE_URL", _url(database))
    with pytest.raises(SystemExit) as exit_info:
        seed._refuse_unless_scratch()
    assert "refused" in str(exit_info.value)


def test_the_dev_database_is_refused_even_if_it_were_named_like_a_scratch_one(
    seed: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The second branch: the name matches `backend/.env`'s own database.

    The dev name is patched rather than read from `.env`, so this asserts the branch itself and not
    whatever happens to be configured on the machine running it.
    """
    monkeypatch.setattr(seed, "_dev_database_name", lambda: "mbai_visual_stage3")
    monkeypatch.setenv("DATABASE_URL", _url("mbai_visual_stage3"))
    with pytest.raises(SystemExit) as exit_info:
        seed._refuse_unless_scratch()
    assert "is the dev database" in str(exit_info.value)


def test_a_real_scratch_database_is_allowed(
    seed: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The positive control. Without it, a guard that refused every database would pass the tests above.

    It also pins the return value, which `run.sh` prints and the seed uses as the database it wrote.
    """
    monkeypatch.setattr(seed, "_dev_database_name", lambda: "mortgageboss_dev")
    monkeypatch.setenv("DATABASE_URL", _url("mbai_visual_stage3"))
    assert seed._refuse_unless_scratch() == "mbai_visual_stage3"
