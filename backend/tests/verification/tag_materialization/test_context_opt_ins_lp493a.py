"""LP-493a — the two context opt-ins PC-5's investigation showed were missing.

⚠️ BOTH DEFAULT OFF. The whole suite passing unchanged (4587) is the evidence that every existing
group's context is byte-identical; these tests pin the new behaviour and, more importantly, the two
things it must NOT do.
"""

from __future__ import annotations

import json

import pytest
from app.verification.eval.lf6t3n_fixture import build_lf6t3n_snapshot
from app.verification.tag_materialization.declarations import load_ai_groups
from app.verification.tag_materialization.subjects import ContextOptions, subject_type


def _borrower_context(**opt_kwargs: bool) -> dict:
    snapshot = build_lf6t3n_snapshot()
    group = load_ai_groups()["contract_emd"]
    opts = ContextOptions(**opt_kwargs)
    subjects = subject_type("borrower").enumerate(snapshot)
    return subject_type("borrower").build_context(subjects[0][1], group.applies_to, opts)


def test_without_the_opt_ins_the_contract_and_transactions_are_absent() -> None:
    """⚠️ THE DEFECT, pinned so it cannot silently return. PC-5 was asked whether an earnest money
    deposit traced to a bank debit while being shown NEITHER — five statements' account-level fields and
    nothing else. It answered `unknown` twice and scored a perfect 1.0000 doing it."""
    context = json.dumps(_borrower_context())
    assert "earnest" not in context.lower()
    assert "transaction" not in context.lower()


def test_unattributed_documents_opt_in_brings_in_the_contract() -> None:
    """A purchase agreement is a PROPERTY document with no `belongs_to`, so borrower-scoped gathering
    dropped it. It is file-level, not "someone else's"."""
    documents = _borrower_context(include_unattributed_documents=True)["documents"]
    assert any(d["document_type"] == "purchase_agreement" for d in documents)
    assert "earnest" in json.dumps(documents).lower()


def test_transactions_opt_in_serialises_the_legacy_attribute() -> None:
    """⚠️ Transactions live in the LEGACY `entry.transactions`, NOT in `entry.lists` — which is empty on
    every one of LF-6T3N's statements. A group could declare include_lists, see nothing, and conclude the
    data was absent when it was one attribute away."""
    documents = _borrower_context(include_transactions=True)["documents"]
    rows = [r for d in documents for r in (d.get("transactions") or {}).get("rows", [])]
    assert len(rows) == 50
    assert {"date", "amount", "direction"} <= set(rows[0])


def test_another_borrowers_document_is_still_never_gathered() -> None:
    """⚠️ THE LINE THE OPT-IN MUST NOT CROSS. It relaxes attribution for UNATTRIBUTED documents only.
    A document belonging to a DIFFERENT borrower stays out — that would be the guessed attribution
    LP-332/LP-336 forbid, and the reason the borrower context filters at all."""
    snapshot = build_lf6t3n_snapshot()
    group = load_ai_groups()["contract_emd"]
    subjects = subject_type("borrower").enumerate(snapshot)
    assert len(subjects) == 2, "LF-6T3N has two borrowers — the test needs both"

    first, second = (
        subject_type("borrower").build_context(
            s[1], group.applies_to, ContextOptions(include_unattributed_documents=True)
        )
        for s in subjects
    )

    # Each borrower's ATTRIBUTED statements differ; only the unattributed contract is shared.
    def attributed_ids(ctx: dict) -> set[str]:
        return {
            json.dumps(d, sort_keys=True)
            for d in ctx["documents"]
            if d["document_type"] == "bank_statement"
        }

    shared = attributed_ids(first) & attributed_ids(second)
    assert not shared, (
        "a bank statement attributed to one borrower reached the other's context — the opt-in must "
        "relax UNATTRIBUTED documents only, never another borrower's"
    )


def test_the_opt_ins_stay_a_short_declared_list() -> None:
    """⚠️ THE BYTE-IDENTICAL GUARANTEE, made checkable. Both opt-ins default off, so every other group's
    context is unchanged — which is what lets a shared context-assembly change ship without re-deriving
    twenty groups. If a future group turns one on, it must re-derive; this test makes that visible.

    LP-495b review — `income_stability` turned `include_unattributed_documents` on, and that IS a re-derivation
    obligation, recorded rather than waved through. Why it was needed: a lease describes the PROPERTY and
    carries no belongs_to, so borrower-scoped gathering dropped it and income.continuance_3yr — IN-13's and
    IN-14's verdict tag — could never see the document establishing rental continuance. Why it is safe on
    today's data: the corpus carries ZERO leases on any loan file (measured), and the group's `applies_to`
    excludes every other property-level type (purchase_agreement, title_commitment, appraisal,
    flood_certification), so nothing else is added. The four LIVE rules on this group's other tags —
    IN-7 / IN-10 / IN-11 / IN-12 — see an unchanged context until the first lease arrives."""
    groups = load_ai_groups()
    with_unattributed = {k for k, g in groups.items() if g.include_unattributed_documents}
    with_transactions = {k for k, g in groups.items() if g.include_transactions}
    assert with_unattributed == {"contract_emd", "income_stability"}
    assert with_transactions == {"contract_emd"}


@pytest.mark.parametrize(
    ("opt_in", "subject"),
    [
        ("include_unattributed_documents", "document"),
        ("include_unattributed_documents", "loan"),
        ("include_transactions", "document"),
        ("include_transactions", "loan"),
    ],
)
def test_the_loader_rejects_the_opt_ins_on_a_wrong_subject(opt_in: str, subject: str) -> None:
    """A closed set, like `include_stated_liabilities`. Asking for borrower-attribution relaxation on a
    subject that never filters by attribution is a declaration ERROR, not a silent no-op.

    ⚠️ THIS USED TO GREP THE SOURCE FILE (reported finding), so inverting the very condition it claims to
    pin left it green — the message string was still in the file. It now exercises the LOADER: build a
    declaration with the opt-in on the wrong subject and require it to raise. `include_transactions` on a
    `document` subject is in the table because the validator used to ADMIT it while only the borrower
    context reads it, which is the silent no-op this guard exists to forbid.
    """
    import app.verification.tag_materialization.declarations as decl

    body = {
        "ai_groups": {
            "probe": {
                "subject": subject,
                "context_builder": subject,
                "tags": ["contract.emd_sourced"],
                "system_prompt": "probe",
                opt_in: True,
            }
        }
    }
    decl.load_ai_groups.cache_clear()
    original = decl._production_doc
    decl._production_doc = lambda: body  # type: ignore[assignment]
    try:
        with pytest.raises(decl.DeclarationError):
            decl.load_ai_groups()
    finally:
        decl._production_doc = original  # type: ignore[assignment]
        decl.load_ai_groups.cache_clear()
