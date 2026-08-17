"""LP-521 — the MIGRATED database must store every outcome the engine can produce.

WHAT HAPPENED. LP-316 created three CHECK constraints over a five-value outcome list. LP-391 added a
sixth value, `pending_automation`, to the Python enum and to the engine — and never extended the
constraints. LP-519's AS-13 is inert by design and reads a LOAN-subject derived tag that materialises on
every file, so the pending-checks pass emitted `pending_automation` on the first real run after deploy.
The insert was rejected, the rule-engine task retried, and each retry re-ran the whole AI pipeline —
about six minutes and real Bedrock spend per attempt. Every verification on every file failed.

⚠️ WHY THIS TEST READS MIGRATION FILES AND NOT THE DATABASE. `tests/conftest.py` builds the test schema
with `Base.metadata.create_all`, so a constraint SQLAlchemy derives from the enum is regenerated from
that same enum on every run — it agrees with the enum by construction and can never catch drift. A
first draft of this file asserted against the live test-DB constraint and passed whether or not the
migration existed: a guard that could not fail. Staging and production are built from MIGRATIONS, so
the migrations are what has to be checked.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from app.models.finding import EvaluationOutcome

_VERSIONS = Path(__file__).resolve().parents[2] / "alembic" / "versions"

# The three constraints sharing one outcome list. A finding that cannot TRANSITION to an outcome is as
# broken as one that cannot be written with it, so all three are guarded.
_CONSTRAINTS = (
    "ck_findings_evaluationoutcome",
    "ck_finding_events_finding_event_from_outcome",
    "ck_finding_events_finding_event_to_outcome",
)


def _defining_migration(constraint: str) -> Path:
    """The NEWEST migration that defines this constraint — the one whose definition is live.

    Newest wins because a later migration rebuilds what an earlier one created. Ordering is by
    filename, which is date-prefixed by this repo's convention.
    """
    defining = sorted(p for p in _VERSIONS.glob("*.py") if constraint in p.read_text())
    assert defining, f"no migration defines {constraint}"
    return defining[-1]


def _declared_values(path: Path) -> set[str]:
    """Every quoted lowercase token in the migration's outcome tuple(s).

    Deliberately crude: it reads what the file SAYS rather than importing and executing it, so a
    migration that builds its list dynamically fails this test loudly instead of being trusted.
    """
    text = path.read_text()
    tuples = re.findall(r"_OUTCOMES\s*=\s*\(([^)]*)\)", text, flags=re.DOTALL)
    assert tuples, f"{path.name} defines no _OUTCOMES tuple this guard can read"
    return {v.strip().strip("\"'") for v in tuples[0].replace("\n", "").split(",") if v.strip()}


@pytest.mark.parametrize("constraint", _CONSTRAINTS)
def test_the_migrated_constraint_stores_every_python_outcome(constraint: str) -> None:
    """⚠️ THE GUARD THAT WAS MISSING FOR TWO TICKETS. Expectation derived from the ENUM, checked against
    the MIGRATION — so a seventh outcome added without a migration fails here, in CI, rather than six
    minutes into a live AI pipeline on staging."""
    migration = _defining_migration(constraint)
    declared = _declared_values(migration)

    missing = sorted(o.value for o in EvaluationOutcome if o.value not in declared)
    assert not missing, (
        f"{constraint} (defined in {migration.name}) cannot store {missing} — the Python enum and the "
        f"migrated constraint have drifted. Write a migration extending the constraint BEFORE shipping "
        f"an enum value; CI's create_all schema will not catch this for you."
    )


@pytest.mark.parametrize("constraint", _CONSTRAINTS)
def test_the_migrated_constraint_admits_nothing_the_enum_lacks(constraint: str) -> None:
    """Drift the other way: a value the database accepts but the engine can never produce is a stale
    constraint that would silently admit a typo'd outcome."""
    migration = _defining_migration(constraint)
    extras = sorted(_declared_values(migration) - {o.value for o in EvaluationOutcome})

    assert not extras, f"{constraint} admits value(s) the enum does not define: {extras}"


def test_pending_automation_specifically_is_migrated() -> None:
    """The value that broke staging, named explicitly — so the regression is legible in the test list
    rather than only inside a parametrized sweep."""
    migration = _defining_migration("ck_findings_evaluationoutcome")

    assert "pending_automation" in _declared_values(migration)


def test_pending_automation_is_reachable_from_the_engine() -> None:
    """The outcome is not decorative: LP-391's pending-checks pass emits it for a BLOCKED rule that
    finds something in its scope — which is exactly how AS-13 produced one. If the engine ever stops
    being able to emit it, the constraint could be narrowed again; but not before, and not silently."""
    from app.verification.rule_engine.result import Verdict

    assert Verdict.PENDING_AUTOMATION.value == EvaluationOutcome.PENDING_AUTOMATION.value
