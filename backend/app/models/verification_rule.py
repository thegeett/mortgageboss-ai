"""Verification rule registry models (LP-118) — the HYBRID rule storage foundation.

Phase 3.5 turns verification rules from hand-coded classes into DATA the engine
reads per run, so the rule set scales toward the ~130-rule playbook without a code
change per rule. This module is the STORAGE FOUNDATION ONLY (LP-118): the tables +
the fields. Nothing here executes a rule — the applicability filter (LP-119),
evaluators (LP-120), the runner wiring (LP-121), and the params admin UI (LP-122)
are later tickets. The live verification path is unchanged by this module.

THE HYBRID (mirrors the lender-overlay pattern: config defaults + DB overrides +
audit). Two kinds of field live on a rule row, and the split is deliberate:

  * **STRUCTURAL** (``evaluator``, ``applicability``, ``canonical_type``,
    ``message_template``) — the rule's LOGIC. Compliance wants logic changes in
    git, so these change via the version-controlled **seed** + a migration, never
    a live edit.
  * **TUNABLE** (``params``, ``severity``, ``enabled``, ``confidence_mode``) — the
    dials Priya tunes. LP-122 will edit these live (no deploy), and every such edit
    is recorded in :class:`RuleChangeAudit`.

``rule_id`` is the stable external reference (findings / monitoring / activity_log
point at it); ``playbook_id`` is the traceability link back to the playbook
(``docs/rules/verification_rule_playbook.xlsx`` / ``rule_seed``). ``validated``
defaults **false** — the Priya-validation gate: an unvalidated threshold must not go
live at full confidence.

The **seed** (``docs/rules/rule_seed.json``) is the authoring source of truth; this
table is the runtime read-source, populated FROM the seed by the LP-118 migration
(each insert recorded in ``rule_change_audits`` with ``change_source="seed_migration"``).
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin, utcnow
from app.models.types import MEDIUM_STRING, SHORT_STRING


class VerificationRule(Base, TimestampMixin):
    """One verification rule as DATA (LP-118) — the row the engine will iterate later.

    Keyed by the stable ``rule_id`` (e.g. ``"xsrc.income.employer_name_consistency"``),
    the same string findings/monitoring/activity_log already reference. A seeded row
    may carry a null ``evaluator`` / ``applicability`` for now — it simply will not run
    until LP-120 fills those. Nothing in this ticket executes it.
    """

    __tablename__ = "verification_rules"

    # --- Identity (the stable external reference; do NOT rename live rule_ids) --- #
    rule_id: Mapped[str] = mapped_column(Text, primary_key=True)
    # Traceability to the playbook (AS-1, CR-4, IN-5, …). Nullable — many live/code
    # rules have no confident playbook mapping (LP-117.5); a wrong mapping is worse
    # than a null one.
    playbook_id: Mapped[str | None] = mapped_column(String(SHORT_STRING), nullable=True, index=True)

    # --- Descriptive ---------------------------------------------------------- #
    name: Mapped[str] = mapped_column(String(MEDIUM_STRING), nullable=False)
    # The playbook category string ("Application/Identity") or the FindingCategory
    # value for code-only rules — free string (data, not an enum) by design.
    category: Mapped[str | None] = mapped_column(String(SHORT_STRING), nullable=True)
    # Authoring metadata from the playbook (DET / DET-FUZZY / DET+AI / AI / CALC / …).
    # Informs the seeded ``confidence_mode``; kept for traceability.
    layer: Mapped[str | None] = mapped_column(String(SHORT_STRING), nullable=True)

    # --- STRUCTURAL (change via seed + migration; compliance wants logic in git) - #
    # The code evaluator this rule uses — a NAME, not executed here (LP-120 fills +
    # LP-121 runs). Null until the rule is built.
    evaluator: Mapped[str | None] = mapped_column(String(SHORT_STRING), nullable=True)
    # {purpose, program, occupancy, property_type, requires_docs, requires_data} —
    # read by LP-119's applicability filter (not built here). Null until specified.
    applicability: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    # The canonical finding type the rule OWNS (the AI-dedup key, LP-86). Null until built.
    canonical_type: Mapped[str | None] = mapped_column(String(SHORT_STRING), nullable=True)
    # Templated finding wording (fixed per run). Null until built.
    message_template: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- TUNABLE (editable live later via LP-122 → audited) -------------------- #
    # Thresholds / windows / tolerances as editable data ({"variance_pct": 5}).
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    # "RED" | "YELLOW" — stored as a string (data). Null until built.
    severity: Mapped[str | None] = mapped_column(String(SHORT_STRING), nullable=True)
    # "certain" (pure-DET, 1.0) | "computed" (DET-FUZZY, match-quality). LP-120
    # finalizes this + replaces the global DETERMINISTIC_CONFIDENCE constant.
    confidence_mode: Mapped[str | None] = mapped_column(String(SHORT_STRING), nullable=True)
    # The on/off switch (the engine will run only enabled rules). Default off.
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # --- Routing / scope metadata (the playbook's real vocab, kept verbatim) ---- #
    # NOW / EXTRACT / BLOCKED / EXISTS? / SCOPE? / IN PROGRESS / …
    status: Mapped[str | None] = mapped_column(String(SHORT_STRING), nullable=True)
    # IN / ? / OUT (the scope tier) — data, not an enum.
    scope: Mapped[str | None] = mapped_column(String(SHORT_STRING), nullable=True)

    # --- The Priya-validation gate (defaults FALSE) --------------------------- #
    # An unvalidated threshold must not go live at full confidence. Only Priya-
    # confirmed rules (e.g. large-deposit >50%, income-variance >5%) seed true.
    validated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # The change history (compliance trail; LP-122 live edits append here too).
    change_audits: Mapped[list["RuleChangeAudit"]] = relationship(
        back_populates="rule", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return (
            f"<VerificationRule {self.rule_id} playbook={self.playbook_id} enabled={self.enabled}>"
        )


class RuleChangeAudit(Base, UUIDMixin):
    """One recorded change to a verification_rule row (LP-118) — the compliance history.

    Every change to a rule row lands here: the LP-118 seed inserts
    (``change_source="seed_migration"``), and later LP-122's live param/severity/enabled
    edits (``change_source="admin_ui"``) and system changes (``"system"``). A full-row
    insert is recorded with ``changed_field="__insert__"`` and the row JSON in ``new_value``.
    """

    __tablename__ = "rule_change_audits"

    # The rule this change is about. RESTRICT (no ondelete) so a rule with history
    # cannot be hard-deleted out from under its audit trail — rules retire via
    # ``enabled=false``, never deletion.
    rule_id: Mapped[str] = mapped_column(
        ForeignKey("verification_rules.rule_id"), index=True, nullable=False
    )
    # The field changed, or "__insert__" for a full-row seed insert.
    changed_field: Mapped[str] = mapped_column(String(SHORT_STRING), nullable=False)
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    # "seed_migration" | "admin_ui" | "system".
    change_source: Mapped[str] = mapped_column(String(SHORT_STRING), nullable=False)
    # Who made the change (null for seed/system). SET NULL keeps the row if the user
    # is removed.
    changed_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    rule: Mapped["VerificationRule"] = relationship(back_populates="change_audits")

    def __repr__(self) -> str:
        return (
            f"<RuleChangeAudit {self.rule_id}.{self.changed_field} "
            f"src={self.change_source} at={self.changed_at}>"
        )
