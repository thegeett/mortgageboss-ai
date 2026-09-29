"""The condition library v1 (LP-918): the shipped data loads, and every refusal refuses.

Each refusal is tested against a MINIMAL valid library with one field broken, and that minimal library
is itself asserted to load (the positive control): a refusal test whose baseline already fails would
pass for the wrong reason.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest
from app.conditions.library import LibraryError, load_library
from app.conditions.library.loader import AGENCY_CITATIONS, parse_library
from app.models.condition_vocabulary import PlanOption

_DOCS = frozenset({"bank_statement", "earnest_money_receipt"})


def _minimal() -> dict[str, Any]:
    return {
        "version": 1,
        "types": [
            {
                "id": "AS-04",
                "name": "Earnest money",
                "category": "assets",
                "rule": {"kind": "agency", "citation": "Fannie Mae B3-4.3-09"},
                "playbook": "Three things.",
                "items": [
                    {
                        "key": "source",
                        "name": "Source",
                        "acceptable": "Statement",
                        "performer": "borrower",
                        "option": "ask_borrower",
                        "documents": ["bank_statement"],
                        "checks": ["all_pages"],
                    }
                ],
            },
            {
                "id": "PA-04",
                "name": "Desk review",
                "category": "property",
                "rule": {"kind": "lender_requirement"},
                "playbook": "Watch.",
                "items": [],
                "default_option": "lender_doing_it",
            },
        ],
    }


def test_the_minimal_library_loads() -> None:
    library = parse_library(_minimal(), documents_known=_DOCS)
    assert set(library.types) == {"AS-04", "PA-04"}
    assert library.types["PA-04"].options == (PlanOption.LENDER_DOING_IT,)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda d: d["types"][0].update(id="IN-7"), "must look like AS-04"),
        (lambda d: d["types"].append(copy.deepcopy(d["types"][0])), "appears twice"),
        (lambda d: d["types"][0]["items"][0].update(performer="uncle"), "performer"),
        (lambda d: d["types"][0]["items"][0].update(option="call_them"), "option"),
        (lambda d: d["types"][0]["items"][0].update(checks=["vibes"]), "check"),
        (lambda d: d["types"][0]["items"][0].update(documents=["napkin"]), "not document types"),
        (
            lambda d: d["types"][0]["rule"].update(citation="Fannie Mae B3-9.9-99"),
            "not a citation the Stage 3 plan makes",
        ),
        (lambda d: d["types"][1].pop("default_option"), "needs default_option"),
        (lambda d: d["types"][1].update(default_option="ask_borrower"), "needs default_option"),
        (lambda d: d["types"][0].update(default_option="lender_doing_it"), "takes its options"),
        (lambda d: d["types"][0].update(waits_on_type="ZZ-99"), "waits_on_type"),
        (lambda d: d["types"][0].update(playbook=" "), "playbook"),
        (
            lambda d: d["types"][0]["items"][0].update(name_with_amount="Source of the money"),
            "must be text containing",
        ),
        # LP-921: an ask is not her task, and her task must say what she does.
        (lambda d: d["types"][0]["items"][0].update(task="upload it"), "only an i_will_do_it"),
        (
            lambda d: d["types"][0]["items"][0].update(option="i_will_do_it"),
            "task must be non-empty",
        ),
        # Stage 3A acceptance: everyone who acts is listed, and it includes the item's performer.
        (lambda d: d["types"][0]["items"][0].update(performers=["lo"]), "must include"),
        (
            lambda d: d["types"][0]["items"][0].update(performers=["borrower", "uncle"]),
            "performers",
        ),
    ],
)
def test_a_malformed_library_is_refused(mutate: Any, message: str) -> None:
    data = _minimal()
    mutate(data)
    with pytest.raises(LibraryError, match=message):
        parse_library(data, documents_known=_DOCS)


def test_the_shipped_library_loads_and_is_about_forty_types() -> None:
    library = load_library()
    # Plan §5 LP-918: "about 40 condition types". Every mapped code needs one, which is what drives it
    # past 40; the bound keeps the library from growing unreviewed.
    assert 40 <= len(library.types) <= 60


def test_every_agency_citation_is_one_the_plan_makes() -> None:
    """The reviewer checks these against the plan's sources; the loader already refuses others."""
    cited = {t.rule.citation for t in load_library().types.values() if t.rule.kind == "agency"}
    assert cited <= AGENCY_CITATIONS
    # And the four the plan leans on hardest are actually used where they belong.
    by_id = load_library().types
    assert by_id["AS-04"].rule.citation == "Fannie Mae B3-4.3-09"
    assert by_id["AS-05"].rule.citation == "Fannie Mae B3-4.2-02"
    assert by_id["IE-03"].rule.citation == "Fannie Mae B3-3.1-04"


