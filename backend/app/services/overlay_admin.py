"""Overlay admin service (LP-87) — view + edit a lender's overlay over LP-80's storage.

The DB-facing half of the overlay admin UI. It reads/writes the SAME ``lenders.lender_overlays``
JSON column from LP-80 (a UI over the existing storage, not a new mechanism), makes each
override's effect legible (the investor base threshold → the lender's effective threshold by
composing against the base rule), and records every edit's from→to values in the overlay's
own audit trail (reusing LP-80.5's :func:`field_changes` / :func:`audit_value`).

Tenant-scoped (a lender is fetched within the caller's company); the admin gate is enforced
at the API layer (:func:`require_role`). The persisted JSON shape is
``{"overrides": [{rule_id, value, reason}], "audit": [{at, actor_user_id, reason, changes}]}``.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.models.base import utcnow
from app.models.helpers import only_active, scope_to_company
from app.models.lender import Lender
from app.schemas.overlay_admin import (
    LenderOverlayView,
    OverlayAuditEntry,
    OverlayOverrideView,
    OverlayUpdateRequest,
)
from app.services.activity_log import audit_value, field_changes
from app.verification.rules.schema import VerificationRule


class UnknownOverlayRuleError(Exception):
    """An override targets a rule_id that is not a known base rule."""


def _base_rule_index() -> dict[str, VerificationRule]:
    """Every base rule by ``rule_id`` (sample + Conventional + FHA) — the override targets."""
    from app.verification.rules.conventional import CONVENTIONAL_RULES
    from app.verification.rules.fha import FHA_RULES
    from app.verification.rules.samples import SAMPLE_RULES

    return {r.rule_id: r for r in (*SAMPLE_RULES, *CONVENTIONAL_RULES, *FHA_RULES)}


async def get_lender(db: AsyncSession, *, company_id: UUID, lender_id: UUID) -> Lender | None:
    """Fetch one of the caller's company's lenders (tenant gate), or None."""
    stmt = only_active(
        scope_to_company(select(Lender).where(Lender.id == lender_id), Lender, company_id), Lender
    )
    return (await db.execute(stmt)).scalars().first()


def _stored_overrides(lender: Lender) -> list[dict[str, Any]]:
    raw = lender.lender_overlays or {}
    overrides = raw.get("overrides", []) if isinstance(raw, dict) else []
    return [o for o in overrides if isinstance(o, dict) and "rule_id" in o]


def _stored_audit(lender: Lender) -> list[dict[str, Any]]:
    raw = lender.lender_overlays or {}
    audit = raw.get("audit", []) if isinstance(raw, dict) else []
    return [a for a in audit if isinstance(a, dict)]


def build_overlay_view(lender: Lender) -> LenderOverlayView:
    """Compose the lender's stored overlay into the effect-legible view (base → effective)."""
    base = _base_rule_index()
    overrides: list[OverlayOverrideView] = []
    for stored in _stored_overrides(lender):
        rule = base.get(stored["rule_id"])
        try:
            effective = Decimal(str(stored.get("value")))
        except (ArithmeticError, ValueError, TypeError):
            continue
        overrides.append(
            OverlayOverrideView(
                rule_id=stored["rule_id"],
                rule_description=rule.description if rule is not None else "(unknown rule)",
                op=rule.condition.op.value if rule is not None else "<=",
                unit=rule.condition.unit if rule is not None else None,
                base_value=rule.condition.value if rule is not None else None,
                effective_value=effective,
                reason=stored.get("reason"),
            )
        )
    audit = [
        OverlayAuditEntry(
            at=str(a.get("at", "")),
            actor_user_id=a.get("actor_user_id"),
            reason=str(a.get("reason", "")),
            changes=list(a.get("changes", [])),
        )
        for a in _stored_audit(lender)
    ]
    audit.reverse()  # newest first
    return LenderOverlayView(
        id=str(lender.id),
        name=lender.name,
        slug=lender.slug,
        overrides=overrides,
        audit=audit,
    )


async def update_lender_overlay(
    db: AsyncSession,
    *,
    company_id: UUID,
    lender_id: UUID,
    request: OverlayUpdateRequest,
    actor_user_id: UUID,
) -> Lender | None:
    """Replace the lender's overlay override set, audited (from→to); persist to LP-80's JSON.

    Validates every ``rule_id`` against the base rules, computes the field-level changes
    (LP-80.5's value-recording posture), appends an audit entry to the overlay's own trail,
    and writes the ``lenders.lender_overlays`` JSON. Returns None if the lender isn't the
    caller's (tenant gate); raises :class:`UnknownOverlayRuleError` for an unknown rule_id.
    """
    lender = await get_lender(db, company_id=company_id, lender_id=lender_id)
    if lender is None:
        return None

    base = _base_rule_index()
    new_overrides: list[dict[str, Any]] = []
    for override in request.overrides:
        if override.rule_id not in base:
            raise UnknownOverlayRuleError(override.rule_id)
        new_overrides.append(
            {
                "rule_id": override.rule_id,
                "value": str(override.value),
                "reason": override.reason,
            }
        )

    before = {o["rule_id"]: o.get("value") for o in _stored_overrides(lender)}
    after = {o["rule_id"]: o["value"] for o in new_overrides}
    changes = field_changes(before, after)

    audit = _stored_audit(lender)
    audit.append(
        {
            "at": audit_value(utcnow()),
            "actor_user_id": str(actor_user_id),
            "reason": request.reason,
            "changes": changes,
        }
    )
    lender.lender_overlays = {"overrides": new_overrides, "audit": audit}
    flag_modified(lender, "lender_overlays")  # JSON column — mark dirty for the UPDATE
    await db.flush()
    return lender
