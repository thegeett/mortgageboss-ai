"""Rule registry loader (LP-118) — READ-ONLY access to the verification_rules table.

The runtime read-side of the hybrid rule storage. The engine (LP-121, later) will call
:func:`load_enabled_rules` once per run to pull the enabled rule definitions into memory;
findings / audit references use :func:`get_rule` to resolve a single ``rule_id``.

THIS MODULE ONLY READS. It does not evaluate, filter, or run any rule — the applicability
filter (LP-119), the evaluators (LP-120), and the runner wiring (LP-121) are later tickets.
A :class:`RuleDefinition` is an inert data snapshot of a row; loading one runs nothing.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import Connection, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.verification_rule import RuleChangeAudit, VerificationRule

# The version-controlled seed (authoring source of truth). backend/app/services/… →
# repo root is parents[3].
DEFAULT_SEED_PATH = Path(__file__).resolve().parents[3] / "docs" / "rules" / "rule_seed.json"

# The seed columns copied verbatim onto a verification_rules row.
_SEED_COLUMNS = (
    "rule_id",
    "playbook_id",
    "name",
    "category",
    "layer",
    "evaluator",
    "applicability",
    "canonical_type",
    "message_template",
    "params",
    "severity",
    "confidence_mode",
    "enabled",
    "status",
    "scope",
    "validated",
)


def seed_verification_rules(
    bind: Connection,
    *,
    seed_path: Path = DEFAULT_SEED_PATH,
    change_source: str = "seed_migration",
) -> int:
    """Populate ``verification_rules`` from the seed, auditing each insert (LP-118).

    Synchronous + Core-based so the SAME code serves the Alembic migration
    (``op.get_bind()``) and the tests (a sync connection). Idempotent: rule_ids already
    present are skipped (so a re-run never duplicates). Each fresh insert writes a
    ``rule_change_audits`` row (``changed_field="__insert__"``, the row JSON in
    ``new_value``). Inserts only — it never runs a rule. Returns the number inserted.
    """
    seed = json.loads(seed_path.read_text(encoding="utf-8"))
    now = datetime.now(UTC)

    existing = set(bind.execute(select(VerificationRule.rule_id)).scalars().all())
    inserted = 0
    for row in seed:
        if row["rule_id"] in existing:
            continue
        bind.execute(
            insert(VerificationRule).values(
                **{col: row.get(col) for col in _SEED_COLUMNS}, created_at=now, updated_at=now
            )
        )
        bind.execute(
            insert(RuleChangeAudit).values(
                id=uuid.uuid4(),
                rule_id=row["rule_id"],
                changed_field="__insert__",
                old_value=None,
                new_value=json.dumps(row, ensure_ascii=False, sort_keys=True),
                change_source=change_source,
                changed_by=None,
                changed_at=now,
            )
        )
        inserted += 1
    return inserted


class RuleDefinition(BaseModel):
    """An inert snapshot of one ``verification_rules`` row (LP-118).

    The engine will later turn this into an evaluation; here it is pure data. The
    STRUCTURAL fields (``evaluator``, ``applicability``, ``canonical_type``,
    ``message_template``) may be null for a seeded-but-not-yet-built rule — it simply
    will not run until LP-120 fills them.
    """

    rule_id: str
    playbook_id: str | None
    name: str
    category: str | None
    layer: str | None
    evaluator: str | None
    applicability: dict[str, Any] | None
    canonical_type: str | None
    message_template: str | None
    params: dict[str, Any]
    severity: str | None
    confidence_mode: str | None
    enabled: bool
    status: str | None
    scope: str | None
    validated: bool

    @classmethod
    def from_model(cls, row: VerificationRule) -> RuleDefinition:
        return cls(
            rule_id=row.rule_id,
            playbook_id=row.playbook_id,
            name=row.name,
            category=row.category,
            layer=row.layer,
            evaluator=row.evaluator,
            applicability=row.applicability,
            canonical_type=row.canonical_type,
            message_template=row.message_template,
            params=row.params or {},
            severity=row.severity,
            confidence_mode=row.confidence_mode,
            enabled=row.enabled,
            status=row.status,
            scope=row.scope,
            validated=row.validated,
        )


async def load_enabled_rules(db: AsyncSession) -> list[RuleDefinition]:
    """Load the ENABLED rule definitions (LP-118), ordered by ``rule_id`` for determinism.

    Read-only. The engine (LP-121) will call this once per run; here it just returns the
    inert snapshots. Disabled rows (not-yet-built playbook rows) are excluded.
    """
    stmt = (
        select(VerificationRule)
        .where(VerificationRule.enabled.is_(True))
        .order_by(VerificationRule.rule_id)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [RuleDefinition.from_model(row) for row in rows]


async def get_rule(db: AsyncSession, rule_id: str) -> RuleDefinition | None:
    """Fetch one rule by its stable ``rule_id`` (for findings / audit references). Read-only."""
    row = await db.get(VerificationRule, rule_id)
    return RuleDefinition.from_model(row) if row is not None else None


async def rule_change_history(db: AsyncSession, rule_id: str) -> list[dict[str, Any]]:
    """The change-audit trail for one rule (compliance history), newest first. Read-only."""
    from app.models.verification_rule import RuleChangeAudit

    stmt = (
        select(RuleChangeAudit)
        .where(RuleChangeAudit.rule_id == rule_id)
        .order_by(RuleChangeAudit.changed_at.desc())
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": str(row.id) if isinstance(row.id, UUID) else row.id,
            "changed_field": row.changed_field,
            "old_value": row.old_value,
            "new_value": row.new_value,
            "change_source": row.change_source,
            "changed_by": str(row.changed_by) if row.changed_by else None,
            "changed_at": row.changed_at,
        }
        for row in rows
    ]