def test_round_one_types_propose_the_plan_in_section_6() -> None:
    """The library alone reproduces plan §6's options for the types round 1 maps to (the AI only fills
    specifics). 1228's "Lender is doing it" and 6178's push-back come from the lender setting and the
    reading (LP-919, LP-920), not the library, so they are not asserted here."""
    by_id = load_library().types
    ask_b, ask_3p, mine = (
        PlanOption.ASK_BORROWER,
        PlanOption.ASK_THIRD_PARTY,
        PlanOption.I_WILL_DO_IT,
    )
    assert by_id["AS-10"].options == (ask_b,)  # 7086
    assert by_id["AS-01"].options == (ask_b,)  # 6132
    assert by_id["AS-04"].options == (ask_b, ask_3p)  # 6637: borrower email + title email
    assert [i.performer.value for i in by_id["AS-04"].items] == ["borrower", "title", "borrower"]
    assert by_id["DI-01"].options == (ask_3p,)  # 0132: LO + attorney
    assert by_id["TI-03"].options == (ask_3p,)  # 1947
    assert by_id["TI-04"].options == (ask_3p,)  # 6378
    assert by_id["IV-02"].options == (mine,)  # 1582
    assert by_id["IV-03"].options == (mine,) and by_id["IV-03"].waits_on_type == "PA-03"  # 0007


async def test_seeded_codes_and_imported_conditions_carry_their_type(db_session: Any) -> None:
    """Through the database: the seed writes each code's type onto its row, and import copies it onto
    the condition (Stage 1's `_apply_code_defaults` path), so 6637 arrives as AS-04."""
    from app.models import Company
    from app.models.condition_round import ConditionRoundCompleteness
    from app.models.lender_condition_code import LenderConditionCode
    from app.scripts.seed_lender_codes import seed_lender_codes
    from app.services.condition_import import import_round
    from app.services.condition_rounds import create_round_from_paste
    from sqlalchemy import select
    from tests.conditions.fixture_helpers import sheet_text
    from tests.models.conftest_helpers import make_lender, make_loan_file

    company = Company(name="Library", slug="library-lp918")
    db_session.add(company)
    await db_session.flush()
    lender = await make_lender(db_session, company=company)
    lender.canonical_lender_key = "uwm"
    loan_file = await make_loan_file(db_session, company=company)
    loan_file.lender_id = lender.id
    await db_session.flush()
    await seed_lender_codes(db_session)

    rows = (
        (
            await db_session.execute(
                select(LenderConditionCode).where(LenderConditionCode.lender_id == lender.id)
            )
        )
        .scalars()
        .all()
    )
    assert rows and all(row.canonical_type_id for row in rows)

    round_ = await create_round_from_paste(
        db_session,
        loan_file=loan_file,
        text=sheet_text("uwm_round1_2026-08-28.txt"),
        completeness=ConditionRoundCompleteness.FULL,
    )
    await import_round(db_session, round_=round_)
    from app.models.condition import Condition

    types = {
        c.lender_code: c.canonical_type_id
        for c in (
            await db_session.execute(
                select(Condition).where(Condition.loan_file_id == loan_file.id)
            )
        ).scalars()
    }
    assert types["6637"] == "AS-04" and types["7086"] == "AS-10" and types["1228"] == "PA-03"
    assert all(types.values()), f"conditions imported without a type: {types}"
