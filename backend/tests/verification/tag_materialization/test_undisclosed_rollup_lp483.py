"""LP-483 / ADR-375 — the inverted matcher: the borrower rollup is DERIVED from the per-liability judgment.

``credit.undisclosed_tradeline`` was an AI tag judged at BORROWER scope. It is now a derived recipe
aggregating ``liab.in_application``, the atomic per-liability judgment — so CR-1 (which debt?) and CR-4
(any debt?) read one comparison and cannot disagree about the same file.

⚠️ THE SEAM THESE PIN. The aggregation is exactly where a false ALL-CLEAR could slip in: an empty list of
judgments must never read as "no undisclosed debt". Every no-evidence path must abstain to ``unknown``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.verification.snapshot.fields import Field, FieldSource
from app.verification.snapshot.model import (
    DocumentEntry,
    DocumentsSection,
    ListRow,
    MismoSection,
    Snapshot,
    TagsSection,
)
from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage
from app.verification.tag_materialization.declarations import load_declarations
from app.verification.tag_materialization.derived import (
    KNOWN_RECIPES,
    _credit_undisclosed_tradeline,
)

_UNKNOWN = "unknown"


def _tag(value: str) -> Tag:
    return Tag(
        value=value,
        confidence=0.9,
        reasoning="test",
        source_facts=("x",),
        produced_by=TagProducedBy.AI,
        tag_role=TagRole.STRUCTURAL_FACT,
        stage=TagStage.A,
    )


def _credit_report(rows: int = 2) -> DocumentEntry:
    return DocumentEntry(
        content_id="cr1",
        document_type="credit_report",
        belongs_to=None,
        fields={},
        lists={
            "tradelines": tuple(
                ListRow(
                    fields={"creditor_name": Field.present(f"C{i}", source=FieldSource.EXTRACTED)},
                    row_id=f"r{i}",
                )
                for i in range(rows)
            )
        },
    )


def _snapshot(
    documents: list[DocumentEntry],
    tags: dict[str, dict[str, Tag]] | None = None,
    *,
    tags_absent: bool = False,
) -> Snapshot:
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 8, 1, tzinfo=UTC),
        documents=DocumentsSection.present(documents),
        mismo=MismoSection.present({}),
        tags=TagsSection.missing() if tags_absent else TagsSection.present(tags or {}),
    )


def _rollup(snapshot: Snapshot) -> tuple[object, str]:
    return _credit_undisclosed_tradeline(snapshot, "borrower-1", None)


# --------------------------------------------------------------------------- #
# The declaration itself — the inversion
# --------------------------------------------------------------------------- #
def test_the_rollup_is_derived_and_the_atomic_judgment_is_the_ai_tag() -> None:
    decls = load_declarations()
    assert decls["credit.undisclosed_tradeline"].mode.value == "derived"
    assert decls["liab.in_application"].mode.value == "ai"
    assert decls["liab.in_application"].subject == "liability"
    assert "credit_undisclosed_tradeline" in KNOWN_RECIPES


# --------------------------------------------------------------------------- #
# ⚠️ Fail-closed: NEVER a false all-clear
# --------------------------------------------------------------------------- #
def test_no_credit_report_abstains_never_no() -> None:
    """'No undisclosed debt' on a file with no credit report is a FALSE ALL-CLEAR."""
    value, reason = _rollup(_snapshot([]))
    assert value == _UNKNOWN
    assert "no credit-report tradelines" in reason


def test_absent_tags_layer_abstains() -> None:
    value, _ = _rollup(_snapshot([_credit_report()], tags_absent=True))
    assert value == _UNKNOWN


def test_tradelines_with_no_judgment_abstain() -> None:
    """The matcher never ran (or produced nothing) — absent ≠ 'everything is disclosed'."""
    value, reason = _rollup(_snapshot([_credit_report()]))
    assert value == _UNKNOWN
    assert "none carries a usable in-application judgment" in reason


def test_every_judgment_unknown_abstains() -> None:
    tags = {
        "r0": {"liab.in_application": _tag(_UNKNOWN)},
        "r1": {"liab.in_application": _tag(_UNKNOWN)},
    }
    value, _ = _rollup(_snapshot([_credit_report()], tags))
    assert value == _UNKNOWN


# --------------------------------------------------------------------------- #
# The aggregation
# --------------------------------------------------------------------------- #
def test_all_disclosed_rolls_up_to_no() -> None:
    tags = {
        "r0": {"liab.in_application": _tag("yes")},
        "r1": {"liab.in_application": _tag("yes")},
    }
    value, reason = _rollup(_snapshot([_credit_report()], tags))
    assert value == "no"
    assert "all 2 judged" in reason


def test_one_undisclosed_rolls_up_to_yes() -> None:
    tags = {
        "r0": {"liab.in_application": _tag("yes")},
        "r1": {"liab.in_application": _tag("no")},
    }
    value, reason = _rollup(_snapshot([_credit_report()], tags))
    assert value == "yes"
    assert "1 of 2" in reason


def test_a_confident_no_survives_alongside_unknowns() -> None:
    """One undisclosed debt is the finding regardless of how many neighbours are unclear."""
    tags = {
        "r0": {"liab.in_application": _tag(_UNKNOWN)},
        "r1": {"liab.in_application": _tag("no")},
    }
    value, _ = _rollup(_snapshot([_credit_report()], tags))
    assert value == "yes"


def test_mismo_liabilities_are_not_counted_as_reported_tradelines() -> None:
    """The rollup asks about REPORTED debts; a stated liability is the comparison set, not a subject
    under test (ADR-374's union means both are subjects — only one side is aggregated here)."""
    snapshot = Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 8, 1, tzinfo=UTC),
        documents=DocumentsSection.present([]),
        mismo=MismoSection.present(
            {"liability.1.holder_name": Field.present("AMEX", source=FieldSource.PARSED)}
        ),
        tags=TagsSection.present({}),
    )
    value, reason = _rollup(snapshot)
    assert value == _UNKNOWN
    assert "no credit-report tradelines" in reason
