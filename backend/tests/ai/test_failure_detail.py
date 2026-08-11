"""``failure_detail`` (LP-473) — the self-locating reason for a FAILED extraction.

"Empty failure, no error type" cost a diagnosis cycle on 222 (the LP-464 lesson: a symptom with no
location is expensive). An exception/infra failure carries its own reason; an all-null FAILED had none.
``failure_detail`` names that honest-none case, identically for the persisted record and the bench.
"""

from app.ai.extraction.parsing import (
    FAILED_ALL_NULL_DETAIL,
    failure_detail,
)
from app.models.extraction import ExtractionStatus


def test_non_failed_has_no_detail() -> None:
    assert failure_detail(ExtractionStatus.SUCCEEDED, None) is None
    assert failure_detail(ExtractionStatus.SUCCEEDED, "ignored") is None
    assert failure_detail(ExtractionStatus.PARTIAL, "ignored") is None


def test_failed_with_reason_keeps_it() -> None:
    # An infra/parse failure sets its own reason via .failed(...) — keep it verbatim.
    assert failure_detail(ExtractionStatus.FAILED, "AI call failed") == "AI call failed"
    assert failure_detail(ExtractionStatus.FAILED, "could not parse extraction") == (
        "could not parse extraction"
    )


def test_failed_all_null_gets_the_synthetic_marker() -> None:
    # The honest-none case: FAILED (derive_status: nothing read) with no reasoning -> a named detail,
    # never a blank. This is the 222 case ("empty failure, no error type").
    assert failure_detail(ExtractionStatus.FAILED, None) == FAILED_ALL_NULL_DETAIL
    assert failure_detail(ExtractionStatus.FAILED, "") == FAILED_ALL_NULL_DETAIL
    assert failure_detail(ExtractionStatus.FAILED, "   ") == FAILED_ALL_NULL_DETAIL
    assert "no exception" in FAILED_ALL_NULL_DETAIL  # self-explaining: not a crash
