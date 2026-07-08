"""LP round-3 seed/DB drift — align confidence_mode + applicability on existing DBs

Revision ID: c9a3e7f1b5d8
Revises: b6f2d9c4e1a8
Create Date: 2026-07-08 12:00:00.000000

Seeding is INSERT-ONLY, so two earlier seed-DATA changes never reached already-seeded DBs — the drift
this migration repairs (round-3 FIX 3 / FIX 4):

* **confidence_mode (FIX 3):** the FIX-6 vocabulary renamed the deterministic value ``"certain" →
  "deterministic"`` in the seed. Existing rows kept ``"certain"`` while the runner emits
  ``"deterministic"``, so the "joinable with no translation" guarantee was false off a fresh DB. Rename
  every ``"certain"`` row to ``"deterministic"`` (``"computed"`` / NULL untouched).

* **applicability (FIX 4):** FIX 3b moved rules to the wire shape (scope/triggers/required_inputs) +
  ``extra="forbid"``, but only AS-5 got a rewrite migration. Legacy FLAT rows (e.g.
  ``xsrc.terms.price_vs_contract = {"purpose": "purchase"}``) remain — and when the engine is wired they
  fail ``extra="forbid"`` and silently degrade to couldn't-check. Repair each legacy-shape row: the one
  with known intent (PC-2 → purchase) is translated to correct wire scope; any other not-yet-built
  legacy row is nulled (universal → authored properly when its rule is built), never left in a degrading
  shape. AS-5 and all valid wire shapes are untouched, so this is a no-op on a fresh (clean) DB.

Data-only; no schema change; no live-path behaviour change (nothing reads these on the live path yet).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c9a3e7f1b5d8"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "b6f2d9c4e1a8"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_WIRE_KEYS = {"scope", "triggers", "required_inputs"}

# Legacy flat rows with KNOWN intent → the correct wire scope (round-3 FIX 4). Everything not listed
# here that is still in a legacy shape is nulled (unbuilt → authored when its rule is built).
_KNOWN_WIRE: dict[str, dict] = {
    "xsrc.terms.price_vs_contract": {  # PC-2 — {"purpose": "purchase"} → purchase scope
        "scope": {"loan_purpose": ["purchase"]},
        "triggers": {},
        "required_inputs": [],
    },
}


def _rules_table() -> sa.TableClause:
    return sa.table(
        "verification_rules",
        sa.column("rule_id", sa.Text()),
        sa.column("applicability", sa.JSON()),
        sa.column("confidence_mode", sa.String()),
    )


def upgrade() -> None:
    bind = op.get_bind()
    rules = _rules_table()

    # FIX 3 — confidence_mode: rename the deterministic value to the FIX-6 vocabulary.
    op.execute(
        rules.update()
        .where(rules.c.confidence_mode == "certain")
        .values(confidence_mode="deterministic")
    )

    # FIX 4 — applicability: repair legacy FLAT shapes (a dict with keys outside the wire set). A row
    # with known intent → its wire scope; any other legacy row → NULL (universal, authored later). Valid
    # wire shapes and NULLs are left alone, so this no-ops on a fresh DB.
    existing = bind.execute(sa.select(rules.c.rule_id, rules.c.applicability)).all()
    for rule_id, applicability in existing:
        if not isinstance(applicability, dict):
            continue
        if not (set(applicability.keys()) - _WIRE_KEYS):
            continue  # already a valid wire shape (only scope/triggers/required_inputs)
        repaired = _KNOWN_WIRE.get(rule_id)  # None → null it (unbuilt, intent uncertain)
        op.execute(rules.update().where(rules.c.rule_id == rule_id).values(applicability=repaired))


def downgrade() -> None:
    """Intentionally a NO-OP.

    The seed now carries the FIX-6 confidence_mode vocabulary and the wire applicability shape, so on a
    fresh DB these rows are already aligned BEFORE this migration runs (it no-ops). Reverting to the old
    ``"certain"`` vocab or the flat applicability shape would re-introduce exactly the drift this fixes —
    a state matching neither the seed nor the runner — so downgrade leaves the aligned values in place.
    """
