"""LP-396 — two isolated "the tag exists, the rule can't consume it" cases. Phase 0 found BOTH still blocked.

A) IN-12 — a WIRING mismatch whose bar text was STALE. has_2yr_history is now measured 100% (LP-393-6), so the
   old "UNSCORED, blocked on calibration" was wrong. IN-12 reads it per_document (tax_return) while it is
   produced per_borrower -> structurally dead. The naive per_borrower re-scope is FORBIDDEN (it collapses IN-12
   into IN-11), and keeping it self-employment-specific needs a borrower-level self-employment signal that does
   not exist. So the bar is corrected to needs-producer (ADR-310); the rule stays inert.
B) AS-6 — a RE-SCORE that changed nothing. LP-390-8a (feed stmt_facts the borrower names) never landed: the
   `document` context builder still sends only the statement's own fields, so owner_matches_borrower still
   abstains (the LP-396 live re-score reproduced LP-390-5: 5/5 `unknown` vs golden `yes`; the AI's own reason
   was "no borrower names were provided"). Valid goldens DO exist (contradicting the "blanked" worry — that was
   the DB worksheet); the blocker is the producer, not the goldens. The bar already names this correctly.

Keyless: the live 0/5 re-score is reported in docs/tickets/LP-396.md, not asserted (model non-determinism);
these pin the structural facts that keep both blocked.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

from app.verification.rule_engine.activation_bars import load_activation_bars
from app.verification.snapshot.fields import Field, FieldSource
from app.verification.snapshot.model import DocumentEntry
from app.verification.tag_materialization.declarations import load_ai_groups, load_declarations
from app.verification.tag_materialization.subjects import subject_type

_JUDGMENT_CSV = Path(__file__).resolve().parents[4] / "docs/calibration/lf6t3n-labels-judgment.csv"


# --------------------------------------------------------------------------- #
# A) IN-12 — the stale bar is corrected; the rule stays needs-producer
# --------------------------------------------------------------------------- #
def test_in12_bar_is_needs_producer_naming_the_real_blocker() -> None:
    bar = load_activation_bars()["IN-12"]
    assert bar.status == "needs-producer"  # was the stale not-calibratable-yet
    assert bar.threshold is None and not bar.validated
    low = bar.rationale.lower()
    assert "self-employment" in low and "per_borrower" in low  # the wiring + specificity blocker
    assert "measured" in low  # explicitly says the tag IS measured (not the stale "unscored")
    # the corrected text asserts the blocker is NOT calibration (it may quote the old stale wording to explain)
    assert "not calibration-blocked" in low
    assert "producer" in low  # names the real fix — a borrower-level self-employment producer


def test_in12_borrower_level_self_employment_signal_now_exists_lp418() -> None:
    # LP-396 pinned the IN-12 gap: income.type (the self-employment discriminator) is a DOCUMENT-subject tag, so
    # no BORROWER-level self-employment signal existed and IN-12 could not be re-scoped. LP-418 closed it WITHOUT
    # a naive re-scope: income.is_self_employed (subject:borrower) is a DETERMINISTIC promotion of income.type —
    # it reads the borrower's own attributed income documents. income.type stays document-subject (that is WHY a
    # promotion, not a re-scope, was the right build).
    decls = load_declarations()
    assert (
        decls["income.type"].subject == "document"
    )  # unchanged — the promotion source, not re-scoped
    signal = decls["income.is_self_employed"]
    assert (
        signal.subject == "borrower"
    )  # LP-418 — the borrower-level signal IN-12's bar said was missing
    assert signal.mode == "derived"  # a deterministic promotion — NO new AI, NO calibration round


# --------------------------------------------------------------------------- #
# B) AS-6 — LP-390-8a never landed; the producer still can't see the borrower names
# --------------------------------------------------------------------------- #
def test_as6_producer_context_still_carries_no_borrower_roster() -> None:
    # the structural reason owner_matches_borrower still abstains: stmt_facts uses the `document` context
    # builder, which sends the statement's OWN fields only — never the loan's borrower roster to compare to.
    group = load_ai_groups()["stmt_facts"]
    assert group.context_builder == "document" and group.subject == "document"
    stmt = DocumentEntry(
        content_id="x",
        document_type="bank_statement",
        fields={"account_holder": Field.present("Jordan A Rivera", source=FieldSource.EXTRACTED)},
    )
    ctx = subject_type("document").build_context(stmt, None)
    assert "account_holder" in ctx  # it can see the name ON the statement...
    assert not any(
        "borrower" in k.lower() for k in ctx
    )  # ...but has NO borrower list to compare it against


def test_as6_goldens_exist_so_the_blocker_is_the_producer_not_the_goldens() -> None:
    # the ticket worried the goldens were blanked (LP-392) — but that was the DB worksheet; the committed
    # SYNTHETIC lf6t3n judgment worksheet still carries filled owner_matches_borrower goldens. So AS-6 is
    # blocked on the PRODUCER (it abstains), not on missing goldens.
    rows = [
        r
        for r in csv.DictReader(io.StringIO(_JUDGMENT_CSV.read_text(encoding="utf-8")))
        if r["tag_id"] == "stmt.owner_matches_borrower"
    ]
    filled = [r for r in rows if (r["golden_label"] or "").strip()]
    assert len(filled) >= 6  # a calibratable count of goldens EXISTS (8, all `yes`)
    assert all((r["golden_label"] or "").strip() == "yes" for r in filled)
    # secondary finding: some goldens are on investment_account subjects, but stmt_facts only runs on
    # bank_statement/money_market — so those rows can never be scored (a producer/worksheet scope mismatch).
    applies_to = load_ai_groups()["stmt_facts"].applies_to
    assert applies_to is not None
    assert "bank_statement" in applies_to and "investment_account" not in applies_to
