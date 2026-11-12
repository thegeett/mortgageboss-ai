"""Reading `companies.settings` never fails a request (LP-MB-Admin-02 review, finding 3).

Settings are read on every request to resolve permissions, so a value that does not parse would lock
the whole company out. Each bad setting takes its default instead; good ones and unknown keys survive.
"""

from typing import Any
from uuid import uuid4

import pytest
from app.core.company_settings import CompanySettings, parse_stored_settings


@pytest.mark.parametrize(
    "stored",
    [
        {"processors_can_create_loans": None},
        {"processors_can_create_loans": "banana"},
        {"processors_can_create_loans": [1]},
    ],
)
def test_a_bad_setting_takes_its_default_and_the_rest_survive(stored: dict[str, Any]) -> None:
    raw = {**stored, "processors_can_invite_borrowers": False, "some_future_flag": "kept"}

    parsed = parse_stored_settings(raw, company_id=uuid4())

    assert parsed.processors_can_create_loans is True  # the default
    assert parsed.processors_can_invite_borrowers is False  # a good value is kept
    assert parsed.model_dump()["some_future_flag"] == "kept"


@pytest.mark.parametrize("raw", [None, [], "x", 3])
def test_a_column_that_is_not_an_object_reads_as_the_defaults(raw: Any) -> None:
    assert parse_stored_settings(raw, company_id=uuid4()) == CompanySettings()


def test_a_good_column_parses_unchanged() -> None:
    raw = {"restrict_loans_to_team": True}
    assert parse_stored_settings(raw, company_id=uuid4()) == CompanySettings(
        restrict_loans_to_team=True
    )
