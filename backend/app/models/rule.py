"""Rule projection model (LP-311, ADR-250) — rules-as-data, projected from files.

The verification rule set lives in version-controlled FILES: ``rule_kinds.csv``
(identity + kind + the Priya-validation gate flags — the gate of record) and
``specs/<rule_id>.yaml`` (the full ``RuleSpec`` behind ``load_rule_spec``). Those
files are the SOURCE OF TRUTH: regulatory thresholds need an audit trail and Priya
sign-off, and git history IS that audit trail (§3D "Storage").

This table is a QUERYABLE PROJECTION of those files, refreshed by the LP-311 loader
(``app.verification.rules.projection``). It is never hand-edited — the loader
reconciles it back to the files on every run, so a hand-mutated row is overwritten.
It replaces the abandoned ``verification_rules`` table (LP-118 / ADR-238, phase3_5_1),
whose evaluator-engine shape does not fit the fact-tag architecture; the LP-311
migration drops that orphaned table.

Reference data is GLOBAL and un-scoped: rules are the same for every company, so
there is deliberately no ``company_id`` (per-tenant overrides are a future ticket).
No soft-delete — a rule that vanishes from the files is hard-removed by the loader,
because the DB carries no truth the files do not.
"""

from typing import Any

from sqlalchemy import Boolean, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin
from app.models.types import LONG_STRING, MEDIUM_STRING, SHORT_STRING


class Rule(Base, UUIDMixin, TimestampMixin):
    """One verification rule as data — projected from rule_kinds.csv + its spec.

    ``rule_id`` (e.g. ``"AS-1"``) is the stable natural key the rest of the system
    references (findings, tags, monitoring). The identity/kind/gate columns mirror
    the ``rule_kinds.csv`` row verbatim (CSV stays the gate of record); ``spec``
    holds the full ``RuleSpec`` payload when a ``specs/<rule_id>.yaml`` exists (null
    otherwise — most rules have no spec file yet).
    """

    __tablename__ = "rules"
    __table_args__ = (UniqueConstraint("rule_id", name="uq_rules_rule_id"),)

    # --- Identity (natural key) ---------------------------------------------- #
    rule_id: Mapped[str] = mapped_column(String(SHORT_STRING), nullable=False)
    name: Mapped[str] = mapped_column(String(MEDIUM_STRING), nullable=False)
    category: Mapped[str | None] = mapped_column(String(SHORT_STRING), nullable=True)

    # --- Kind + routing (verbatim from rule_kinds.csv, the gate of record) ---- #
    kind: Mapped[str] = mapped_column(String(SHORT_STRING), nullable=False)
    evaluation_path: Mapped[str | None] = mapped_column(String(SHORT_STRING), nullable=True)
    numeric_check: Mapped[bool] = mapped_column(Boolean, nullable=False)
    # Structural-only; None for non-structural rules (the CSV cell is blank).
    exact_match: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    # --- The Priya-validation gate (files win; see LP-311 / ADR-250) ---------- #
    priya_validated: Mapped[bool] = mapped_column(Boolean, nullable=False)
    threshold_needs_signoff: Mapped[bool] = mapped_column(Boolean, nullable=False)
    rationale: Mapped[str | None] = mapped_column(String(LONG_STRING), nullable=True)

    # --- The full spec (from specs/<rule_id>.yaml), or null if none yet ------- #
    # none_as_null so a rule without a spec file is SQL NULL, not a JSONB 'null'.
    spec: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True), nullable=True)

    def __repr__(self) -> str:
        return f"<Rule {self.rule_id} kind={self.kind} priya_validated={self.priya_validated}>"
