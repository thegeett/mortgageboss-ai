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

import pytest
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
    _p = _contract_days_until_closing(_closing_snap("2026-07-24"), "loan", None)
    value, _ = _p[0], _p[1]
    assert value == "10"  # 2026-07-24 minus 2026-07-14


def test_days_until_closing_past_is_a_negative_number() -> None:
    # A past closing date is a MEANINGFUL observation (PC-7 decides it's stale) — the tag emits it, never
    # abstains to "unknown" the way a future-dated PAYSTUB does.
    _p = _contract_days_until_closing(_closing_snap("2026-07-04"), "loan", None)
    value, reason = _p[0], _p[1]
    assert value == "-10" and "past" in reason


def test_days_until_closing_is_deterministic_no_wall_clock() -> None:
    # Same closing date, a fixed snapshot date → the SAME number every run (recency is against
    # snapshot.created_at, never datetime.now()).
    for _ in range(3):
        _p = _contract_days_until_closing(_closing_snap("2026-08-13"), "loan", None)
        value, _ = _p[0], _p[1]
        assert value == "30"


def test_days_until_closing_absent_is_unknown() -> None:
    _p = _contract_days_until_closing(_closing_snap(None), "loan", None)
    value, _ = _p[0], _p[1]
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
    _p = _contract_days_until_closing(snap, "loan", None)
    value, reason = _p[0], _p[1]
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
    produced = _stmt_continuity(_snap(docs=docs, tags=tags), "loan", None)
    value, reason = produced[0], produced[1]
    assert value == "broken" and "carry" in reason
    # LP-406-2b review: the reason must LOCATE the break (account + the two mismatched balances) so AS-8's
    # fired finding is actionable — not a generic "some account doesn't chain".
    assert "****1" in reason and "1200" in reason and "1250" in reason
    # LP-647 §1 — AND IT MUST NAME THE TWO STATEMENTS, in order.
    #
    # Locating the break in PROSE was half the job: `produce_derived_tags` sets
    # `source_facts=(subject_id,)`, which for a loan-subject recipe is the literal "loan", so the
    # finding could say the balances and not the documents. A processor was told the chain breaks
    # and not which statements to open.
    assert len(produced) == 3, "the broken path must carry the statements it compared"
    assert produced[2] == ("s1", "s2"), "the PAIR that disagrees, in order"


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
    produced = _stmt_continuity(_snap(docs=docs, tags=tags), "loan", None)
    assert produced[0] == "broken"
    # LP-647 §1 — the WELLS pair, not the Chase one that chains cleanly. Naming every statement on
    # the file would point a processor at documents the finding says nothing about.
    assert produced[2] == ("w1", "w2")


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
    # bug-017 — the recipe now names the documents it compared on covered/uncovered, so it returns a
    # 3-tuple there and a 2-tuple where it has nothing to name. Index rather than unpack.
    return str(_income_employer_coverage(snap, bid, BorrowerSubject(bid, index, snap))[0])


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
    value = _income_employer_coverage(snap, bid, BorrowerSubject(bid, 1, snap))[0]
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
    a_val = _income_employer_coverage(snap, a, BorrowerSubject(a, 1, snap))[0]
    b_val = _income_employer_coverage(snap, b, BorrowerSubject(b, 2, snap))[0]
    assert a_val == "one_sided" and b_val == "one_sided"


# --------------------------------------------------------------------------- #
# bug-017 — IN-6 names the pay stubs and W-2s it compared
# --------------------------------------------------------------------------- #
def test_coverage_uncovered_names_the_documents_it_compared() -> None:
    """THE LF-XMB2 SHAPE. IN-6's finding said an employer appears on one document type but not the
    other and linked NO document, while AS-8's finding — same file, same run — named its two
    statements. The difference was entirely the recipe's return arity."""
    bid = str(uuid4())
    docs = [_income_doc("p1", "pay_stub", bid), _income_doc("w1", "w2", bid)]
    tags = {
        "p1": {"income.employer_normalized": _tag("COPA Exec Off")},
        "w1": {"income.employer_normalized": _tag("Commonwealth Of Pennsylvania")},
    }
    snap = _snap(docs=docs, tags=tags, mismo={"borrower.1.borrower_id": _f(bid)})

    produced = _income_employer_coverage(snap, bid, BorrowerSubject(bid, 1, snap))

    assert produced[0] == "uncovered"
    assert len(produced) == 3
    # THE ORDERING IS THE LOAD-BEARING PART. The employer the sentence names is whichever sorts first
    # among the uncovered — normalized, "commonwealth of pennsylvania" < "copa exec off" — so the W-2
    # is the document that states it, and the W-2 must LEAD: the first id becomes the finding's
    # source_document_id, the single document the UI opens (bug-013 review). The pay stub follows as
    # the side it was compared against.
    assert produced[2] == ("w1", "p1")
    assert "Commonwealth Of Pennsylvania" in produced[1]
    assert "W-2s" in produced[1] and "not on a pay stub" in produced[1]


