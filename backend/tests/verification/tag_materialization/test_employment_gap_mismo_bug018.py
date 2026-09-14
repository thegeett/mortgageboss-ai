"""bug-018 — IN-4 asked for employment dates the application already carried.

On LF-XMB2 IN-4 abstained with "fewer than two dated employment records, so employment continuity cannot
be verified" and told the processor to upload employment documentation. The 1003 on that file states PNC
ending 2026-03-03 and First National Bank starting 2026-03-09 for the same borrower: two dated positions
and a six-day gap.

`income.employment_start` / `_end` are read from VOE fields and nothing else, so a file with no VOE has
no dated records whatever the application says. The 1003's employment records have been in the snapshot
since LP-624 and nothing read them.

What must hold after the merge, and is pinned here: records still never pair across borrowers; a gap
measured from stated dates names no document, because there is no document behind it; and the two
different absences ("no dated records" vs "records that never pair") no longer share one sentence.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.verification.snapshot.fields import Field, FieldSource
from app.verification.snapshot.model import (
    BorrowerRef,
    DocumentEntry,
    DocumentsSection,
    MismoSection,
    Snapshot,
    TagsSection,
)
from app.verification.snapshot.pii import PiiField
from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage
from app.verification.tag_materialization.derived import _income_max_employment_gap

_B1 = UUID("00000000-0000-0000-0000-0000000b0181")
_B2 = UUID("00000000-0000-0000-0000-0000000b0182")


def _f(value: str) -> Field:
    return Field.present(value, source=FieldSource.EXTRACTED)


def _tag(value: str) -> Tag:
    return Tag(
        value=value,
        confidence=None,
        reasoning="fixture",
        source_facts=("raw",),
        produced_by=TagProducedBy.PARSED,
        tag_role=TagRole.STRUCTURAL_FACT,
        stage=TagStage.A,
    )


def _voe(cid: str, borrower: UUID, *, start: str | None = None, end: str | None = None) -> tuple:
    """A VOE attributed to one borrower, plus the employment tags read off it."""
    entry = DocumentEntry(
        content_id=cid,
        document_type="voe",
        belongs_to=(BorrowerRef(borrower_id=borrower, name="fixture"),),
    )
    tags: dict[str, Tag] = {}
    if start is not None:
        tags["income.employment_start"] = _tag(start)
    if end is not None:
        tags["income.employment_end"] = _tag(end)
    return entry, {cid: tags}


def _snap(
    *,
    mismo: dict[str, Field | PiiField] | None = None,
    docs: list[DocumentEntry] | None = None,
    tags: dict[str, dict[str, Tag]] | None = None,
) -> Snapshot:
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 9, 11, tzinfo=UTC),
        documents=DocumentsSection.present(list(docs or [])),
        mismo=MismoSection.present(mismo or {}),
        tags=TagsSection.present(tags or {}),
    )


def _stated(borrower_index: int, borrower: UUID, **employers: str) -> dict[str, Field | PiiField]:
    """The application's employment facts for one borrower: employer_N_start / employer_N_end."""
    facts: dict[str, Field | PiiField] = {
        f"borrower.{borrower_index}.borrower_id": _f(str(borrower))
    }
    for name, value in employers.items():
        row, field = name.split("_", 1)  # "1_end" -> row 1, field "end"
        facts[f"borrower.{borrower_index}.employer.{row}.{field}_date"] = _f(value)
    return facts


# --------------------------------------------------------------------------- #
# The application's own records now count
# --------------------------------------------------------------------------- #
def test_the_applications_dated_positions_produce_the_gap() -> None:
    """THE LF-XMB2 SHAPE — PNC ends 2026-03-03, FNB starts 2026-03-09, and no VOE anywhere."""
    produced = _income_max_employment_gap(
        _snap(mismo=_stated(1, _B1, **{"1_end": "2026-03-03", "2_start": "2026-03-09"})),
        "loan",
        None,
    )

    assert produced[0] == "6"


def test_a_gap_from_stated_dates_alone_names_no_document() -> None:
    """There is no document behind a stated date. Naming one would send a processor to a file that does
    not evidence the gap — the inverse of bug-017's complaint, and just as wrong."""
    produced = _income_max_employment_gap(
        _snap(mismo=_stated(1, _B1, **{"1_end": "2026-03-03", "2_start": "2026-03-09"})),
        "loan",
        None,
    )

    assert len(produced) == 2, "a stated-only gap has no document to name"


