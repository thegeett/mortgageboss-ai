"""LP-509-B1 — capture the MISMO property PROJECT indicators.

`properties.property_type` is null on LF-WCHG (the export states an empty PropertyType), so
`property.type` never materialized and CO-1 / CO-3 / CO-4 / IH-7 all reported "the property type has
not been determined". The export does carry what decides it:

    <AttachmentType>Detached</AttachmentType>
    <PropertyInProjectIndicator>false</PropertyInProjectIndicator>   <-- decisive
    <PUDIndicator>false</PUDIndicator>
    <FinancedUnitCount>1</FinancedUnitCount>

and the parser captured neither indicator. `PropertyInProjectIndicator = false` is what rules a
condominium out — a condominium is by definition a property in a project. `AttachmentType` alone is
NOT sufficient and is not used that way: Fannie Mae recognises DETACHED condominiums.

Both columns are NULLABLE and TRI-STATE: null means the export did not state it, which must abstain.
Null is never read as false.

Stored raw rather than folded into `property_type` during import, so the classification stays a
decision the tag layer derives and can revisit; folding it in at import would discard the evidence.

The `readonly.properties` view is recreated to expose them (structural booleans, no PII) — required
by the C7 drift guard, which holds that every model column is either in a view or explicitly
excluded with a reason.
"""

import importlib.util
import re
from collections.abc import Sequence
from pathlib import Path

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3e940f8ee9d"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "d4e8a1c05b73"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROLE = "mbai_readonly"
_SCHEMA = "readonly"

# Recreated in BOTH directions, so a downgrade leaves the view matching the columns that still
# exist. Dropping only this one view (rather than the whole schema) keeps the change reviewable and
# leaves the other 31 untouched.
_PROPERTIES_VIEW_WITH_INDICATORS = f"""
CREATE VIEW {_SCHEMA}.properties AS
SELECT id, loan_file_id, city, state, property_type, occupancy_type,
       attachment_type, construction_method, financed_unit_count,
       in_project, is_pud,
       estimated_value, purchase_price, valuation_amount,
       created_at, updated_at, deleted_at
FROM public.properties
"""


def _c7_properties_view() -> str:
    """C7's own `readonly.properties` definition, for the downgrade.

    READ FROM C7 RATHER THAN COPIED. A second copy of the view text here would be a copy that can
    drift from the one C7 actually shipped, and it would also be a second `CREATE VIEW … FROM
    public.properties` in this file — which the drift guard scans for, and which (being later in the
    file) would win and make the guard check the PRE-change definition.
    """
    c7_path = Path(__file__).resolve().parent / (
        "20260814_2300_d4e8a1c05b73_c7_readonly_query_schema.py"
    )
    spec = importlib.util.spec_from_file_location("c7_for_downgrade", c7_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for view in module._VIEWS:
        if re.search(r"FROM\s+public\.properties\b", view):
            return str(view)
    raise RuntimeError("C7 no longer defines a readonly.properties view")


def _regrant() -> None:
    """Re-grant SELECT on the rebuilt view, but only where the role exists.

    The role is deliberately NOT created by any migration — it exists in staging only (C7). In
    production this is a no-op, exactly as it is there.
    """
    op.execute(f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{_ROLE}') THEN
                EXECUTE 'GRANT SELECT ON {_SCHEMA}.properties TO {_ROLE}';
            END IF;
        END
        $$;
    """)


def upgrade() -> None:
    op.add_column("properties", sa.Column("in_project", sa.Boolean(), nullable=True))
    op.add_column("properties", sa.Column("is_pud", sa.Boolean(), nullable=True))
    # ADD COLUMN does not require dropping the view (only a type change or a drop would); the view
    # is rebuilt so the new columns are actually SELECTable through the read-only path.
    op.execute(f"DROP VIEW IF EXISTS {_SCHEMA}.properties")
    op.execute(_PROPERTIES_VIEW_WITH_INDICATORS)
    _regrant()


def downgrade() -> None:
    # The view must go first here: it SELECTs the columns being dropped, and PostgreSQL refuses
    # DROP COLUMN while a view depends on it.
    op.execute(f"DROP VIEW IF EXISTS {_SCHEMA}.properties")
    op.drop_column("properties", "is_pud")
    op.drop_column("properties", "in_project")
    op.execute(_c7_properties_view())
    _regrant()
