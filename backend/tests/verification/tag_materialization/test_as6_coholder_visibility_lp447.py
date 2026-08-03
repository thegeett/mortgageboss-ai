"""AS-6 reads the joint-account co-holder with NO rule/prompt change — the LP-447 Part 1 finding (D1).

LP-446 added ``account_owner_name_2`` / ``account_owner_count`` to the bank_statement extractor. AS-6's tags are
produced by the ``stmt_facts`` AI group over ``_doc_context``, which emits EVERY present document field. So the
new fields are already visible to the reasoner with NO code change — and because ``_doc_context`` OMITS absent
fields, a single-holder statement's context is byte-identical to pre-LP-446 (the AS-6 11/11 calibration, which
ships AUTO, is preserved by construction). Only a JOINT account gains the second-holder line.

⚠️ These are the GUARDS behind "AS-6 needed no change": if a future ticket PII-routes ``account_owner_name_2``
(masking it) the co-holder name would stop reaching the reasoner and AS-6 would silently go blind on joint
accounts — this test turns red first. (The end-to-end verdicts — the 4 real joint statements stay ``satisfied``,
a genuine non-borrower co-holder → ``needs_review`` while the statement still counts — were proven on the real
dev-DB documents in LP-447; see docs/tickets/LP-447.md.)
"""

from __future__ import annotations

from app.verification.snapshot.documents_section import _PII_FIELDS
from app.verification.snapshot.fields import Field, FieldSource
from app.verification.snapshot.model import DocumentEntry
from app.verification.tag_materialization.subjects import _DEFAULT_CONTEXT_OPTIONS, _doc_context


def _stmt(**fields: str) -> DocumentEntry:
    return DocumentEntry(
        content_id="stmt-1",
        document_type="bank_statement",
        belongs_to=None,
        fields={k: Field.present(v, source=FieldSource.EXTRACTED) for k, v in fields.items()},
    )


def test_coholder_fields_are_not_pii_routed_so_they_reach_the_reasoner_unmasked() -> None:
    # A masked name/count would blind the co-holder comparison. AS-6 needs the actual second-holder name to
    # judge it against the borrower roster, so these MUST stay plain (non-PII) fields — pinned here.
    for field in ("account_owner_name_2", "account_owner_count", "account_holder_name"):
        assert field not in _PII_FIELDS


def test_doc_context_emits_the_coholder_fields_on_a_joint_account() -> None:
    joint = _stmt(
        account_holder_name="AKASH V PATEL",
        account_owner_name_2="BANSARI N PATEL",
        account_owner_count="2",
    )
    ctx = _doc_context(joint, None, _DEFAULT_CONTEXT_OPTIONS)
    # The stmt_facts reasoner sees BOTH holders + the count — the non_borrower_co_holder judgment's input.
    assert ctx["account_owner_name_2"] == "BANSARI N PATEL"
    assert ctx["account_owner_count"] == "2"
    assert ctx["account_holder_name"] == "AKASH V PATEL"


def test_single_holder_context_omits_the_new_fields_so_calibration_is_preserved() -> None:
    # The absent second-holder field is OMITTED (absent≠empty) → a single-holder statement's context is exactly
    # what it was pre-LP-446. The AS-6 11/11 calibration (auto-ship) cannot move on single-holder statements.
    single = _stmt(account_holder_name="AKASH V PATEL")
    ctx = _doc_context(single, None, _DEFAULT_CONTEXT_OPTIONS)
    assert "account_owner_name_2" not in ctx
    assert "account_owner_count" not in ctx
    assert ctx["account_holder_name"] == "AKASH V PATEL"
