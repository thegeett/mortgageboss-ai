"""LP-410 — the derived-producer wave: contract.days_until_closing, stmt.continuity,
income.employer_coverage. Three DESCRIPTIVE derived tags that unblock PC-7 / AS-8 / IN-6 (whose CHECKS
were inexpressible in the DSL — PC-7 no `today`; AS-8 ordered-pairwise, ADR-322; IN-6 set-coverage,
ADR-323). The tags describe (a number / an observed-state enum); the rules judge.

These pin: each value set + the fail-closed `unknown`; the not_applicable-ENABLING values (a single
statement → nothing_to_chain; one document type → one_sided); per-ACCOUNT isolation (no false global-gap)
and per-BORROWER isolation; determinism vs a fixed snapshot date (no wall-clock); and the subject match
(each tag is produced where its rule reads it — the anti-structural-death check, done now so the rules
aren't born dead).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
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
from app.verification.tag_materialization.declarations import load_declarations
from app.verification.tag_materialization.derived import (
    _contract_days_until_closing,
    _income_employer_coverage,
    _stmt_continuity,
)
from app.verification.tag_materialization.subjects import BorrowerSubject

_FILE_DATE = datetime(2026, 7, 14, tzinfo=UTC)


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
        tag_version=1,
        stage=TagStage.A,
    )


def _snap(
    *,
    docs: list[DocumentEntry] | None = None,
    tags: dict[str, dict[str, Tag]] | None = None,
    mismo: dict[str, Field | PiiField] | None = None,
    created: datetime = _FILE_DATE,
) -> Snapshot:
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=created,
        documents=DocumentsSection.present(list(docs or [])),
        mismo=MismoSection.present(mismo or {}),
        tags=TagsSection.present(tags or {}),
    )


# --------------------------------------------------------------------------- #
# contract.days_until_closing — a SIGNED number, no judgment, deterministic
# --------------------------------------------------------------------------- #
def _closing_snap(closing: str | None, *, created: datetime = _FILE_DATE) -> Snapshot:
    doc = DocumentEntry(content_id="c1", document_type="purchase_agreement")
    tags = {"c1": {"contract.closing_date": _tag(closing)}} if closing is not None else {}
    return _snap(docs=[doc], tags=tags, created=created)


def test_days_until_closing_future_is_a_positive_number() -> None:
    value, _ = _contract_days_until_closing(_closing_snap("2026-07-24"), "loan", None)
    assert value == "10"  # 2026-07-24 minus 2026-07-14


def test_days_until_closing_past_is_a_negative_number() -> None:
    # A past closing date is a MEANINGFUL observation (PC-7 decides it's stale) — the tag emits it, never
    # abstains to "unknown" the way a future-dated PAYSTUB does.
    value, reason = _contract_days_until_closing(_closing_snap("2026-07-04"), "loan", None)
    assert value == "-10" and "past" in reason


def test_days_until_closing_is_deterministic_no_wall_clock() -> None:
    # Same closing date, a fixed snapshot date → the SAME number every run (recency is against
    # snapshot.created_at, never datetime.now()).
    for _ in range(3):
        value, _ = _contract_days_until_closing(_closing_snap("2026-08-13"), "loan", None)
        assert value == "30"


def test_days_until_closing_absent_is_unknown() -> None:
    value, _ = _contract_days_until_closing(_closing_snap(None), "loan", None)
    assert value == "unknown"


def test_days_until_closing_disagreement_is_unknown() -> None:
    doc_a = DocumentEntry(content_id="a", document_type="purchase_agreement")
    doc_b = DocumentEntry(content_id="b", document_type="uniform_residential_loan_application")
    snap = _snap(
        docs=[doc_a, doc_b],
        tags={
            "a": {"contract.closing_date": _tag("2026-07-24")},
            "b": {"contract.closing_date": _tag("2026-08-24")},  # a different date
        },
    )
    value, reason = _contract_days_until_closing(snap, "loan", None)
    assert value == "unknown" and "disagree" in reason


# --------------------------------------------------------------------------- #
# stmt.continuity — per-account chaining, the not_applicable-enabling value, isolation
# --------------------------------------------------------------------------- #
def _stmt(cid: str, *, bank: str, masked: str, start: str, begin: str, end: str) -> DocumentEntry:
    return DocumentEntry(
        content_id=cid,
        document_type="bank_statement",
        fields={"bank_name": _f(bank), "account_number_masked": _f(masked)},
    )


def _stmt_tags(cid: str, *, start: str, begin: str, end: str) -> dict[str, dict[str, Tag]]:
    return {
        cid: {
            "stmt.period_start": _tag(start),
            "stmt.beginning_balance": _tag(begin),
            "stmt.ending_balance": _tag(end),
        }
    }


def test_continuity_chained() -> None:
    docs = [
        _stmt("s1", bank="Chase", masked="****1", start="2026-01-01", begin="1000", end="1200"),
        _stmt("s2", bank="Chase", masked="****1", start="2026-02-01", begin="1200", end="1300"),
    ]
    tags = {
        **_stmt_tags("s1", start="2026-01-01", begin="1000", end="1200"),
        **_stmt_tags("s2", start="2026-02-01", begin="1200", end="1300"),
    }
    value, _ = _stmt_continuity(_snap(docs=docs, tags=tags), "loan", None)
    assert value == "chained"


def test_continuity_broken_when_balances_do_not_carry() -> None:
    docs = [
        _stmt("s1", bank="Chase", masked="****1", start="2026-01-01", begin="1000", end="1200"),
        _stmt("s2", bank="Chase", masked="****1", start="2026-02-01", begin="1250", end="1300"),
    ]
    tags = {
        **_stmt_tags("s1", start="2026-01-01", begin="1000", end="1200"),
        **_stmt_tags("s2", start="2026-02-01", begin="1250", end="1300"),  # 1200 ≠ 1250
    }
    value, reason = _stmt_continuity(_snap(docs=docs, tags=tags), "loan", None)
    assert value == "broken" and "carry" in reason
    # LP-406-2b review: the reason must LOCATE the break (account + the two mismatched balances) so AS-8's
    # fired finding is actionable — not a generic "some account doesn't chain".
    assert "****1" in reason and "1200" in reason and "1250" in reason


def test_continuity_single_statement_is_nothing_to_chain_not_couldnt_check() -> None:
    # THE TRAP: one statement for an account = nothing to chain = a value that lets AS-8 reach
    # not_applicable — NOT "unknown" (which would make AS-8 couldnt_check on an ordinary one-statement file).
    docs = [_stmt("s1", bank="Chase", masked="****1", start="2026-01-01", begin="1000", end="1200")]
    tags = _stmt_tags("s1", start="2026-01-01", begin="1000", end="1200")
    value, _ = _stmt_continuity(_snap(docs=docs, tags=tags), "loan", None)
    assert value == "nothing_to_chain"


def test_continuity_no_statements_is_nothing_to_chain() -> None:
    value, _ = _stmt_continuity(_snap(), "loan", None)
    assert value == "nothing_to_chain"


def test_continuity_unreadable_balance_is_unknown() -> None:
    docs = [
        _stmt("s1", bank="Chase", masked="****1", start="2026-01-01", begin="1000", end="1200"),
        _stmt("s2", bank="Chase", masked="****1", start="2026-02-01", begin="1200", end="1300"),
    ]
    tags = {
        **_stmt_tags("s1", start="2026-01-01", begin="1000", end="1200"),
        "s2": {
            "stmt.period_start": _tag("2026-02-01"),
            "stmt.beginning_balance": _tag("unknown"),  # unreadable
            "stmt.ending_balance": _tag("1300"),
        },
    }
    value, _ = _stmt_continuity(_snap(docs=docs, tags=tags), "loan", None)
    assert value == "unknown"


def test_continuity_per_account_isolation_no_false_global_gap() -> None:
    # Chase Jan→Mar chains (1200 → 1200); a separate Wells account has ONE statement in between. A GLOBAL
    # date-chain would pair Chase-Jan-end (1200) with Wells-Feb-begin (5000) and fabricate a break — the
    # per-account grouping (resolve_accounts) prevents that. Expect "chained".
    docs = [
        _stmt("c1", bank="Chase", masked="****1", start="2026-01-01", begin="1000", end="1200"),
        _stmt("w1", bank="Wells", masked="****9", start="2026-02-01", begin="5000", end="5100"),
        _stmt("c2", bank="Chase", masked="****1", start="2026-03-01", begin="1200", end="1300"),
    ]
    tags = {
        **_stmt_tags("c1", start="2026-01-01", begin="1000", end="1200"),
        **_stmt_tags("w1", start="2026-02-01", begin="5000", end="5100"),
        **_stmt_tags("c2", start="2026-03-01", begin="1200", end="1300"),
    }
    value, _ = _stmt_continuity(_snap(docs=docs, tags=tags), "loan", None)
    assert value == "chained"


def test_continuity_break_in_one_account_is_surfaced_fire_if_any() -> None:
    # Chase chains, Wells does not (5100 → 6000). A break in ANY account → "broken" (never masked by a
    # clean sibling).
    docs = [
        _stmt("c1", bank="Chase", masked="****1", start="2026-01-01", begin="1000", end="1200"),
        _stmt("c2", bank="Chase", masked="****1", start="2026-02-01", begin="1200", end="1300"),
        _stmt("w1", bank="Wells", masked="****9", start="2026-01-01", begin="5000", end="5100"),
        _stmt("w2", bank="Wells", masked="****9", start="2026-02-01", begin="6000", end="6100"),
    ]
    tags = {
        **_stmt_tags("c1", start="2026-01-01", begin="1000", end="1200"),
        **_stmt_tags("c2", start="2026-02-01", begin="1200", end="1300"),
        **_stmt_tags("w1", start="2026-01-01", begin="5000", end="5100"),
        **_stmt_tags("w2", start="2026-02-01", begin="6000", end="6100"),  # 5100 ≠ 6000
    }
    value, _ = _stmt_continuity(_snap(docs=docs, tags=tags), "loan", None)
    assert value == "broken"


def test_continuity_per_borrower_isolation_colliding_last4_not_merged() -> None:
    # LP-406-2b review: two DIFFERENT borrowers whose accounts COLLIDE on the same institution + masked
    # last-4 must NOT be chained against each other. Each chains cleanly on its OWN statements; a global
    # (institution, masked) merge would pair borrower A's ending balance against borrower B's opening and
    # FABRICATE a break. Per-borrower sub-grouping (belongs_to) keeps them separate → "chained".
    a, b = str(uuid4()), str(uuid4())

    def _bs(cid: str, owner: str) -> DocumentEntry:
        return DocumentEntry(
            content_id=cid,
            document_type="bank_statement",
            belongs_to=(BorrowerRef(borrower_id=UUID(owner), name="X"),),
            fields={"bank_name": _f("Chase"), "account_number_masked": _f("****1234")},
        )

    docs = [
        _bs("a1", a),
        _bs("a2", a),
        _bs("b1", b),
        _bs("b2", b),
    ]  # same bank + last-4, two borrowers
    tags = {
        **_stmt_tags("a1", start="2026-01-01", begin="1000", end="1200"),
        **_stmt_tags("a2", start="2026-02-01", begin="1200", end="1300"),  # A chains 1200 -> 1200
        **_stmt_tags("b1", start="2026-01-01", begin="5000", end="5200"),
        **_stmt_tags("b2", start="2026-02-01", begin="5200", end="5400"),  # B chains 5200 -> 5200
    }
    value, _ = _stmt_continuity(_snap(docs=docs, tags=tags), "loan", None)
    # A merged chain would pair A-Jan-end (1200) with B-Jan-begin (5000) -> a false "broken". Isolated: chained.
    assert value == "chained"


def test_continuity_all_periods_unreadable_on_a_multi_statement_account_is_unknown() -> None:
    # LP-410 review (fail-open fix): an account with TWO statements whose period_start is unreadable on BOTH
    # (neither orderable) must be UNKNOWN, never a silent "nothing_to_chain". Balances are readable; only the
    # periods are not, so we cannot order/confirm the chain → fail-closed. Pre-fix this returned
    # "nothing_to_chain" (→ AS-8 would not_applicable on two statements it never actually checked).
    docs = [
        _stmt("s1", bank="Chase", masked="****1", start="x", begin="1000", end="1200"),
        _stmt("s2", bank="Chase", masked="****1", start="x", begin="1200", end="1300"),
    ]
    tags = {
        "s1": {
            "stmt.period_start": _tag("unknown"),  # unreadable period on BOTH
            "stmt.beginning_balance": _tag("1000"),
            "stmt.ending_balance": _tag("1200"),
        },
        "s2": {
            "stmt.period_start": _tag("unknown"),
            "stmt.beginning_balance": _tag("1200"),
            "stmt.ending_balance": _tag("1300"),
        },
    }
    value, _ = _stmt_continuity(_snap(docs=docs, tags=tags), "loan", None)
    assert value == "unknown"


# --------------------------------------------------------------------------- #
# income.employer_coverage — per-borrower set coverage, one_sided, isolation
# --------------------------------------------------------------------------- #
def _income_doc(cid: str, doctype: str, bid: str) -> DocumentEntry:
    return DocumentEntry(
        content_id=cid,
        document_type=doctype,
        belongs_to=(BorrowerRef(borrower_id=UUID(bid), name="Sam"),),
    )


def _cov(docs: list[DocumentEntry], employers: dict[str, str], bid: str, *, index: int = 1) -> str:
    tags = {cid: {"income.employer_normalized": _tag(emp)} for cid, emp in employers.items()}
    mismo: dict[str, Field | PiiField] = {"borrower.1.borrower_id": _f(bid)}
    snap = _snap(docs=docs, tags=tags, mismo=mismo)
    value, _ = _income_employer_coverage(snap, bid, BorrowerSubject(bid, index, snap))
    return str(value)


def test_coverage_covered_reuses_in5_normalization() -> None:
    # "Acme Corp" (pay stub) and "Acme" (W-2) normalize equal (drop_entity_suffix) → covered. Same
    # deterministic normalization IN-5's exact bookend uses — no new judgment.
    bid = str(uuid4())
    docs = [_income_doc("p1", "pay_stub", bid), _income_doc("w1", "w2", bid)]
    assert _cov(docs, {"p1": "Acme Corp", "w1": "Acme"}, bid) == "covered"


def test_coverage_covered_two_employers_the_set_coverage_case() -> None:
    # The case ConsistencyEval could NOT express (it would see {Acme, Beta} differ → fire): two employers,
    # each covered on both sides → covered.
    bid = str(uuid4())
    docs = [
        _income_doc("p1", "pay_stub", bid),
        _income_doc("p2", "pay_stub", bid),
        _income_doc("w1", "w2", bid),
        _income_doc("w2", "w2", bid),
    ]
    emps = {"p1": "Acme", "p2": "Beta", "w1": "Acme", "w2": "Beta"}
    assert _cov(docs, emps, bid) == "covered"


def test_coverage_uncovered_when_an_employer_lacks_a_counterpart() -> None:
    bid = str(uuid4())
    docs = [
        _income_doc("p1", "pay_stub", bid),
        _income_doc("p2", "pay_stub", bid),
        _income_doc("w1", "w2", bid),
    ]
    # Beta is on a pay stub but has no W-2 → uncovered.
    assert _cov(docs, {"p1": "Acme", "p2": "Beta", "w1": "Acme"}, bid) == "uncovered"


def test_coverage_one_sided_when_only_one_document_type() -> None:
    # THE TRAP (IN-6 form): only W-2s, no pay stubs → nothing to cross-check → one_sided (lets IN-6 reach
    # not_applicable), NOT a finding and NOT couldnt_check.
    bid = str(uuid4())
    docs = [_income_doc("w1", "w2", bid), _income_doc("w2", "w2", bid)]
    assert _cov(docs, {"w1": "Acme", "w2": "Acme"}, bid) == "one_sided"


def test_coverage_no_income_docs_is_one_sided() -> None:
    bid = str(uuid4())
    assert _cov([], {}, bid) == "one_sided"


def test_coverage_unreadable_employer_is_unknown() -> None:
    bid = str(uuid4())
    docs = [_income_doc("p1", "pay_stub", bid), _income_doc("w1", "w2", bid)]
    assert _cov(docs, {"p1": "unknown", "w1": "Acme"}, bid) == "unknown"


def test_coverage_tags_absent_with_documents_is_unknown_not_one_sided() -> None:
    # LP-410 review (fail-open fix): the borrower HAS both a pay stub and a W-2, but no tags materialized
    # (a degraded/no-AI run). We could not read any employer → UNKNOWN, never "one_sided" (which would
    # falsely claim there was nothing to cross-check). documents.absent stays one_sided; only tags.absent-
    # with-documents is unknown.
    bid = str(uuid4())
    docs = [_income_doc("p1", "pay_stub", bid), _income_doc("w1", "w2", bid)]
    snap = Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=_FILE_DATE,
        documents=DocumentsSection.present(docs),
        mismo=MismoSection.present({"borrower.1.borrower_id": _f(bid)}),
        tags=TagsSection.missing(),  # documents present, but the tags layer never materialized
    )
    value, _ = _income_employer_coverage(snap, bid, BorrowerSubject(bid, 1, snap))
    assert value == "unknown"


def test_coverage_per_borrower_isolation() -> None:
    # Borrower A has ONLY a pay stub; borrower B has ONLY a W-2 (same employer). Each is judged on its OWN
    # documents (belongs_to) — A's pay stub must NOT cover B's W-2. If coverage pooled across borrowers,
    # both would read "covered"; per-borrower isolation makes each "one_sided".
    a, b = str(uuid4()), str(uuid4())
    docs = [_income_doc("p1", "pay_stub", a), _income_doc("w1", "w2", b)]
    tags = {
        "p1": {"income.employer_normalized": _tag("Acme")},
        "w1": {"income.employer_normalized": _tag("Acme")},
    }
    mismo: dict[str, Field | PiiField] = {
        "borrower.1.borrower_id": _f(a),
        "borrower.2.borrower_id": _f(b),
    }
    snap = _snap(docs=docs, tags=tags, mismo=mismo)
    a_val, _ = _income_employer_coverage(snap, a, BorrowerSubject(a, 1, snap))
    b_val, _ = _income_employer_coverage(snap, b, BorrowerSubject(b, 2, snap))
    assert a_val == "one_sided" and b_val == "one_sided"


# --------------------------------------------------------------------------- #
# The subject match — each tag is produced where its rule reads it (anti-structural-death)
# --------------------------------------------------------------------------- #
def test_each_tag_is_produced_at_the_subject_its_rule_reads() -> None:
    decl = load_declarations()
    assert decl["contract.days_until_closing"].subject == "loan"  # PC-7 (loan)
    assert decl["stmt.continuity"].subject == "loan"  # AS-8 (loan)
    assert decl["income.employer_coverage"].subject == "borrower"  # IN-6 (per_borrower)


def test_the_three_tags_are_registered_derived_recipes() -> None:
    from app.verification.tag_materialization.derived import KNOWN_RECIPES

    for recipe in ("contract_days_until_closing", "stmt_continuity", "income_employer_coverage"):
        assert recipe in KNOWN_RECIPES


def test_days_until_closing_uses_the_snapshot_date_object() -> None:
    # Guards against a wall-clock regression: a snapshot dated 2026-07-14 with closing 2026-07-14 is 0.
    value, _ = _contract_days_until_closing(_closing_snap("2026-07-14"), "loan", None)
    assert value == "0"
    assert _FILE_DATE.date() == date(2026, 7, 14)