def test_coverage_covered_names_every_document_it_read() -> None:
    bid = str(uuid4())
    docs = [_income_doc("p1", "pay_stub", bid), _income_doc("w1", "w2", bid)]
    tags = {
        "p1": {"income.employer_normalized": _tag("Acme Corp")},
        "w1": {"income.employer_normalized": _tag("Acme")},  # normalizes equal
    }
    snap = _snap(docs=docs, tags=tags, mismo={"borrower.1.borrower_id": _f(bid)})

    produced = _income_employer_coverage(snap, bid, BorrowerSubject(bid, 1, snap))

    assert produced[0] == "covered"
    assert produced[2] == ("p1", "w1")


def test_coverage_names_nothing_when_it_compared_nothing() -> None:
    """one_sided and unknown have no comparison to point at. EMPTY IS HONEST — the subject stands, and
    `_source_document_ids` drops a borrower id rather than writing a link to a document."""
    bid = str(uuid4())
    snap = _snap(
        docs=[_income_doc("p1", "pay_stub", bid)],
        tags={"p1": {"income.employer_normalized": _tag("Acme")}},
        mismo={"borrower.1.borrower_id": _f(bid)},
    )

    produced = _income_employer_coverage(snap, bid, BorrowerSubject(bid, 1, snap))

    assert produced[0] == "one_sided" and len(produced) == 2


def test_coverage_unknown_names_the_document_it_could_not_read() -> None:
    """bug-017 review — THE BRANCH WHERE THE LINK MATTERS MOST, and it named nothing.

    "one_sided and unknown have no comparison to point at" is true of one_sided, which never reaches a
    finding at all (IN-6's applicability makes it not_applicable). It is NOT true of unknown: that branch
    is reached only when an employer name could not be READ, so the recipe knows precisely which document
    defeated it — and IN-6 still shipped "an employer name on ONE of this borrower's income documents
    could not be read" with no way to tell which. The unreadable document leads, then what was read.
    """
    bid = str(uuid4())
    docs = [_income_doc("p1", "pay_stub", bid), _income_doc("w1", "w2", bid)]
    snap = _snap(
        docs=docs,
        tags={
            "p1": {"income.employer_normalized": _tag("Acme")}
        },  # the W-2's name never materialized
        mismo={"borrower.1.borrower_id": _f(bid)},
    )

    produced = _income_employer_coverage(snap, bid, BorrowerSubject(bid, 1, snap))

    assert produced[0] == "unknown"
    assert len(produced) == 3
    assert produced[2] == ("w1", "p1")


@pytest.mark.asyncio
async def test_in6_couldnt_check_end_to_end_names_the_unreadable_document() -> None:
    """And through the real evaluator, because the couldnt_check takes a DIFFERENT path to the finding
    than the uncovered one: it terminates at applicability rather than at an outcome. That path builds
    its result with the subject's load-bearing tags too, which is what carries the ids — so the abstention
    a processor reads can name the document to open."""
    from app.verification.rule_engine.registry import evaluate_rules
    from app.verification.rule_engine.result import Verdict
    from app.verification.tag_materialization.producer import materialize_tags

    bid = str(uuid4())
    docs = [_income_doc("p1", "pay_stub", bid), _income_doc("w1", "w2", bid)]
    snapshot = await materialize_tags(
        _snap(
            docs=docs,
            tags={"p1": {"income.employer_normalized": _tag("Acme")}},
            mismo={"borrower.1.borrower_id": _f(bid)},
        ),
        only_groups=frozenset(),
    )

    evaluations, _tags = await evaluate_rules(snapshot, rule_ids=("IN-6",))

    assert evaluations, "IN-6 produced no evaluation — the fixture does not reach the rule"
    result = evaluations[0]
    assert result.verdict is Verdict.COULDNT_CHECK
    assert result.source_content_ids == ("w1", "p1"), (
        "an abstention that cannot say WHICH document it could not read is the complaint bug-017 "
        f"exists to answer. Got {result.source_content_ids}"
    )


