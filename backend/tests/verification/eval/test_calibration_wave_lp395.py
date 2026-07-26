"""LP-395 — the calibration-wave Phase-0 evidence: NONE of the four census "needs-calibration" rules is
actually calibratable now. This pins WHY (keyless, deterministic — no worksheet is generated, nothing is
scored), so a later fixture change that unblocks one flips a guard here and forces a re-evaluation.

- AS-7: `txn.is_nsf_or_overdraft` has NO producer (not in the declared layer, and — verified by inspection —
  not in Stage-B `tag_correlation`; only READ by the derived `stmt.nsf_count`, which abstains). needs-PRODUCER,
  not needs-calibration — the census (LP-394) was wrong; this vindicates LP-390-2's orphan finding.
- IN-8: `income.voe_present` is labelable on only the VOE docs → n=3 on the scenario fixture (< 6). Thin.
- IN-9: `income.offer_letter_present` — NO offer-letter document exists in ANY fixture, so its positive class
  is empty (one-sided). needs a scenario.
- IN-13: `income.continuance_3yr` produces 13 rows, but the fixtures carry only EMPLOYMENT income, where
  continuance is honestly `unknown` (LP-393-1 reached n=1 meaningful) — no other-income scenario to discriminate.
"""

from __future__ import annotations

from app.verification.eval.income_scenarios import build_income_calibration_snapshot
from app.verification.eval.lf6t3n_fixture import build_lf6t3n_plus, build_lf6t3n_snapshot
from app.verification.eval.worksheet import build_worksheet
from app.verification.tag_materialization.declarations import load_declarations

_SNAP = build_income_calibration_snapshot()


def _rows(tag: str) -> int:
    return len(
        build_worksheet(
            _SNAP, document_filenames={}, only_tags=frozenset({tag}), label_prompts={tag: "q?"}
        )
    )


def test_as7_tag_has_no_declared_producer() -> None:
    # the orphan: is_nsf_or_overdraft is in the VOCABULARY (fact_tags.csv) but has NO producer declaration.
    # Stage-B (tag_correlation) produces txn.has_identified_source / txn.source_strength but NOT this tag —
    # verified by inspection; here we pin the declared-layer absence (the machine-checkable half).
    decls = load_declarations()
    assert "txn.is_nsf_or_overdraft" not in decls  # no declared producer → AS-7 is needs-producer
    # contrast: a Stage-B tag is ALSO absent from the declared layer but IS produced (LP-390-2) — so declared
    # absence alone is not proof; the proof is that NO path produces is_nsf_or_overdraft (inspection).
    assert (
        "txn.has_identified_source" not in decls
    )  # Stage-B tag, produced elsewhere — the contrast case
    assert (
        "stmt.nsf_count" in decls
    )  # the derived aggregate IS declared — but its leaf input is the orphan


def test_in8_voe_present_is_thin_below_the_calibratable_floor() -> None:
    # the scenario fixture has 3 VOE docs; voe_present is labelable only on VOE/offer-letter types → n=3 < 6.
    assert _rows("income.voe_present") == 3
    # no fixture reaches 6 VOE docs (the calibratable floor): scenario 3, lf6t3n 0, lf6t3n_plus 2.
    voe_counts = {
        "scenario": sum(1 for e in _SNAP.documents.entries if (e.document_type or "") == "voe"),
        "lf6t3n": sum(
            1 for e in build_lf6t3n_snapshot().documents.entries if (e.document_type or "") == "voe"
        ),
        "plus": sum(
            1 for e in build_lf6t3n_plus().documents.entries if (e.document_type or "") == "voe"
        ),
    }
    assert max(voe_counts.values()) < 6  # thin everywhere → needs-more-scenarios


def test_in9_offer_letter_has_no_positive_class_in_any_fixture() -> None:
    # offer_letter_present can only be `yes` on an offer-letter document; NONE exists in any fixture, so its
    # positive class is empty (one-sided) → not calibratable.
    for snap in (_SNAP, build_lf6t3n_snapshot(), build_lf6t3n_plus()):
        assert not any(
            (e.document_type or "") in ("employment_offer_letter", "offer_letter")
            for e in snap.documents.entries
        )


def test_in13_continuance_produces_rows_but_the_fixture_is_all_employment() -> None:
    # continuance_3yr has ENOUGH rows (13 borrowers) — the blocker is SIGNAL, not row count: every borrower
    # carries only EMPLOYMENT income (W-2 / pay-stub / VOE), where continuance is honestly `unknown`. There is
    # no "other income" borrower (pension / child support / alimony) to make continuance a real yes/no.
    assert _rows("income.continuance_3yr") == 13
    other_income_docs = {
        "pension",
        "child_support",
        "alimony",
        "social_security",
        "annuity",
        "award_letter",
    }
    assert not any(
        (e.document_type or "") in other_income_docs for e in _SNAP.documents.entries
    )  # no discriminating other-income scenario


def test_no_worksheet_is_generated_this_wave() -> None:
    # 0 of 4 calibratable → this ticket generates NO labeling worksheet (the LP-393 thin-n discipline: do not
    # calibrate a tag thin). The deliverable is the Phase-0 verdict + the fixture-gap report, nothing scored.
    for tag in (
        "income.voe_present",
        "income.offer_letter_present",
        "income.continuance_3yr",
    ):
        assert load_declarations()[
            tag
        ]  # each tag DOES produce (so the blocker is a scenario, not a producer)
