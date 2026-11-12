"""LP-MB-Admin-01 — roles as a set, the company owner, and the company audit log.

1. `user_roles` (one row per role a user holds, ADR-440) and `company_audit_log` (admin actions,
   ADR-441; `action` deliberately has no CHECK). `users.role`'s CHECK gains `loan_officer` so it
   agrees with the model, which shares the enum with `user_roles.role`.
2. Backfill `user_roles` from `users.role`, one row per user, deleted and inactive users included.
3. `companies.owner_user_id`: per company, the earliest-created active admin. A company with no
   active admin keeps NULL and is printed; `scripts/transfer_owner` sets it by hand. Each company
   gets one `role_backfilled` audit row saying what happened.
4. `users.role` becomes nullable: the app no longer writes it, and it has no server default. It is
   kept for one release so this can be rolled back; a later ticket drops it.

Downgrade copies the set back (`admin` if the user holds admin, else `processor`, so a loan officer
becomes a processor), restores NOT NULL and the two-value CHECK, and drops the column and tables.

5. Readonly: `readonly.users` is rebuilt WITHOUT `role`, so a staging query that still asks for the
   column fails instead of reading a frozen value, and `readonly.user_roles` is where roles are now
   read. Only ids, a role word and a timestamp, so every column is exposed. `company_audit_log`
   gets no view yet: `summary` and `detail` are prose and values and would need the scrub.

Hand-written, like every migration against this schema.

Revision ID: 0a7332974687
Revises: e3a9d4c7b512
Create Date: 2026-11-12 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0a7332974687"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "e3a9d4c7b512"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROLES = ("processor", "admin", "loan_officer")
_OLD_ROLES = ("processor", "admin")

_GRANT = """
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mbai_readonly') THEN
            EXECUTE 'GRANT SELECT ON readonly.users, readonly.user_roles TO mbai_readonly';
        END IF;
    END
    $$;
    """


def _swap_users_role_check(values: tuple[str, ...]) -> None:
    # Raw SQL, not `op.drop_constraint`, which applies the naming convention again (the LP-912 trap).
    joined = ", ".join(f"'{v}'" for v in values)
    op.execute("ALTER TABLE users DROP CONSTRAINT ck_users_userrole")
    op.execute(f"ALTER TABLE users ADD CONSTRAINT ck_users_userrole CHECK (role IN ({joined}))")


def upgrade() -> None:
    # 1. Tables.
    op.create_table(
        "user_roles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("granted_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_user_roles_user_id_users", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["granted_by_user_id"],
            ["users.id"],
            name="fk_user_roles_granted_by_user_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_user_roles"),
        sa.UniqueConstraint("user_id", "role", name="uq_user_roles_user_id_role"),
    )
    op.create_index("ix_user_roles_user_id", "user_roles", ["user_id"])
    joined = ", ".join(f"'{v}'" for v in _ROLES)
    op.execute(
        f"ALTER TABLE user_roles ADD CONSTRAINT ck_user_roles_userrole CHECK (role IN ({joined}))"
    )
    _swap_users_role_check(_ROLES)

    op.create_table(
        "company_audit_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("summary", sa.String(length=256), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name="fk_company_audit_log_company_id_companies",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name="fk_company_audit_log_actor_user_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_company_audit_log"),
    )
    op.create_index("ix_company_audit_log_company_id", "company_audit_log", ["company_id"])
    op.execute(
        "CREATE INDEX ix_company_audit_log_company_id_created_at "
        "ON company_audit_log (company_id, created_at DESC)"
    )

    # 2. One role row per user, from the column.
    op.execute(
        "INSERT INTO user_roles (id, user_id, role, granted_by_user_id, created_at) "
        "SELECT gen_random_uuid(), id, role, NULL, created_at FROM users"
    )

    # 3. The owner: the earliest-created active admin of each company.
    op.add_column(
        "companies", sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.create_foreign_key(
        "fk_companies_owner_user_id_users",
        "companies",
        "users",
        ["owner_user_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.execute(
        """
        UPDATE companies c SET owner_user_id = (
            SELECT u.id FROM users u
            JOIN user_roles r ON r.user_id = u.id AND r.role = 'admin'
            WHERE u.company_id = c.id AND u.is_active AND u.deleted_at IS NULL
            ORDER BY u.created_at, u.id
            LIMIT 1
        )
        """
    )
    op.execute(
        """
        INSERT INTO company_audit_log
            (id, company_id, actor_user_id, action, target_type, target_id, summary, detail,
             created_at)
        SELECT gen_random_uuid(), c.id, NULL, 'role_backfilled', 'company', c.id,
               CASE WHEN c.owner_user_id IS NULL
                    THEN 'Roles copied from users.role; no active admin, so no owner was set'
                    ELSE 'Roles copied from users.role; owner set to the earliest active admin'
               END,
               json_build_object(
                   'changes',
                   CASE WHEN c.owner_user_id IS NULL THEN '[]'::json
                        ELSE json_build_array(json_build_object(
                            'field', 'owner_user_id', 'from', NULL, 'to', c.owner_user_id::text))
                   END,
                   'users', (SELECT count(*) FROM users u WHERE u.company_id = c.id)
               ),
               now()
        FROM companies c
        """
    )
    unowned = (
        op.get_bind()
        .execute(
            sa.text("SELECT id, slug FROM companies WHERE owner_user_id IS NULL ORDER BY slug")
        )
        .all()
    )
    for company_id, slug in unowned:
        print(f"LP-MB-Admin-01: company {slug} ({company_id}) has no active admin; owner not set")

    # 4. The app stops writing the column.
    op.alter_column("users", "role", existing_type=sa.String(length=32), nullable=True)

    # 5. Readonly. DROP then CREATE: a view cannot lose a column with CREATE OR REPLACE.
    op.execute("DROP VIEW IF EXISTS readonly.users")
    op.execute(
        """
        CREATE VIEW readonly.users AS
        SELECT id, company_id, is_active, default_aggression_level, density,
               created_at, updated_at, deleted_at
        FROM public.users
        """
    )
    op.execute(
        """
        CREATE VIEW readonly.user_roles AS
        SELECT id, user_id, role, granted_by_user_id, created_at
        FROM public.user_roles
        """
    )
    op.execute(_GRANT)


def downgrade() -> None:
    # The previous definitions are inside this function on purpose: the readonly drift guard reads
    # everything above `def downgrade(` as the live view.
    op.execute("DROP VIEW IF EXISTS readonly.user_roles")
    op.execute("DROP VIEW IF EXISTS readonly.users")
    op.execute(
        """
        CREATE VIEW readonly.users AS
        SELECT id, company_id, role, is_active, default_aggression_level, density,
               created_at, updated_at, deleted_at
        FROM public.users
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mbai_readonly') THEN
                EXECUTE 'GRANT SELECT ON readonly.users TO mbai_readonly';
            END IF;
        END
        $$;
        """
    )
    op.execute(
        """
        UPDATE users u SET role = CASE
            WHEN EXISTS (SELECT 1 FROM user_roles r WHERE r.user_id = u.id AND r.role = 'admin')
            THEN 'admin' ELSE 'processor' END
        """
    )
    _swap_users_role_check(_OLD_ROLES)
    op.alter_column("users", "role", existing_type=sa.String(length=32), nullable=False)
    # Dropping the column drops its foreign key.
    op.drop_column("companies", "owner_user_id")
    op.drop_table("company_audit_log")
    op.drop_table("user_roles")