@pytest.mark.asyncio
async def test_in6_end_to_end_names_the_documents_on_the_evaluation() -> None:
    """THROUGH THE REAL EVALUATOR (LP-487's standing rule), which is the only version that proves a
    processor sees it: the tag carrying ids proves the recipe, `source_content_ids` proves the bridge."""
    from app.verification.rule_engine.registry import evaluate_rules
    from app.verification.tag_materialization.producer import materialize_tags

    bid = str(uuid4())
    docs = [_income_doc("p1", "pay_stub", bid), _income_doc("w1", "w2", bid)]
    tags = {
        "p1": {"income.employer_normalized": _tag("COPA Exec Off")},
        "w1": {"income.employer_normalized": _tag("Commonwealth Of Pennsylvania")},
    }
    snapshot = await materialize_tags(
        _snap(docs=docs, tags=tags, mismo={"borrower.1.borrower_id": _f(bid)}),
        only_groups=frozenset(),
    )

    evaluations, _tags = await evaluate_rules(snapshot, rule_ids=("IN-6",))

    assert evaluations, "IN-6 produced no evaluation — the fixture does not reach the rule"
    result = evaluations[0]
    # W-2 first: it states 'Commonwealth Of Pennsylvania', the employer the finding's sentence names
    # (it sorts first among the uncovered), and the leading id is the document the UI opens.
    assert result.source_content_ids == ("w1", "p1"), (
        "the pay stub and W-2 the recipe compared must reach `source_content_ids` — the only field "
        f"`_source_document_ids` reads, and so the only one a processor sees. Got "
        f"{result.source_content_ids}"
    )


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
    _p = _contract_days_until_closing(_closing_snap("2026-07-14"), "loan", None)
    value, _ = _p[0], _p[1]
    assert value == "0"
    assert _FILE_DATE.date() == date(2026, 7, 14)


def test_the_tag_carries_its_statements_all_the_way_into_source_facts() -> None:
    """LP-647 §1 — AT THE LAYER THE DEFECT WAS SEEN, not at the recipe that returns the ids.

    The recipe returning `("s1", "s2")` proves nothing on its own: the value has to survive
    `produce_derived_tags`, which is the function that was overwriting it. It sets
    `source_facts=(subject_id,)`, and a loan-subject recipe's subject_id is the literal string
    "loan" — which is exactly what LF-JR4T's AS-8 finding carried, and why
    `_attach_document_provenance` had nothing to attach and the finding rendered with no documents.

    A test that stopped at the recipe would have passed against the shipped defect.
    """
    from app.verification.tag_materialization.declarations import load_declarations
    from app.verification.tag_materialization.derived import produce_derived_tags

    docs = [
        _stmt("s1", bank="Chase", masked="****1", start="2026-01-01", begin="1000", end="1200"),
        _stmt("s2", bank="Chase", masked="****1", start="2026-02-01", begin="1250", end="1300"),
    ]
    tags = {
        **_stmt_tags("s1", start="2026-01-01", begin="1000", end="1200"),
        **_stmt_tags("s2", start="2026-02-01", begin="1250", end="1300"),  # 1200 ≠ 1250
    }
    decl = load_declarations()["stmt.continuity"]

    produced = produce_derived_tags(decl, _snap(docs=docs, tags=tags))

    tag = produced["loan"]["stmt.continuity"]
    assert tag.value == "broken"
    assert tag.source_facts == ("s1", "s2"), (
        "the tag reached the snapshot naming the loan instead of the statements — the shipped "
        f"behaviour this closes, got {tag.source_facts}"
    )


def test_a_recipe_with_nothing_to_name_still_falls_back_to_its_subject() -> None:
    """THE POSITIVE CONTROL, and it guards a real regression: 77 of 79 recipes return two elements
    and must keep their subject as their source. A tag over a computed figure — DTI, reserves — has
    no document to point at, and `_attach_document_provenance`'s own rule is that inventing one
    "would send a processor to the wrong page with the system's confidence behind it".

    The chained path is the same recipe with nothing to name, which makes it the cheapest proof that
    the fallback survives.
    """
    from app.verification.tag_materialization.declarations import load_declarations
    from app.verification.tag_materialization.derived import produce_derived_tags

    docs = [
        _stmt("s1", bank="Chase", masked="****1", start="2026-01-01", begin="1000", end="1200"),
        _stmt("s2", bank="Chase", masked="****1", start="2026-02-01", begin="1200", end="1300"),
    ]
    tags = {
        **_stmt_tags("s1", start="2026-01-01", begin="1000", end="1200"),
        **_stmt_tags("s2", start="2026-02-01", begin="1200", end="1300"),  # chains
    }
    decl = load_declarations()["stmt.continuity"]

    tag = produce_derived_tags(decl, _snap(docs=docs, tags=tags))["loan"]["stmt.continuity"]

    assert tag.value == "chained"
    assert tag.source_facts == ("loan",), "no break, nothing to name — the subject stands"


