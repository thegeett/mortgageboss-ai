"""The generic vocabulary-driven producers (LP-326) — production is a declaration, not per-family code.

Proves: parsed/derived/ai each materialize from a DECLARATION only; the txn.* round-trip equivalence
(the generic AI producer reproduces the legacy Stage-A tags); the LP-325 gather contract (an address
tag and its type co-located on the same document subject → ID-4's residence filter works end to end);
ID-2 end to end; the fail-loud loader; and that NO per-family branch exists in the producers.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from app.ai.tag_production import StageAResult, TagJudgment, TransactionJudgment
from app.services.tag_production import produce_stage_a_transaction_tags
from app.verification.rule_engine.consistency import evaluate_consistency_rule
from app.verification.rule_engine.result import Verdict
from app.verification.rules.specs import load_rule_spec
from app.verification.snapshot.fields import Field, FieldSource
from app.verification.snapshot.model import (
    BorrowerRef,
    DocumentEntry,
    DocumentsSection,
    MismoSection,
    Snapshot,
    TagsSection,
    TransactionRecord,
)
from app.verification.snapshot.pii import PiiField, PiiKind
from app.verification.snapshot.tag import TagProducedBy
from app.verification.tag_materialization.ai import (
    AiGroupResult,
    AiSubjectJudgment,
    AiTagJudgment,
    produce_ai_group_tags,
)
from app.verification.tag_materialization.declarations import (
    AiGroup,
    DeclarationError,
    ProductionMode,
    TagDeclaration,
    load_ai_groups,
    load_declarations,
)
from app.verification.tag_materialization.derived import produce_derived_tags
from app.verification.tag_materialization.parsed import produce_parsed_tag
from app.verification.tag_materialization.producer import materialize_tags
from app.verification.tag_materialization.subjects import subject_type

pytestmark = pytest.mark.anyio

_LF = uuid4()


def _field(value: object) -> Field:
    return Field.present(value, source=FieldSource.EXTRACTED)


def _txn(cid: str, *, amount: str = "50.00", desc: str = "PAYROLL") -> TransactionRecord:
    return TransactionRecord(
        content_id=cid,
        date=_field("2026-05-01"),
        amount=_field(amount),
        direction=_field("credit"),
        description=_field(desc),
    )


def _doc(cid: str, *, fields: dict[str, object] | None = None, borrower=None) -> DocumentEntry:
    built = {
        k: (v if isinstance(v, (Field, PiiField)) else _field(v)) for k, v in (fields or {}).items()
    }
    return DocumentEntry(
        content_id=cid,
        document_type="doc",
        belongs_to=((BorrowerRef(borrower_id=borrower, name="Sam"),) if borrower else None),
        fields=built,
    )


def _snapshot(*, docs=None, txns=None, mismo=None) -> Snapshot:
    entries = list(docs or [])
    if txns:
        entries.append(
            DocumentEntry(
                content_id="stmt", document_type="bank_statement", transactions=tuple(txns)
            )
        )
    return Snapshot(
        loan_file_id=_LF,
        run_id=uuid4(),
        created_at=datetime(2026, 7, 15, tzinfo=UTC),
        documents=DocumentsSection.present(entries) if entries else DocumentsSection.present([]),
        mismo=MismoSection.present(mismo or {}) if mismo is not None else MismoSection.present({}),
        tags=TagsSection.present({}),
    )


# --------------------------------------------------------------------------- #
# parsed — map an extraction field; absent → absent tag; never AI-re-typed
# --------------------------------------------------------------------------- #
def test_parsed_maps_the_declared_field_produced_by_parsed_no_confidence() -> None:
    decl = TagDeclaration("id.dob", ProductionMode.PARSED, "document", "dob", None)
    doc = _doc("d1", fields={"dob": "1985-03-04"})
    tag = produce_parsed_tag(decl, "d1", subject_type("document").read_field(doc, "dob"))
    assert tag is not None
    assert tag.value == "1985-03-04"
    assert tag.produced_by is TagProducedBy.PARSED and tag.confidence is None
    assert tag.source_facts == ("d1",)


def test_parsed_absent_field_is_an_absent_tag_never_fabricated() -> None:
    decl = TagDeclaration("id.dob", ProductionMode.PARSED, "document", "dob", None)
    doc = _doc("d1", fields={})  # no dob field
    assert produce_parsed_tag(decl, "d1", subject_type("document").read_field(doc, "dob")) is None


def test_parsed_hash_reads_match_hash_and_nonmatchable_is_absent() -> None:
    decl = TagDeclaration("id.ssn_hash", ProductionMode.PARSED, "document", "ssn:hash", None)
    ssn = PiiField.from_raw(
        "123-45-6789", kind=PiiKind.SSN, loan_file_id=_LF, source=FieldSource.EXTRACTED
    )
    tag = produce_parsed_tag(decl, "d1", ssn)
    assert tag is not None and tag.value == ssn.match_hash and tag.value is not None
    # A non-matchable (blank) SSN → the tag is ABSENT (so a gather excludes it, never a null match).
    blank = PiiField.from_raw("", kind=PiiKind.SSN, loan_file_id=_LF, source=FieldSource.EXTRACTED)
    assert produce_parsed_tag(decl, "d1", blank) is None


# --------------------------------------------------------------------------- #
# derived — a deterministic recipe
# --------------------------------------------------------------------------- #
def test_derived_recipe_complete_vs_incomplete_vs_absent() -> None:
    decl = load_declarations()["id.app_required_fields_present"]
    complete = _snapshot(
        mismo={
            k: _field("x")
            for k in ("borrower.1.name", "borrower.1.ssn", "loan.amount", "property.address")
        }
    )
    out = produce_derived_tags(decl, complete)
    assert out["loan"]["id.app_required_fields_present"].value == "complete"

    incomplete = _snapshot(mismo={"borrower.1.name": _field("x")})
    out = produce_derived_tags(decl, incomplete)
    assert out["loan"]["id.app_required_fields_present"].value == "incomplete + list"
    assert out["loan"]["id.app_required_fields_present"].produced_by is TagProducedBy.DERIVED

    absent = Snapshot(
        loan_file_id=_LF,
        run_id=uuid4(),
        created_at=datetime(2026, 7, 15, tzinfo=UTC),
        mismo=MismoSection.missing(),
    )
    out = produce_derived_tags(decl, absent)
    assert out["loan"]["id.app_required_fields_present"].value == "unknown"


# --------------------------------------------------------------------------- #
# ai — the generic producer (reuses the LP-313 machinery)
# --------------------------------------------------------------------------- #
class _AiStub:
    def __init__(
        self, by_short: dict[str, tuple[str, float | None]], *, truncated=False, malformed=False
    ):
        self.by_short = by_short
        self.truncated = truncated
        self.malformed = malformed
        self.calls = 0
        self.contexts: list[str] = []

    async def __call__(self, context_json: str) -> AiGroupResult:
        self.calls += 1
        self.contexts.append(context_json)
        subjects = json.loads(context_json)["subjects"]
        judgments = []
        for s in subjects:
            if self.malformed:
                tags: dict[str, AiTagJudgment | None] = dict.fromkeys(self.by_short)
            else:
                tags = {k: AiTagJudgment(v, c, "because") for k, (v, c) in self.by_short.items()}
            judgments.append(AiSubjectJudgment(index=int(s["index"]), tags=tags))
        return AiGroupResult(judgments, 1, 1, "stub", self.truncated)


async def test_ai_group_co_locates_its_tags_on_one_subject_lp325() -> None:
    # THE LP-325 GATHER CONTRACT: a document stating an address carries BOTH id.address_normalized AND
    # id.current_address_type on the SAME subject.
    group = load_ai_groups()["id_address"]
    doc = _doc("d1", fields={"address": "123 Main St"})
    snap = _snapshot(docs=[doc])
    stub = _AiStub(
        {
            "address_normalized": ("123 Main Street", 0.9),
            "current_address_type": ("residence", 0.95),
        }
    )
    out = await produce_ai_group_tags(
        snap,
        group,
        {t: load_declarations()[t].allowed_values for t in group.tag_ids},
        reasoner=stub,
    )
    assert set(out["d1"]) == {"id.address_normalized", "id.current_address_type"}
    assert out["d1"]["id.address_normalized"].value == "123 Main Street"
    assert out["d1"]["id.current_address_type"].value == "residence"
    assert out["d1"]["id.address_normalized"].source_facts == ("d1",)
    assert out["d1"]["id.address_normalized"].produced_by is TagProducedBy.AI


async def test_ai_off_domain_and_malformed_are_unknown_never_defaulted() -> None:
    group = load_ai_groups()["id_address"]
    snap = _snapshot(docs=[_doc("d1", fields={"address": "x"})])
    allowed = {t: load_declarations()[t].allowed_values for t in group.tag_ids}
    # An off-vocabulary current_address_type → coerced to unknown (never accepted verbatim).
    off = _AiStub({"address_normalized": ("A", 0.9), "current_address_type": ("garage", 0.9)})
    out = await produce_ai_group_tags(snap, group, allowed, reasoner=off)
    assert out["d1"]["id.current_address_type"].value == "unknown"
    assert out["d1"]["id.current_address_type"].confidence is None  # fail-closed marker
    # A malformed judgment → unknown-with-reason.
    bad = _AiStub(
        {"address_normalized": ("", None), "current_address_type": ("", None)}, malformed=True
    )
    out = await produce_ai_group_tags(snap, group, allowed, reasoner=bad)
    assert out["d1"]["id.address_normalized"].value == "unknown"


async def test_ai_caches_by_content_fingerprint() -> None:
    group = load_ai_groups()["id_name"]
    snap = _snapshot(docs=[_doc("d1", fields={"name": "Sam"}), _doc("d2", fields={"name": "Sam"})])
    allowed = {t: load_declarations()[t].allowed_values for t in group.tag_ids}
    stub = _AiStub({"name_normalized": ("Sam", 0.9)})
    cache: dict[str, dict[str, object]] = {}
    await produce_ai_group_tags(snap, group, allowed, reasoner=stub, cache=cache)  # type: ignore[arg-type]
    first = stub.calls
    # Re-run with the SAME content → a cache hit; the reasoner is not called again.
    await produce_ai_group_tags(snap, group, allowed, reasoner=stub, cache=cache)  # type: ignore[arg-type]
    assert stub.calls == first  # identical content reused across the re-run


# --------------------------------------------------------------------------- #
# txn.* round-trip EQUIVALENCE — the generic AI producer reproduces the legacy Stage-A tags
# --------------------------------------------------------------------------- #
class _LegacyStageAStub:
    async def __call__(self, context_json: str) -> StageAResult:
        n = len(json.loads(context_json)["transactions"])
        return StageAResult(
            [
                TransactionJudgment(
                    index=i,
                    is_money_in=TagJudgment("in", 0.9, "because"),
                    apparent_category=TagJudgment("payroll", 0.8, "because"),
                )
                for i in range(1, n + 1)
            ],
            1,
            1,
            "stub",
            False,
        )


async def test_txn_roundtrip_through_the_generic_producer_is_equivalent() -> None:
    snap = _snapshot(txns=[_txn("t1"), _txn("t2", amount="99.00", desc="RENT")])

    legacy = await produce_stage_a_transaction_tags(snap, reasoner=_LegacyStageAStub())

    stub = _AiStub({"is_money_in": ("in", 0.9), "apparent_category": ("payroll", 0.8)})
    generic = await materialize_tags(
        snap, ai_reasoners={"txn_stage_a": stub}, only_subjects=frozenset({"transaction"})
    )

    for cid in ("t1", "t2"):
        for tag_id in ("txn.amount", "txn.date", "txn.is_money_in", "txn.apparent_category"):
            lt = legacy.tags.by_subject[cid][tag_id]
            gt = generic.tags.by_subject[cid][tag_id]
            assert (
                gt.value,
                gt.confidence,
                gt.reasoning,
                gt.produced_by,
                gt.source_facts,
                gt.stage,
            ) == (
                lt.value,
                lt.confidence,
                lt.reasoning,
                lt.produced_by,
                lt.source_facts,
                lt.stage,
            ), f"{cid}:{tag_id} diverged"


# --------------------------------------------------------------------------- #
# End to end via declarations only: materialize id.* → ID-4 residence filter + ID-2
# --------------------------------------------------------------------------- #
def _residence_stub(addr_by_doc: dict[str, tuple[str, str]]):
    """A reasoner that returns a per-document address+type from a {doc_desc: (addr, type)} map."""

    async def _call(context_json: str) -> AiGroupResult:
        subjects = json.loads(context_json)["subjects"]
        js = []
        for s in subjects:
            addr, kind = addr_by_doc[str(s.get("addr_key"))]
            js.append(
                AiSubjectJudgment(
                    index=int(s["index"]),
                    tags={
                        "address_normalized": AiTagJudgment(addr, 0.9, "x"),
                        "current_address_type": AiTagJudgment(kind, 0.95, "x"),
                    },
                )
            )
        return AiGroupResult(js, 1, 1, "stub", False)

    return _call


async def test_id4_residence_filter_works_end_to_end_from_materialized_tags() -> None:
    b = uuid4()
    docs = [
        _doc("app", fields={"addr_key": "app", "address": "123 N Main St"}, borrower=b),
        _doc("dl", fields={"addr_key": "dl", "address": "123 North Main Street"}, borrower=b),
        _doc("mail", fields={"addr_key": "mail", "address": "PO Box 9"}, borrower=b),
    ]
    snap = _snapshot(docs=docs)
    addr = {
        "app": ("123 N Main St", "residence"),
        "dl": ("123 North Main Street", "residence"),
        "mail": ("PO Box 9", "mailing"),
    }
    snap = await materialize_tags(
        snap,
        ai_reasoners={"id_address": _residence_stub(addr)},
        only_subjects=frozenset({"document"}),
        only_groups=frozenset({"id_address"}),
    )
    # Each doc carries BOTH tags co-located (the contract).
    assert set(snap.tags.by_subject["app"]) >= {"id.address_normalized", "id.current_address_type"}

    # ID-4: the two residence addresses are compared (mailing excluded); an AI stub judges them a match.
    async def _match(_ctx: str):
        from app.ai.rule_judgment import RuleJudgment, RuleJudgmentResult

        return RuleJudgmentResult(RuleJudgment("agree", 0.9, "same"), 1, 1, "stub", False)

    results = await evaluate_consistency_rule(load_rule_spec("ID-4"), snap, reasoner=_match)
    assert [r.verdict for r in results] == [Verdict.SATISFIED]


async def test_id4_mailing_only_borrower_is_couldnt_check_not_a_discrepancy() -> None:
    b = uuid4()
    docs = [
        _doc("app", fields={"addr_key": "app", "address": "123 N Main St"}, borrower=b),
        _doc("mail", fields={"addr_key": "mail", "address": "PO Box 9"}, borrower=b),
    ]
    snap = _snapshot(docs=docs)
    addr = {"app": ("123 N Main St", "residence"), "mail": ("PO Box 9", "mailing")}
    snap = await materialize_tags(
        snap,
        ai_reasoners={"id_address": _residence_stub(addr)},
        only_subjects=frozenset({"document"}),
        only_groups=frozenset({"id_address"}),
    )
    results = await evaluate_consistency_rule(load_rule_spec("ID-4"), snap)  # no AI needed
    assert [r.verdict for r in results] == [
        Verdict.COULDNT_CHECK
    ]  # <2 residence → nothing to compare


async def test_id2_end_to_end_from_parsed_ssn_hashes() -> None:
    b = uuid4()

    def ssn_doc(cid: str, ssn: str | None) -> DocumentEntry:
        pii = (
            PiiField.from_raw(ssn, kind=PiiKind.SSN, loan_file_id=_LF, source=FieldSource.EXTRACTED)
            if ssn is not None
            else PiiField.missing()
        )
        return _doc(cid, fields={"ssn": pii}, borrower=b)

    # Two docs, same SSN → matching hashes → satisfied.
    snap = await materialize_tags(
        _snapshot(docs=[ssn_doc("app", "111-22-3333"), ssn_doc("cr", "111-22-3333")]),
        only_subjects=frozenset({"document"}),
        only_groups=frozenset(),
    )
    assert [r.verdict for r in await evaluate_consistency_rule(load_rule_spec("ID-2"), snap)] == [
        Verdict.SATISFIED
    ]

    # Different SSNs → differing hashes → fired.
    snap = await materialize_tags(
        _snapshot(docs=[ssn_doc("app", "111-22-3333"), ssn_doc("cr", "999-88-7777")]),
        only_subjects=frozenset({"document"}),
        only_groups=frozenset(),
    )
    assert [r.verdict for r in await evaluate_consistency_rule(load_rule_spec("ID-2"), snap)] == [
        Verdict.FIRED
    ]

    # One SSN absent → that source excluded; <2 remain → couldnt_check (never a false match).
    snap = await materialize_tags(
        _snapshot(docs=[ssn_doc("app", "111-22-3333"), ssn_doc("cr", None)]),
        only_subjects=frozenset({"document"}),
        only_groups=frozenset(),
    )
    assert [r.verdict for r in await evaluate_consistency_rule(load_rule_spec("ID-2"), snap)] == [
        Verdict.COULDNT_CHECK
    ]


# --------------------------------------------------------------------------- #
# Declaration-driven: a BRAND-NEW tag materializes from a declaration only (no new Python)
# --------------------------------------------------------------------------- #
async def test_a_new_ai_tag_materializes_from_a_declaration_only() -> None:
    # A synthetic group + declaration the producer has never seen — it runs with ZERO new Python.
    group = AiGroup("synth", "document", "document", ("x.flavor",), "prompt")
    snap = _snapshot(docs=[_doc("d1", fields={"flavor": "vanilla"})])
    stub = _AiStub({"flavor": ("vanilla", 0.9)})
    out = await produce_ai_group_tags(snap, group, {"x.flavor": None}, reasoner=stub)
    assert (
        out["d1"]["x.flavor"].value == "vanilla"
    )  # a free-string tag (no allowed set) accepted verbatim


# --------------------------------------------------------------------------- #
# The loader FAILS LOUD on an invalid declaration (no silently-unproducible tag)
# --------------------------------------------------------------------------- #
def test_loader_fails_loud_on_invalid_declaration(tmp_path, monkeypatch) -> None:
    import app.verification.tag_materialization.declarations as d

    bad = tmp_path / "tag_production.yaml"
    bad.write_text(
        "tags:\n  x.foo: {mode: derived, subject: loan, data: no_such_recipe}\nai_groups: {}\n"
    )
    monkeypatch.setattr(d, "_PRODUCTION_YAML", bad)
    d._production_doc.cache_clear()
    d.load_declarations.cache_clear()
    monkeypatch.setattr(d, "_allowed_values_by_tag", lambda: {"x.foo": None})
    from app.verification.tag_materialization.derived import KNOWN_RECIPES
    from app.verification.tag_materialization.subjects import KNOWN_CONTEXT_BUILDERS

    with pytest.raises(DeclarationError, match="unknown derived recipe"):
        d.validate_declarations(
            known_recipes=KNOWN_RECIPES, known_context_builders=KNOWN_CONTEXT_BUILDERS
        )
    d._production_doc.cache_clear()
    d.load_declarations.cache_clear()


def test_derived_declaration_accepts_a_non_loan_subject(tmp_path, monkeypatch) -> None:
    # LP-332 generalized derived production to the declared subject (the producer enumerates the subject
    # registry, like parsed/ai), so a non-loan derived subject is now VALID — no longer rejected at load.
    import app.verification.tag_materialization.declarations as d

    ok = tmp_path / "tag_production.yaml"
    ok.write_text(
        "tags:\n"
        "  x.foo: {mode: derived, subject: borrower, data: app_required_fields_present}\n"
        "ai_groups: {}\n"
    )
    monkeypatch.setattr(d, "_PRODUCTION_YAML", ok)
    d._production_doc.cache_clear()
    d.load_declarations.cache_clear()
    monkeypatch.setattr(d, "_allowed_values_by_tag", lambda: {"x.foo": None})
    from app.verification.tag_materialization.derived import KNOWN_RECIPES
    from app.verification.tag_materialization.subjects import KNOWN_CONTEXT_BUILDERS

    d.validate_declarations(  # no raise — a borrower-subject derived tag is valid now
        known_recipes=KNOWN_RECIPES, known_context_builders=KNOWN_CONTEXT_BUILDERS
    )
    d._production_doc.cache_clear()
    d.load_declarations.cache_clear()


def test_derived_declaration_on_a_per_row_subject_fails_loud(tmp_path, monkeypatch) -> None:
    # LP-332 generalized derived production, but the recipes are written only for the loan / borrower
    # subjects. A derived tag declared on a per-row subject (document/transaction) would run a
    # loan/borrower recipe against the wrong raw object and silently mis-key garbage — reject it at load.
    import app.verification.tag_materialization.declarations as d

    bad = tmp_path / "tag_production.yaml"
    bad.write_text(
        "tags:\n"
        "  x.foo: {mode: derived, subject: document, data: app_required_fields_present}\n"
        "ai_groups: {}\n"
    )
    monkeypatch.setattr(d, "_PRODUCTION_YAML", bad)
    d._production_doc.cache_clear()
    d.load_declarations.cache_clear()
    monkeypatch.setattr(d, "_allowed_values_by_tag", lambda: {"x.foo": None})
    from app.verification.tag_materialization.derived import KNOWN_RECIPES
    from app.verification.tag_materialization.subjects import KNOWN_CONTEXT_BUILDERS

    with pytest.raises(DeclarationError, match="derived subject 'document' is not supported"):
        d.validate_declarations(
            known_recipes=KNOWN_RECIPES, known_context_builders=KNOWN_CONTEXT_BUILDERS
        )
    d._production_doc.cache_clear()
    d.load_declarations.cache_clear()


# --------------------------------------------------------------------------- #
# NO per-family Python — the producers carry no id.*-specific branch
# --------------------------------------------------------------------------- #
def test_producers_have_no_per_family_branches() -> None:
    pkg = Path(__file__).parents[3] / "app" / "verification" / "tag_materialization"
    for py in pkg.glob("*.py"):
        for line in py.read_text().splitlines():
            code = line.split("#", 1)[0]  # ignore comments
            assert 'startswith("id' not in code, f"per-family branch in {py.name}: {line}"
            assert '== "id.' not in code, f"per-family branch in {py.name}: {line}"
            assert 'startswith("txn' not in code, f"per-family branch in {py.name}: {line}"
