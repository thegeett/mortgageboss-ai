"""Fact-tag vocabulary projection models (LP-311, ADR-250).

The tag VOCABULARY — the definition of every fact-tag the AI may produce (name,
entity, type/allowed-values, description, produced_by) — is authored by a human
with Priya in ``docs/snapshot-fact-tags.xlsx`` and committed as machine-source CSVs
(``fact_tags.csv``, ``rule_tags.csv``, ``tag_dependencies.csv``). Per §3D "Storage":
the vocabulary is SCHEMA and lives in git as files; only tag VALUES (per loan file,
per run) live in the DB, inside the frozen snapshot — those are NOT modelled here.

These three tables are a QUERYABLE PROJECTION of the vocabulary files, refreshed by
the LP-311 loader and never hand-edited. Global and un-scoped (the vocabulary is the
same for every company; no ``company_id``). No soft-delete — a tag removed from the
files is hard-removed by the loader.

* :class:`Tag`           — one fact-tag definition (the vocabulary row).
* :class:`RuleTag`       — a rule -> required-tag edge (from ``rule_tags.csv``).
* :class:`TagDependency` — a tag -> depends-on-tag DAG edge. Currently empty: the
  vocabulary xlsx has no ``depends_on`` column yet (LP-311 Phase 0). The table +
  the loader's cycle check exist so the DAG is a drop-in once authored.
"""

from typing import Any

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin
from app.models.types import SHORT_STRING


class Tag(Base, UUIDMixin, TimestampMixin):
    """One fact-tag definition, projected from ``fact_tags.csv``.

    ``tag_id`` (e.g. ``"txn.is_money_in"``) is the stable natural key that
    ``source_facts`` / rule requirements reference. ``tag_role`` and ``tag_version``
    are part of the §3D tag contract but are not yet columns in the vocabulary file,
    so ``tag_role`` is null and ``tag_version`` defaults to 1 until authored
    (LP-311 Phase 0). ``extras`` preserves the file's remaining vocabulary columns
    (decision, used_by_rules reverse-index, raw type string) verbatim.
    """

    __tablename__ = "tags"
    __table_args__ = (UniqueConstraint("tag_id", name="uq_tags_tag_id"),)

    # --- Identity (natural key) ---------------------------------------------- #
    tag_id: Mapped[str] = mapped_column(String(SHORT_STRING), nullable=False)
    # The entity the tag attaches to (transaction, statement, income, liability,
    # borrower, loan, property, doc, asset, calc-line).
    entity: Mapped[str] = mapped_column(String(SHORT_STRING), nullable=False)

    # --- Type / values ------------------------------------------------------- #
    # Parsed leading token: enum / number / date / string / int / object / list /…
    value_type: Mapped[str] = mapped_column(String(SHORT_STRING), nullable=False)
    # Enum members, e.g. ["in", "out", "unknown"]; null for non-enum types.
    # none_as_null so a non-enum tag is SQL NULL, not a JSONB 'null'.
    allowed_values: Mapped[list[str] | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)

    # --- Production metadata -------------------------------------------------- #
    # parsed | AI | derived | spec | "parsed/AI" — who produces the tag value.
    produced_by: Mapped[str] = mapped_column(String(SHORT_STRING), nullable=False)
    # structural_fact | rule_judgment — null until the vocabulary declares it.
    tag_role: Mapped[str | None] = mapped_column(String(SHORT_STRING), nullable=True)
    # Additive-only vocabulary version; defaults to 1 (no per-tag version in file).
    tag_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # Remaining vocabulary columns kept verbatim for fidelity / cross-check.
    extras: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    def __repr__(self) -> str:
        return f"<Tag {self.tag_id} entity={self.entity} type={self.value_type}>"


class RuleTag(Base, UUIDMixin, TimestampMixin):
    """A rule -> required-tag edge (from ``rule_tags.csv``).

    To evaluate a rule, its required tags must exist and be non-unknown. Both ends
    are natural-key FKs so a dangling reference is impossible at rest; the loader
    also validates the reference up front and fails loud with a clear message
    (the FK is the backstop, not the primary error surface).
    """

    __tablename__ = "rule_tags"
    __table_args__ = (UniqueConstraint("rule_id", "tag_id", name="uq_rule_tags_rule_id_tag_id"),)

    rule_id: Mapped[str] = mapped_column(
        ForeignKey("rules.rule_id", ondelete="CASCADE"), index=True, nullable=False
    )
    tag_id: Mapped[str] = mapped_column(
        ForeignKey("tags.tag_id", ondelete="CASCADE"), index=True, nullable=False
    )

    def __repr__(self) -> str:
        return f"<RuleTag {self.rule_id} -> {self.tag_id}>"


class TagDependency(Base, UUIDMixin, TimestampMixin):
    """A tag -> depends-on-tag DAG edge (from ``tag_dependencies.csv``).

    A tag is never produced before its inputs exist, and confidence propagates along
    the DAG. Both ends are natural-key FKs to :class:`Tag`; the loader rejects a
    cycle (topological check) and a dangling edge before it writes. Empty today —
    the vocabulary has no ``depends_on`` column yet (LP-311 Phase 0).
    """

    __tablename__ = "tag_dependencies"
    __table_args__ = (
        UniqueConstraint(
            "tag_id", "depends_on_tag_id", name="uq_tag_dependencies_tag_id_depends_on_tag_id"
        ),
    )

    tag_id: Mapped[str] = mapped_column(
        ForeignKey("tags.tag_id", ondelete="CASCADE"), index=True, nullable=False
    )
    depends_on_tag_id: Mapped[str] = mapped_column(
        ForeignKey("tags.tag_id", ondelete="CASCADE"), index=True, nullable=False
    )

    def __repr__(self) -> str:
        return f"<TagDependency {self.tag_id} depends_on {self.depends_on_tag_id}>"
