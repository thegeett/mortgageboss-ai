"""LP-519 — delete the findings of the withdrawn AS-13 rule.

AS-13 was removed from the catalog after breaking staging twice (see registry.py). Pulling the spec
stops NEW findings, but it does not remove the row already written: a finding is retired only by
`reconcile_evaluation_findings`, which loads prior findings for rules in `evaluated_rule_ids` — a set
AS-13 is no longer in. So the row would sit in Needs Attention forever, telling a processor that
"the 'Repeated same-amount deposits' check is not active yet" for a check that no longer exists.

Deleting rather than soft-deleting is deliberate. The immortality rule ("a finding is never destroyed,
only retired") protects a HUMAN's work: a resolution, an override, a note. This row has none — it is a
`pending_automation` marker minted by the pending-checks pass, derived fresh every run and never
actionable. Nothing is lost that anyone entered.

Scoped to AS-13 by name. A sweep over "every rule_id no longer in the catalog" would be more general
and much more dangerous — it would delete the findings of any rule temporarily removed for any reason.

Revision ID: d5c81b6a47f2
Revises: b7f1a4c93e08
Create Date: 2026-08-17 20:10:00.000000
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d5c81b6a47f2"  # pragma: allowlist secret
down_revision: str | None = "b7f1a4c93e08"  # pragma: allowlist secret
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    # finding_events first — it FKs to findings with ON DELETE CASCADE, but being explicit keeps the
    # intent readable and does not depend on the cascade staying configured that way.
    op.execute(
        "DELETE FROM finding_events WHERE finding_id IN "
        "(SELECT id FROM findings WHERE rule_id = 'AS-13')"
    )
    op.execute("DELETE FROM findings WHERE rule_id = 'AS-13'")


def downgrade() -> None:
    """Nothing to restore.

    The rows were derived per run by the pending-checks pass, never authored. Re-creating a synthetic
    one would fabricate a finding that no run produced — worse than the gap it fills. When AS-13 is
    reinstated its findings are minted by the next verification run, as they always were.
    """