@pytest.mark.asyncio
async def test_as8_end_to_end_names_the_statements_on_the_evaluation() -> None:
    """LP-647 §1 review — THROUGH THE REAL EVALUATOR, which is the only version that proves the fix.

    This repo has a standing rule for exactly this reason (LP-487): a verdict assertion runs through
    `materialize_tags` then `evaluate_rules`, "never by calling a recipe or the gate directly",
    because LP-508 shipped a guard whose own test called the mechanism directly — the mechanism
    worked and the WIRING did not.

    My first attempt at this test broke that rule in a subtler way: it hand-built the
    `RuleEvaluation` with `source_content_ids` already set, so it asserted the field the bridge is
    supposed to POPULATE. Removing the bridge entirely left it green. The unit test below is a
    supplement to this one, never a substitute.
    """
    from app.verification.rule_engine.registry import evaluate_rules
    from app.verification.tag_materialization.producer import materialize_tags

    docs = [
        _stmt("s1", bank="Chase", masked="****1", start="2026-01-01", begin="1000", end="1200"),
        _stmt("s2", bank="Chase", masked="****1", start="2026-02-01", begin="1250", end="1300"),
    ]
    tags = {
        **_stmt_tags("s1", start="2026-01-01", begin="1000", end="1200"),
        **_stmt_tags("s2", start="2026-02-01", begin="1250", end="1300"),  # 1200 ≠ 1250
    }
    snapshot = await materialize_tags(_snap(docs=docs, tags=tags), only_groups=frozenset())

    evaluations, _tags = await evaluate_rules(snapshot, rule_ids=("AS-8",))

    assert evaluations, "AS-8 produced no evaluation — the fixture does not reach the rule"
    result = evaluations[0]
    assert result.source_content_ids == ("s1", "s2"), (
        "the statements the recipe compared must reach `source_content_ids` — the ONLY field "
        f"`_source_document_ids` reads, and therefore the only one a processor sees. Got "
        f"{result.source_content_ids}"
    )


def test_the_statements_reach_the_evaluation_that_becomes_the_finding() -> None:
    """LP-647 §1 review — THE LAYER THE DEFECT IS ACTUALLY SEEN AT, one further out again.

    Asserting the tag's `source_facts` proved the recipe's ids survived `produce_derived_tags`. It did
    NOT prove they reach a processor: a finding's document links come from `_source_document_ids`,
    which reads `result.source_content_ids` and nothing else, and only `consistency.py` was setting
    that field. So AS-8 carried its two statements in the provenance JSON and still rendered with no
    documents — the exact symptom §1 exists to fix, surviving §1's first version.

    That is the same reasoning as the last layer, applied once more: the tag carrying ids proves
    nothing if the FINDING is built from a different field. This asserts the field the finding is
    built from.
    """
    from app.verification.rule_engine.deterministic import _named_documents
    from app.verification.rule_engine.result import LoadBearingTag

    def _lb(tag_id: str, sources: tuple[str, ...]) -> LoadBearingTag:
        return LoadBearingTag(tag_id, "broken", None, "because", sources)

    named = _named_documents((_lb("stmt.continuity", ("s1", "s2")),))
    assert named == ("s1", "s2"), "what the recipe named must reach source_content_ids"

    # DEDUPED AND ORDER-PRESERVING across several tags: two tags naming the same statement produce
    # one link, and the order a processor reads them in is the order the rule declared.
    deduped = _named_documents(
        (_lb("stmt.continuity", ("s1", "s2")), _lb("stmt.min_account_months", ("s2", "s3")))
    )
    assert deduped == ("s1", "s2", "s3")

    # A TAG THAT NAMED NOTHING contributes nothing. The 77 untouched recipes fall back to their
    # subject, which for a loan-level rule is the string "loan" — it reaches here and is dropped
    # downstream by `document_id_by_content_id`, never written as a dangling link.
    assert _named_documents((_lb("dti.back_end", ("loan",)),)) == ("loan",)
    assert _named_documents(()) == ()
