"""The admin lenders list, led by the overlay (LP-UI-025).

An overlay is the highest-leverage thing an admin touches — one change moves every
file at that lender — so the list answers "what is different here, and when did it
last change" before "who do I call".

Both numbers come off the `lender_overlays` blob already on the row, through the
same accessors the editor uses, so the list's count and the editor's list cannot
disagree about what an override is.
"""

from datetime import UTC, datetime
from uuid import uuid4

from app.models.lender import Lender
from app.services.overlay_admin import build_lender_summary


def _lender(overlays: object) -> Lender:
    return Lender(
        id=uuid4(),
        company_id=uuid4(),
        name="UWM",
        slug="uwm",
        supported_programs=["conventional"],
        lender_overlays=overlays,
    )


class TestTheListRow:
    def test_counts_the_stored_overrides(self) -> None:
        lender = _lender({"overrides": [{"rule_id": "DT-1"}, {"rule_id": "LT-2"}], "audit": []})
        assert build_lender_summary(lender).override_count == 2

    def test_zero_overrides_is_a_real_answer(self) -> None:
        # Not a gap: it means the agency guideline applies unchanged here. The
        # count has to be 0 rather than absent so the UI can say that in words.
        summary = build_lender_summary(_lender({"overrides": [], "audit": []}))
        assert summary.override_count == 0
        assert summary.last_changed_at is None

    def test_never_edited_is_not_a_date(self) -> None:
        # `None` and "edited a long time ago" are different facts. A lender whose
        # overlay has never been touched must not render a timestamp.
        assert build_lender_summary(_lender({})).last_changed_at is None

    def test_reports_the_most_recent_change(self) -> None:
        lender = _lender(
            {
                "overrides": [{"rule_id": "DT-1"}],
                "audit": [
                    {"at": "2026-01-05T00:00:00+00:00", "reason": "a"},
                    {"at": "2026-03-09T00:00:00+00:00", "reason": "b"},
                ],
            }
        )
        assert build_lender_summary(lender).last_changed_at == datetime(2026, 3, 9, tzinfo=UTC)

    def test_does_not_assume_the_audit_is_ordered(self) -> None:
        # `max`, not `[-1]`. Overlays were hand-edited JSON before LP-87, so a
        # blob carries no ordering guarantee and "most recent" must not need one.
        lender = _lender(
            {
                "overrides": [],
                "audit": [
                    {"at": "2026-03-09T00:00:00+00:00", "reason": "b"},
                    {"at": "2026-01-05T00:00:00+00:00", "reason": "a"},
                ],
            }
        )
        assert build_lender_summary(lender).last_changed_at == datetime(2026, 3, 9, tzinfo=UTC)

    def test_an_unparseable_timestamp_costs_the_line_not_the_list(self) -> None:
        # Hand-edited JSON is why this is defensive. A malformed `at` must not
        # take the whole admin list down with it.
        lender = _lender({"overrides": [{"rule_id": "DT-1"}], "audit": [{"at": "not a date"}]})
        summary = build_lender_summary(lender)
        assert summary.last_changed_at is None
        assert summary.override_count == 1

    def test_a_malformed_blob_still_yields_a_row(self) -> None:
        # `lender_overlays` is JSON and has been hand-edited. A list that 500s
        # because one lender's blob is a string helps nobody.
        assert build_lender_summary(_lender("nonsense")).override_count == 0

    def test_an_override_without_a_rule_id_is_not_counted(self) -> None:
        # The editor's accessor drops these, so the count must too — otherwise
        # the list says 2 and the editor shows 1.
        lender = _lender({"overrides": [{"rule_id": "DT-1"}, {"note": "orphan"}], "audit": []})
        assert build_lender_summary(lender).override_count == 1
