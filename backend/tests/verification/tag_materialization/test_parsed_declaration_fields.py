"""The parsed-declaration field guard (LP-369, EXTENDED to MISMO by LP-450) — a declaration must name a
field that EXISTS.

THE BUG CLASS (found four times): a declaration names something that doesn't exist → the thing is
ABSENT → the rule couldnt_checks on every file → silently, forever, with every test green. AS-1 read
income through a calc gated on an unused input (LP-366); IN-8/IN-9 named document types the classifier
doesn't emit (LP-333); `housing.insurance_monthly` was declared `producer=AI` with no producer (LP-367);
and parsed tags named extraction fields that don't exist — `id.dob` read `dob` (it is `date_of_birth`),
`id.ssn_hash` read `ssn` (it is `employee_ssn`) — silently killing LIVE rules ID-3 and ID-2 (LP-368/369).
This is the IH-1 shape: the value existed, the link was broken, nobody knew for months.

THE ROOT: the loader validates declarations that EXIST; it does not validate that what they POINT AT
exists. A declared key with no member resolves to ABSENT, and absent is indistinguishable from "the
document genuinely doesn't have this" — so it is silent.

THE GUARD (this test): for every `mode: parsed` declaration, the field it reads MUST be a real member of
the resolution universe its `subject` reads from:
  * ``subject: document``  → an extraction model's field name (``DocumentEntry.fields`` keys; see
    ``build_document_fields``), or the ``asserted_name`` alias.
  * ``subject: transaction`` → a ``_TXN_FIELDS`` key.
  * ``subject: loan`` → a MISMO fact KEY (``mismo.facts`` keys — ``loan.*`` / ``property.*`` / the
    file-level ``liability.{n}.*`` / ``asset.{n}.*``).
  * ``subject: borrower`` → the FIELD SUFFIX after ``borrower.{n}.`` (``_borrower_read_field`` reads
    ``borrower.{index}.<data>``) — ``first_name`` / ``citizenship`` / ``income.{n}.monthly_amount`` / …

LP-450 CLOSED THE MISMO HOLE. Before it, loan/borrower were SKIPPED (data-dependent, "not statically
checkable") — a silent gap on exactly the subjects a large tag phase (step D) leans on. But the MISMO
key universe IS statically enumerable: ``build_mismo_section`` emits it from a FIXED set of ``put(key,…)``
calls, so this guard builds a fully-populated synthetic section (pure, no DB, no AI) and reads its keys.
RESIDUAL GAP (documented, not hidden): ``borrower.{n}.declaration.<slug>`` slugs come from a borrower's
free-form declarations JSON — DATA-DEPENDENT, so a ``declaration.*`` reference is accepted by prefix and
its slug is NOT validated. That is the one edge this guard cannot close.

THE OTHER TWO MODES are guarded at LOAD (``declarations.validate_declarations``, called by the projection
loader): a ``derived`` tag's ``data`` must be a key in ``_RECIPES``; an ``ai`` tag's group must exist and
LIST the tag. So field-legality is guarded for EVERY mode — derived/ai at load (their universes are
in-layer), parsed field-existence HERE (this test).

WHY A TEST, NOT A LOAD-TIME CHECK for the parsed modes: the authoritative universes live in
``app.ai.extraction.*`` (the AI models) and ``app.models.*`` + ``mismo_section`` (the ORM + its mapping).
A load-time check would force the deterministic tag-vocabulary loader (``declarations.py``) to import the
AI/ORM layers and construct a synthetic section at load — a layering inversion the LP-369 reasoning
already rejected. Keeping the parsed check in the test layer fails CI just as loudly. (derived/ai stay at
load because THEIR universes are already in ``declarations``' own layer — no inversion.)

The ``:``-suffix (``employee_ssn:hash``) is split off before the field lookup (``producer.py``), so the
guard checks the part before the colon.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
import re
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import app.ai.extraction as extraction_pkg
from app.verification.snapshot.mismo_section import build_mismo_section
from app.verification.tag_materialization.declarations import (
    ProductionMode,
    TagDeclaration,
    load_declarations,
)
from app.verification.tag_materialization.subjects import _LIABILITY_FIELD_ALIASES, _TXN_FIELDS
from pydantic import BaseModel

# Declarations whose field genuinely has NO producer today — a KNOWN missing-extraction gap, not a
# typo, and their consuming rules are DORMANT (not in ACTIVE_RULE_IDS). Exempted LOUDLY (here, with a
# reason) rather than silently — the guard still fails on any NEW mismatch. Each must remain a genuine
# mismatch (asserted below) so the exemption cannot rot into hiding a now-resolvable declaration.
_KNOWN_UNPRODUCIBLE: dict[str, str] = {
    # stated income is MISMO-indexed (borrower.{n}.income.{m}.monthly_amount), not a document field —
    # it needs a DERIVED/borrower source (cf. dti.qualifying_income_monthly). IN-1 / DT-1 dormant.
    "income.stated_monthly": "stated income is MISMO-indexed, not a document field (needs a derived source)",
    # LP-381: stmt.page_count_declared / page_count_present are now emitted by bank_statement.py (the printed
    # "of N" + the deterministic PDF page total) — the exemption is REMOVED (the field resolves for AS-9).
}


def _document_field_universe() -> set[str]:
    """Every field name an extraction model can emit (the ``DocumentEntry.fields`` key space), plus the
    ``asserted_name`` alias that ``build_document_fields`` synthesizes."""
    fields: set[str] = {"asserted_name"}
    for mod_info in pkgutil.iter_modules(extraction_pkg.__path__):
        module = importlib.import_module(f"{extraction_pkg.__name__}.{mod_info.name}")
        for _name, obj in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(obj, BaseModel)
                and obj.__name__.endswith("Extraction")
                and obj.__module__ == module.__name__
            ):
                fields |= set(obj.model_fields.keys())
    return fields


_INDEX_RE = re.compile(
    r"\.\d+\."
)  # a MISMO collection index (borrower.1., income.2., liability.3., …)


def _norm_index(key: str) -> str:
    """Normalise a MISMO collection index to ``.{n}.`` so ``income.1.monthly_amount`` (the synthetic
    universe, always index 1) matches a declaration reading ``income.5.monthly_amount``."""
    return _INDEX_RE.sub(".{n}.", key)


def _mismo_field_universe() -> tuple[frozenset[str], frozenset[str]]:
    """The legal MISMO reference universe, built from ``build_mismo_section``'s OWN ``put(key,…)`` mapping
    (the source of truth — can't drift) over a fully-populated synthetic section. Pure: transient
    ``SimpleNamespace`` rows, no DB, no session, no AI. Returns ``(loan_keys, borrower_suffixes)``, both
    index-normalised: ``loan_keys`` are the non-borrower keys a ``subject: loan`` tag reads whole;
    ``borrower_suffixes`` are the parts after ``borrower.{n}.`` a ``subject: borrower`` tag reads.

    ``declaration.<slug>`` is DROPPED from the suffixes — its slug is data-dependent (a borrower's
    free-form declarations JSON), so it is handled by prefix in :func:`_resolves`, the documented residual."""
    ns = SimpleNamespace
    inc = ns(
        id=uuid4(),
        is_deleted=False,
        monthly_amount=Decimal("1"),
        income_type="W2",
        employment_income=True,
    )
    # LP-624 — the stub carries the whole employment record now, because the section publishes it.
    emp = ns(
        id=uuid4(),
        is_deleted=False,
        employer_name="e",
        is_current=True,
        self_employed=False,
        classification="Primary",
        position="Product Manager",
        start_date=None,
        end_date=None,
        monthly_income=None,
        special_relationship=False,
    )
    bor = ns(
        id=uuid4(), is_deleted=False, borrower_position=1, first_name="f", middle_name="m", last_name="l",
        date_of_birth=date(1990, 1, 1), marital_status="Married", is_primary=True, dependent_count=0,
        citizenship="USCitizen", ssn="123-45-6789", stated_income_items=[inc], stated_employers=[emp],
        declarations={"Bankruptcy": "No"},
    )  # fmt: skip
    lf = ns(
        id=uuid4(), loan_program="Conventional", loan_purpose="Purchase", refinance_type="CashOut",
        loan_amount=Decimal("1"), note_amount=Decimal("1"), note_rate_percent=Decimal("1"),
        amortization_type="Fixed", amortization_months=360,
        application_received_date=date(2026, 6, 8),  # LP-494 — CO-4's date-keyed reserve floor
    )  # fmt: skip
    prop = ns(
        address_line="a", address_line_2="b", city="c", state="ST", postal_code="00000",
        property_type="SFR", occupancy_type="Primary", estimated_value=Decimal("1"),
        purchase_price=Decimal("1"), valuation_amount=Decimal("1"), attachment_type="Detached",
        construction_method="SiteBuilt", financed_unit_count=1,
        in_project=False, is_pud=False,  # LP-509-B1
    )  # fmt: skip
    liab = ns(
        id=uuid4(),
        is_deleted=False,
        liability_type="Revolving",
        monthly_payment=Decimal("1"),
        unpaid_balance=Decimal("1"),
        holder_name="h",
        paid_off_at_closing=None,  # LP-572 — projected, but not part of the identity hash
    )
    asset = ns(
        id=uuid4(), is_deleted=False, asset_type="Checking", value=Decimal("1"), holder_name="h"
    )
    # build_mismo_section only READS attributes (it is pure, no ORM behaviour), so duck-typed
    # SimpleNamespace rows drive the real mapping without the DB/session a real ORM row would need.
    # LP-596 — every field must be POPULATED: `put` omits a NULL, so a row of Nones would leave the
    # owned-property keys out of the universe this test exists to enumerate.
    owned = ns(
        id=uuid4(),
        is_deleted=False,
        is_subject=False,
        disposition_status="Retain",
        lien_upb=Decimal("1"),
        unit_count=1,
        rental_income_gross=Decimal("1"),
        rental_income_net=Decimal("1"),
        current_usage_type="Investment",
        usage_type="Investment",
        estimated_value=Decimal("1"),
    )
    facts = build_mismo_section(
        loan_file=lf,  # type: ignore[arg-type]
        borrowers=[bor],  # type: ignore[list-item]
        property_=prop,  # type: ignore[arg-type]
        liabilities=[liab],  # type: ignore[list-item]
        assets=[asset],  # type: ignore[list-item]
        owned_properties=[owned],  # type: ignore[list-item]
    )
    loan_keys, borrower_suffixes = set(), set()
    for key in facts:
        m = re.match(r"borrower\.\d+\.(.+)$", key)
        if m is None:
            loan_keys.add(_norm_index(key))
        elif not m.group(1).startswith("declaration."):  # slug is data-dependent → prefix-handled
            borrower_suffixes.add(_norm_index(m.group(1)))
    return frozenset(loan_keys), frozenset(borrower_suffixes)


_MISMO_LOAN_KEYS, _MISMO_BORROWER_SUFFIXES = _mismo_field_universe()


def _field_name(decl: TagDeclaration) -> str:
    """The field the parsed producer looks up — the ``data`` key with any ``:suffix`` (e.g. ``:hash``)
    stripped, mirroring ``producer.py``'s ``decl.data.split(':', 1)[0]``."""
    return decl.data.split(":", 1)[0]


def _resolves(decl: TagDeclaration, doc_fields: set[str]) -> bool:
    """Whether the declaration's field is a LEGAL reference in the universe its subject reads — legality,
    NOT presence (a legal field absent on a given file is the normal couldnt_check path, never a violation).

    LP-450 closes loan/borrower (MISMO) against ``build_mismo_section``'s key vocabulary. A borrower
    ``declaration.<slug>`` reference is accepted by prefix — its slug is data-dependent (the residual gap)."""
    field = _field_name(decl)
    if decl.subject == "document":
        return field in doc_fields
    if decl.subject == "transaction":
        return field in _TXN_FIELDS
    if decl.subject == "loan":
        return _norm_index(field) in _MISMO_LOAN_KEYS
    if decl.subject == "borrower":
        if field.startswith("declaration."):
            return (
                True  # data-dependent slug — the documented residual gap (cannot validate the slug)
            )
        return _norm_index(field) in _MISMO_BORROWER_SUFFIXES
    if decl.subject == "liability":
        # LP-483 — the canonical names the liability family's alias map resolves, for EITHER source. A
        # name only one source carries is legal (the other leg yields an absent tag — the normal
        # couldnt_check path); a name NEITHER carries is the typo this guard exists to catch.
        return field in {name for aliases in _LIABILITY_FIELD_ALIASES.values() for name in aliases}
    return True  # an unknown subject is out of this guard's scope


def _parsed_declarations() -> list[tuple[str, TagDeclaration]]:
    return [
        (tag_id, decl)
        for tag_id, decl in load_declarations().items()
        if decl.mode is ProductionMode.PARSED
    ]


# --------------------------------------------------------------------------- #
# D5 — the error: it must name the tag, the bad reference, and the nearest legal matches (typo-obvious)
# --------------------------------------------------------------------------- #
def _legal_universe(decl: TagDeclaration, doc_fields: set[str]) -> tuple[str, set[str]]:
    """(a human name for the universe, the legal reference set) for a parsed declaration's subject."""
    if decl.subject == "document":
        return "extraction field", doc_fields
    if decl.subject == "transaction":
        return "txn field", set(_TXN_FIELDS)
    if decl.subject == "loan":
        return "MISMO loan fact", set(_MISMO_LOAN_KEYS)
    if decl.subject == "borrower":
        return "MISMO borrower field", set(_MISMO_BORROWER_SUFFIXES)
    if decl.subject == "liability":
        # LP-483 review: ``_resolves`` gained a liability branch and this did not, so a typo'd liability
        # declaration failed with an EMPTY universe and "no close reference match" — losing exactly the
        # nearest-legal-name hint this D5 section exists to give.
        return "liability field", {
            name for aliases in _LIABILITY_FIELD_ALIASES.values() for name in aliases
        }
    return "reference", set()


def _violation(tag_id: str, decl: TagDeclaration, doc_fields: set[str]) -> str:
    import difflib

    name, universe = _legal_universe(decl, doc_fields)
    field = _norm_index(_field_name(decl))
    nearest = difflib.get_close_matches(field, sorted(universe), n=3, cutoff=0.5)
    hint = f"; nearest legal {name}s: {nearest}" if nearest else f" (no close {name} match)"
    return f"{tag_id} {{subject: {decl.subject}, data: {decl.data!r}}} → {field!r} is not a legal {name}{hint}"


# --------------------------------------------------------------------------- #
# THE GUARD — every parsed declaration (document / transaction / loan / borrower) names a real field
# --------------------------------------------------------------------------- #
def test_every_parsed_declaration_names_a_real_field() -> None:
    doc_fields = _document_field_universe()
    violations = [
        _violation(tag_id, decl, doc_fields)
        for tag_id, decl in _parsed_declarations()
        if not _resolves(decl, doc_fields) and tag_id not in _KNOWN_UNPRODUCIBLE
    ]
    assert not violations, (
        "parsed declaration(s) name a field that cannot exist → the tag is ABSENT and its rule "
        "couldnt_checks silently on every file (the LP-369 / IH-1 bug class):\n  "
        + "\n  ".join(violations)
    )


def test_transaction_declarations_name_real_txn_fields() -> None:
    for tag_id, decl in _parsed_declarations():
        if decl.subject == "transaction":
            assert _field_name(decl) in _TXN_FIELDS, (
                f"{tag_id} reads unknown txn field {decl.data!r}"
            )


# --------------------------------------------------------------------------- #
# The guard actually FIRES — a guard that cannot fail is not a guard
# --------------------------------------------------------------------------- #
def test_guard_fires_on_a_synthetic_bad_declaration() -> None:
    doc_fields = _document_field_universe()
    # The exact pre-fix bug: id.dob read a document field 'dob' that no extractor emits.
    bad = TagDeclaration(
        tag_id="id.dob",
        mode=ProductionMode.PARSED,
        subject="document",
        data="dob",
        allowed_values=None,
    )
    assert not _resolves(bad, doc_fields)  # the guard would flag it
    # And the corrected form resolves.
    good = TagDeclaration(
        tag_id="id.dob",
        mode=ProductionMode.PARSED,
        subject="document",
        data="date_of_birth",
        allowed_values=None,
    )
    assert _resolves(good, doc_fields)


def test_hash_suffix_is_stripped_before_the_field_check() -> None:
    doc_fields = _document_field_universe()
    good = TagDeclaration(
        tag_id="id.ssn_hash",
        mode=ProductionMode.PARSED,
        subject="document",
        data="employee_ssn:hash",
        allowed_values=None,
    )
    assert _resolves(good, doc_fields)  # 'employee_ssn' is real; the ':hash' suffix is stripped
    bad = TagDeclaration(
        tag_id="id.ssn_hash",
        mode=ProductionMode.PARSED,
        subject="document",
        data="ssn:hash",
        allowed_values=None,
    )
    assert not _resolves(bad, doc_fields)  # 'ssn' is not a real field (it is 'employee_ssn')


# --------------------------------------------------------------------------- #
# LP-450 — the MISMO (loan / borrower) extension: the guard fires per mode, and the residual is honest
# --------------------------------------------------------------------------- #
def _decl(subject: str, data: str) -> TagDeclaration:
    return TagDeclaration(
        tag_id="x.test", mode=ProductionMode.PARSED, subject=subject, data=data, allowed_values=None
    )


def test_guard_fires_on_a_bad_loan_reference() -> None:
    doc_fields = _document_field_universe()
    assert _resolves(_decl("loan", "loan.program"), doc_fields)  # a real MISMO loan key
    assert _resolves(_decl("loan", "property.purchase_price"), doc_fields)  # a real property key
    # A typo no put() emits — the guard flags it (before LP-450 this resolved silently to absent).
    assert not _resolves(_decl("loan", "loan.programme"), doc_fields)
    assert not _resolves(_decl("loan", "property.purchse_price"), doc_fields)


def test_guard_fires_on_a_bad_borrower_reference() -> None:
    doc_fields = _document_field_universe()
    assert _resolves(_decl("borrower", "marital_status"), doc_fields)  # a real borrower.{n}.<field>
    assert _resolves(_decl("borrower", "citizenship"), doc_fields)
    assert _resolves(_decl("borrower", "income.1.monthly_amount"), doc_fields)  # index-normalised
    # A typo (the borrower producer would read borrower.{n}.maritalstatus → absent → couldnt_check).
    assert not _resolves(_decl("borrower", "maritalstatus"), doc_fields)
    assert not _resolves(_decl("borrower", "citzenship"), doc_fields)


def test_legal_but_absent_mismo_field_does_not_fail__legality_not_presence() -> None:
    # D4 — the guard checks LEGALITY, not PRESENCE. `middle_name` is a legal MISMO borrower field even for a
    # borrower who has none (absent on that file → the normal couldnt_check path). It MUST pass the guard —
    # a check that failed on a legal-but-absent field would be the wrong check.
    doc_fields = _document_field_universe()
    assert _resolves(_decl("borrower", "middle_name"), doc_fields)
    assert _resolves(
        _decl("loan", "loan.refinance_type"), doc_fields
    )  # legal, absent on a purchase file


def test_declaration_slug_is_the_documented_residual_gap() -> None:
    # borrower.{n}.declaration.<slug> slugs are data-dependent (a borrower's free-form declarations JSON), so
    # a `declaration.*` reference is accepted by PREFIX and its slug is not validated — the one edge this
    # guard cannot close, documented rather than hidden.
    doc_fields = _document_field_universe()
    assert _resolves(_decl("borrower", "declaration.anything_at_all"), doc_fields)


def test_error_message_names_the_tag_the_bad_reference_and_nearest_matches() -> None:
    # D5 — a failure must make the typo obvious: the tag, the bad reference, and the nearest legal matches.
    doc_fields = _document_field_universe()
    msg = _violation("id.marital_status", _decl("borrower", "maritalstatus"), doc_fields)
    assert "id.marital_status" in msg  # the tag
    assert "maritalstatus" in msg  # the bad reference
    assert "marital_status" in msg  # the nearest legal field (difflib)
    assert "MISMO borrower field" in msg  # the universe named


def test_mismo_universe_is_enumerable_and_nonempty() -> None:
    # The whole basis of the LP-450 extension: build_mismo_section's key vocabulary is statically enumerable.
    assert "loan.program" in _MISMO_LOAN_KEYS and "property.purchase_price" in _MISMO_LOAN_KEYS
    assert (
        "marital_status" in _MISMO_BORROWER_SUFFIXES and "citizenship" in _MISMO_BORROWER_SUFFIXES
    )
    assert (
        "income.{n}.monthly_amount" in _MISMO_BORROWER_SUFFIXES
    )  # index-normalised collection field
    # declaration.<slug> is deliberately NOT in the suffix set (prefix-handled residual).
    assert not any(s.startswith("declaration.") for s in _MISMO_BORROWER_SUFFIXES)


# --------------------------------------------------------------------------- #
# The exemptions are genuine — the allow-list cannot rot into hiding a fixable declaration
# --------------------------------------------------------------------------- #
def test_exemptions_are_still_genuine_mismatches() -> None:
    doc_fields = _document_field_universe()
    decls = load_declarations()
    for tag_id in _KNOWN_UNPRODUCIBLE:
        decl = decls[tag_id]
        assert decl.mode is ProductionMode.PARSED
        assert not _resolves(decl, doc_fields), (
            f"{tag_id} is exempted but now RESOLVES — remove it from _KNOWN_UNPRODUCIBLE "
            "(the exemption is masking a healthy declaration)"
        )