def test_a_stated_record_merges_with_the_same_borrowers_document() -> None:
    """The merge that makes this worth doing: a VOE says the job ended, the application says the next
    one began. Neither source alone has a pair. The document that evidences its half is named; the
    stated start contributes the date and no link."""
    entry, tags = _voe("voe_end", _B1, end="2026-01-31")
    produced = _income_max_employment_gap(
        _snap(
            mismo=_stated(1, _B1, **{"2_start": "2026-03-09"}),
            docs=[entry],
            tags=tags,
        ),
        "loan",
        None,
    )

    assert produced[0] == "37"  # 2026-01-31 → 2026-03-09
    assert produced[2] == ("voe_end",)


def test_a_document_backed_gap_still_names_both_of_its_documents() -> None:
    """LP-647 §1's behaviour is untouched where both sides are documents."""
    ended, ended_tags = _voe("voe_end", _B1, end="2026-01-31")
    started, started_tags = _voe("voe_start", _B1, start="2026-03-09")
    produced = _income_max_employment_gap(
        _snap(docs=[ended, started], tags={**ended_tags, **started_tags}),
        "loan",
        None,
    )

    assert produced[0] == "37"
    assert produced[2] == ("voe_end", "voe_start")


# --------------------------------------------------------------------------- #
# What must NOT change
# --------------------------------------------------------------------------- #
def test_a_child_support_start_date_is_not_an_employment_start() -> None:
    """bug-018 review — THE DATE THAT IS NOT A JOB START, MASKING THE GAP IN THE RULE'S OWN SUBJECT.

    `income.employment_start` is declared over the field name `start_date` with no document_type filter,
    and `alimony_income` / `child_support_income` both declare a field of exactly that name — so a
    support order produces an "employment start" carrying the date the SUPPORT began. Each end pairs
    with the EARLIEST start after it, so that date falling inside a real gap shrinks it: 121 days of
    unemployment read as 10, and IN-4 satisfies instead of firing.

    Pre-existing mis-scoping, made reachable by this ticket — before it, a file with no VOE had no pair
    at all and abstained; now the application supplies the other half.
    """
    order = DocumentEntry(
        content_id="cs1",
        document_type="child_support_income",
        belongs_to=(BorrowerRef(borrower_id=_B1, name="fixture"),),
    )
    ended, ended_tags = _voe("voe_end", _B1, end="2026-01-31")

    produced = _income_max_employment_gap(
        _snap(
            mismo=_stated(1, _B1, **{"2_start": "2026-06-01"}),
            docs=[ended, order],
            tags={**ended_tags, "cs1": {"income.employment_start": _tag("2026-02-10")}},
        ),
        "loan",
        None,
    )

    assert produced[0] == "121", (
        "the gap runs from the VOE's end to the job that actually started (2026-01-31 → 2026-06-01); "
        "the child-support start date must not stand in as a job start"
    )


def test_two_borrowers_stated_records_never_pair_with_each_other() -> None:
    """The rule this recipe has always had: one borrower's job-end must not pair with ANOTHER
    borrower's job-start. Merging a second source must not become a way around it."""
    facts: dict[str, Field | PiiField] = {
        **_stated(1, _B1, **{"1_end": "2026-01-31"}),
        **_stated(2, _B2, **{"1_start": "2026-06-01"}),
    }
    produced = _income_max_employment_gap(_snap(mismo=facts), "loan", None)

    assert produced[0] == "unknown"
    assert "starts after another one ends" in produced[1]


def test_a_stated_record_with_no_borrower_link_is_skipped() -> None:
    """Without `borrower.{n}.borrower_id` the record cannot be grouped with that borrower's documents,
    and grouping it with the unattributed ones could manufacture a gap between two people."""
    facts: dict[str, Field | PiiField] = {
        "borrower.1.employer.1.end_date": _f("2026-01-31"),
        "borrower.1.employer.2.start_date": _f("2026-03-09"),
    }
    produced = _income_max_employment_gap(_snap(mismo=facts), "loan", None)

    assert produced[0] == "unknown"
    assert "fewer than two" in produced[1]


# --------------------------------------------------------------------------- #
# The two absences no longer share one sentence
# --------------------------------------------------------------------------- #
def test_no_dated_records_says_so() -> None:
    produced = _income_max_employment_gap(
        _snap(mismo=_stated(1, _B1, **{"1_start": "2021-01-25"})), "loan", None
    )

    assert produced[0] == "unknown"
    assert "fewer than two dated employment records" in produced[1]


def test_records_that_never_pair_say_something_different() -> None:
    """A borrower with two dated positions whose dates never cross is NOT missing documentation, and
    telling them to upload employment dates they have already provided is what this sentence fixes."""
    produced = _income_max_employment_gap(
        _snap(mismo=_stated(1, _B1, **{"1_start": "2021-01-25", "2_start": "2024-04-01"})),
        "loan",
        None,
    )

    assert produced[0] == "unknown"
    assert "starts after another one ends" in produced[1]
    assert "fewer than two" not in produced[1]
