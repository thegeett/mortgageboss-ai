"""The parsed-declaration field guard (LP-369) — a declaration must name a field that EXISTS.

THE BUG CLASS (found four times): a declaration names something that doesn't exist → the thing is
ABSENT → the rule couldnt_checks on every file → silently, forever, with every test green. AS-1 read
income through a calc gated on an unused input (LP-366); IN-8/IN-9 named document types the classifier
doesn't emit (LP-333); `housing.insurance_monthly` was declared `producer=AI` with no producer (LP-367);
and parsed tags named extraction fields that don't exist — `id.dob` read `dob` (it is `date_of_birth`),
`id.ssn_hash` read `ssn` (it is `employee_ssn`) — silently killing LIVE rules ID-3 and ID-2 (LP-368/369).

THE ROOT: the loader validates declarations that EXIST; it does not validate that what they POINT AT
exists. A declared key with no member resolves to ABSENT, and absent is indistinguishable from "the
document genuinely doesn't have this" — so it is silent.

THE GUARD (this test): for every `mode: parsed` declaration, the field it reads MUST be a real member of
the resolution universe its `subject` reads from:
  * ``subject: document``  → an extraction model's field name (``DocumentEntry.fields`` keys; see
    ``build_document_fields``), or the ``asserted_name`` alias.
  * ``subject: transaction`` → a ``_TXN_FIELDS`` key.
  * ``subject: borrower`` / ``loan`` → MISMO facts, which are DATA-DEPENDENT (``borrower.{n}.<field>`` /
    a full key). These are NOT statically checkable from the models, so the guard SKIPS them — and this
    file documents that it does not cover them.

WHY A TEST, NOT A LOAD-TIME CHECK: the authoritative field universe lives in ``app.ai.extraction.*`` (the
AI extraction models). A load-time check would force the deterministic tag-vocabulary loader
(``declarations.py``) to import the AI extraction layer — a layering inversion. Keeping the check in the
test layer fails CI just as loudly without that coupling. (If the layering is later resolved, promoting
this to a loader validation is a small follow-up.)

The ``:``-suffix (``employee_ssn:hash``) is split off before the field lookup (``producer.py``), so the
guard checks the part before the colon.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil

import app.ai.extraction as extraction_pkg
from app.verification.tag_materialization.declarations import (
    ProductionMode,
    TagDeclaration,
    load_declarations,
)
from app.verification.tag_materialization.subjects import _TXN_FIELDS
from pydantic import BaseModel

# Declarations whose field genuinely has NO producer today — a KNOWN missing-extraction gap, not a
# typo, and their consuming rules are DORMANT (not in ACTIVE_RULE_IDS). Exempted LOUDLY (here, with a
# reason) rather than silently — the guard still fails on any NEW mismatch. Each must remain a genuine
# mismatch (asserted below) so the exemption cannot rot into hiding a now-resolvable declaration.
_KNOWN_UNPRODUCIBLE: dict[str, str] = {
    # stated income is MISMO-indexed (borrower.{n}.income.{m}.monthly_amount), not a document field —
    # it needs a DERIVED/borrower source (cf. dti.qualifying_income_monthly). IN-1 / DT-1 dormant.
    "income.stated_monthly": "stated income is MISMO-indexed, not a document field (needs a derived source)",
    # no extractor emits a page count ('Page X of Y'); AS-9 dormant. A missing-extraction gap.
    "stmt.page_count_declared": "no extraction model emits a page count",
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


def _field_name(decl: TagDeclaration) -> str:
    """The field the parsed producer looks up — the ``data`` key with any ``:suffix`` (e.g. ``:hash``)
    stripped, mirroring ``producer.py``'s ``decl.data.split(':', 1)[0]``."""
    return decl.data.split(":", 1)[0]


def _resolves(decl: TagDeclaration, doc_fields: set[str]) -> bool:
    """Whether the declaration's field exists in the universe its subject reads. Borrower/loan (MISMO)
    are data-dependent → not statically checkable → treated as resolving (out of this guard's scope)."""
    field = _field_name(decl)
    if decl.subject == "document":
        return field in doc_fields
    if decl.subject == "transaction":
        return field in _TXN_FIELDS
    return True  # borrower / loan — MISMO, not statically checkable (documented limitation)


def _parsed_declarations() -> list[tuple[str, TagDeclaration]]:
    return [
        (tag_id, decl)
        for tag_id, decl in load_declarations().items()
        if decl.mode is ProductionMode.PARSED
    ]


# --------------------------------------------------------------------------- #
# THE GUARD — every parsed declaration names a real field
# --------------------------------------------------------------------------- #
def test_every_parsed_document_declaration_names_a_real_extraction_field() -> None:
    doc_fields = _document_field_universe()
    violations = [
        f"{tag_id} {{subject: {decl.subject}, data: {decl.data!r}}} → field {_field_name(decl)!r} "
        f"is not emitted by any extractor"
        for tag_id, decl in _parsed_declarations()
        if not _resolves(decl, doc_fields) and tag_id not in _KNOWN_UNPRODUCIBLE
    ]
    assert not violations, (
        "parsed declaration(s) name a field no producer emits → the tag is ABSENT and its rule "
        "couldnt_checks silently on every file (LP-369 bug class):\n  " + "\n  ".join(violations)
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
