"""Subject enumerators (LP-324) — resolve a spec's executable ``subject_enumeration`` key.

A rule's spec declares WHERE its subjects come from as a KEY (not prose); the generic evaluators
resolve the key to an enumerator that yields ``(subject_id, subject_tags)`` pairs from a tagged
snapshot. Adding a rule over an existing subject shape needs no new Python — it reuses a key.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from app.verification.rules.specs import DOC_TYPE_TAG
from app.verification.snapshot.fields import Field
from app.verification.snapshot.model import DocumentEntry, Snapshot
from app.verification.snapshot.pii import PiiField
from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage
from app.verification.snapshot.traversal import all_transactions

# The loan-level subject key: loan-level tags (occupancy.*, id.*, …) live under this single subject
# in the tags layer (distinct from the per-transaction content_id subjects). Introduced by LP-319.
LOAN_SUBJECT = "loan"
_UNKNOWN = "unknown"

# The reserved structural marker an unresolvable statement carries (LP-336) — a NON-vocabulary tag (like
# DOC_TYPE_TAG), so a per_account rule can see WHY a statement was not grouped and couldnt_check it. The
# statements that DID resolve carry their account_key as the subject id; this marks the ones that did not.
ACCOUNT_UNRESOLVED_TAG = "account.unresolved"
# Only depository statements carry the (institution, masked-number) account identity this groups on.
_STATEMENT_DOC_TYPE = "bank_statement"

Subject = tuple[str, Mapping[str, Tag]]
Enumerator = Callable[[Snapshot], list[Subject]]


def _per_deposit(snapshot: Snapshot) -> list[Subject]:
    """One subject per bank-statement transaction (its stable content_id + its tag map)."""
    if snapshot.tags.absent:
        return [(txn.content_id, {}) for txn in all_transactions(snapshot)]
    return [
        (txn.content_id, snapshot.tags.by_subject.get(txn.content_id, {}))
        for txn in all_transactions(snapshot)
    ]


def _loan(snapshot: Snapshot) -> list[Subject]:
    """The single loan-level subject (loan-level tags live under ``LOAN_SUBJECT``)."""
    tags = {} if snapshot.tags.absent else snapshot.tags.by_subject.get(LOAN_SUBJECT, {})
    return [(LOAN_SUBJECT, tags)]


def _per_borrower(snapshot: Snapshot) -> list[Subject]:
    """One subject per borrower on the loan — serving BOTH meanings of ``per_borrower`` (LP-325/331).

    Borrowers are the distinct ``belongs_to`` refs across the documents (the reliable
    borrower↔document resolution, LP-202), in first-seen order.

    The subject's tag map is ASSEMBLED (LP-331, GAP-D) by DECLARED keying, so the SAME enumerator
    serves its two legitimate meanings without duplicating a fact:

    * a CONSISTENCY rule uses ``per_borrower`` as a GROUPING KEY and IGNORES this map — it GATHERS its
      document-keyed fact across the borrower's documents itself (LP-325). So what this map contains is
      irrelevant to consistency (verified: ``consistency.py`` discards ``_subject_tags``), and ID-1/2/3/4
      are unchanged. LP-326's document keying is untouched.
    * a per-borrower JUDGMENT rule (e.g. ID-8 citizenship eligibility) READS this map. It gets the
      borrower's OWN facts (materialized under ``by_subject[borrower_id]`` — a borrower-level fact like
      ``id.citizenship`` from the 1003/MISMO) plus the LOAN-LEVEL shared facts (e.g. ``program.type``)
      merged in as context — each fact from its ONE declared keying (no duplication, no divergence). A
      borrower's own facts override a same-id loan fact.

    Borrower isolation: each map holds ONLY that borrower's own tags + the shared loan tags — one
    borrower's facts never leak into another's. An absent/empty map → the judgment gates to couldnt_check
    for that borrower (fail-closed), never a fabricated verdict.

    NOTE (deferred, LP-331): a PRODUCER that materializes ``id.citizenship`` under ``borrower_id`` from
    MISMO (which keys per-borrower facts by INDEX, ``borrower.N.*``) needs a ``borrower_id ↔ MISMO-index``
    resolution — a separate materialization gap. This enumerator is complete regardless of how the
    borrower's facts got under ``by_subject[borrower_id]``.
    """
    if snapshot.documents.absent:
        return []
    by_subject = {} if snapshot.tags.absent else snapshot.tags.by_subject
    loan_tags = by_subject.get(
        LOAN_SUBJECT, {}
    )  # loan-level facts, shared into every borrower's context
    seen: dict[str, None] = {}  # borrower_id -> None, preserving first-seen (deterministic) order
    for entry in snapshot.documents.entries:
        if entry.belongs_to is None:
            continue
        for ref in entry.belongs_to:
            seen.setdefault(str(ref.borrower_id), None)
    # {**loan, **own}: the borrower's OWN facts take precedence over a same-id loan fact.
    return [(bid, {**loan_tags, **by_subject.get(bid, {})}) for bid in seen]


def _per_document(snapshot: Snapshot) -> list[Subject]:
    """One subject per document (LP-327) — its stable ``content_id`` + the tags ABOUT that document.

    Unlike ``per_borrower``, the tag map is POPULATED (a document's tags are keyed under its own
    content_id), so a per-DOCUMENT rule (ID-9 POA acceptability, ID-7 title vesting, altered-document
    detection, appraisal condition) can reason over that document's declared tags.

    The document's INTRINSIC type (``DocumentEntry.document_type`` — the classifier's known vocabulary:
    ``title_commitment`` / ``power_of_attorney`` / …) is injected as a structural subject tag
    ``document.document_type`` (LP-329), so a rule can DECLARE its document-type applicability as a
    plain tag predicate (``document.document_type == "power_of_attorney"``) — no document types in
    code, no entry-passing. An unclassified document → value ``"unknown"`` (the applicability then
    couldnt_checks — honest — rather than wrongly ruling the rule out).
    """
    if snapshot.documents.absent:
        return []
    tags = {} if snapshot.tags.absent else snapshot.tags.by_subject
    subjects: list[Subject] = []
    for entry in snapshot.documents.entries:
        subject_tags = {**tags.get(entry.content_id, {}), DOC_TYPE_TAG: _doc_type_tag(entry)}
        subjects.append((entry.content_id, subject_tags))
    return subjects


# DOC_TYPE_TAG (the reserved structural tag id for a document's intrinsic type) is the ONE contract
# source in ``specs`` — imported above — so a spec's applicability predicate and this injection can
# never drift, and RuleSpec validates a document-type-scoped rule is actually per_document.


def _doc_type_tag(entry: DocumentEntry) -> Tag:
    return Tag(
        value=entry.document_type or _UNKNOWN,
        confidence=None,
        reasoning="the document's classified type (structural)",
        source_facts=(entry.content_id,),
        produced_by=TagProducedBy.DERIVED,
        tag_role=TagRole.STRUCTURAL_FACT,
        stage=TagStage.A,
    )


# --------------------------------------------------------------------------- #
# per_account (LP-336) — group a file's bank-statement DOCUMENTS by account, FAIL-CLOSED.
#
# NOT a SubjectType (LP-323-AS-A refuted that): a statement IS a document, so stmt.* facts key under the
# DOCUMENT subject; grouping by account is an ENUMERATION concern, not a second keying (no fact keys under
# two subjects — the divergence risk LP-331/332 rejected).
#
# THE DANGER (mirrors LP-332's borrower_id resolution): the masked account number is "display only,
# non-matchable" (fact_tags.csv) — ****1234 at Chase and ****1234 at Wells Fargo look IDENTICAL. So the
# identity is (INSTITUTION, masked-number): both are deterministic extraction fields (bank_name +
# account_number_masked, no uncalibrated AI). A statement MISSING either identifier is UNRESOLVABLE — it is
# SURFACED (never dropped, never merged) so the rule couldnt_checks it WITH A REASON. A guessed grouping
# would MIS-GROUP (fabricating a chaining break) or OVER-SPLIT (hiding a real one) — worse than abstaining.
# --------------------------------------------------------------------------- #
def _field_str(field: Field | PiiField | None) -> str | None:
    """A present field's display value (PiiField → its MASKED display; Field → its value), stripped, or
    None. A PiiField contributes only its non-raw masked last-4 — no raw PII enters the account key."""
    if field is None or not field.is_present:
        return None
    value = field.display if isinstance(field, PiiField) else field.value
    text = str(value).strip() if value is not None else ""
    return text or None


def resolve_accounts(snapshot: Snapshot) -> tuple[dict[str, list[str]], list[str]]:
    """The FAIL-CLOSED account-identity resolution (the heart of LP-336). Returns
    ``({account_key: [statement content_id, …]}, [unresolvable content_id, …])``.

    A bank statement's account is identified by ``(institution, masked-number)`` — BOTH required, because
    the masked number alone collides across institutions. A statement missing EITHER is UNRESOLVABLE (not
    grouped, not dropped). The ``account_key`` is stable (derived from the identity, LP-312 spirit) so
    LP-322 reconciliation matches an account across runs; it carries only the bank name + masked last-4
    (both display-safe, the AS-1 subject-key precedent). Deterministic — reads parsed extraction fields."""
    resolved: dict[
        str, list[str]
    ] = {}  # account_key -> content_ids, first-seen (deterministic) order
    unresolvable: list[str] = []
    if snapshot.documents.absent:
        return resolved, unresolvable
    for entry in snapshot.documents.entries:
        if entry.document_type != _STATEMENT_DOC_TYPE:
            continue  # only depository statements carry this account identity
        institution = _field_str(entry.fields.get("bank_name"))
        masked = _field_str(entry.fields.get("account_number_masked"))
        if institution is None or masked is None:
            unresolvable.append(entry.content_id)  # cannot identify → never a guessed grouping
            continue
        account_key = f"account:{institution.casefold()}:{masked}"
        resolved.setdefault(account_key, []).append(entry.content_id)
    return resolved, unresolvable


def _account_unresolved_tag(content_id: str) -> Tag:
    return Tag(
        value="yes",
        confidence=None,
        reasoning=(
            f"statement {content_id} has no resolvable account identity (missing institution and/or "
            "masked account number) — not grouped, to avoid a guessed merge that could fabricate or hide "
            "a chaining break"
        ),
        source_facts=(content_id,),
        produced_by=TagProducedBy.DERIVED,
        tag_role=TagRole.STRUCTURAL_FACT,
        stage=TagStage.A,
    )


def _per_account(snapshot: Snapshot) -> list[Subject]:
    """One subject per resolved ACCOUNT (its stable key + its statements' merged tags), PLUS one subject
    per UNRESOLVABLE statement (its content_id + an ``account.unresolved`` marker), so a per_account rule
    couldnt_checks the ones that could not be grouped rather than silently missing them (absent≠empty)."""
    resolved, unresolvable = resolve_accounts(snapshot)
    by_subject = {} if snapshot.tags.absent else snapshot.tags.by_subject
    subjects: list[Subject] = []
    for account_key, content_ids in resolved.items():
        merged: dict[str, Tag] = {}
        for (
            cid
        ) in content_ids:  # the account's statements' tags (a grouping-key convenience; a rule that
            merged.update(
                by_subject.get(cid, {})
            )  # needs the ORDERED statements uses resolve_accounts)
        subjects.append((account_key, merged))
    for cid in unresolvable:
        subjects.append((cid, {ACCOUNT_UNRESOLVED_TAG: _account_unresolved_tag(cid)}))
    return subjects


_ENUMERATORS: dict[str, Enumerator] = {
    "per_deposit": _per_deposit,
    "loan": _loan,
    "per_borrower": _per_borrower,
    "per_document": _per_document,
    "per_account": _per_account,
}


def enumerate_subjects(key: str, snapshot: Snapshot) -> list[Subject]:
    """Resolve the spec's ``subject_enumeration`` key to its subjects (raises on an unknown key)."""
    enumerator = _ENUMERATORS.get(key)
    if enumerator is None:
        raise KeyError(f"unknown subject_enumeration key {key!r} (known: {sorted(_ENUMERATORS)})")
    return enumerator(snapshot)


def is_known_enumerator(key: str) -> bool:
    return key in _ENUMERATORS


__all__ = [
    "ACCOUNT_UNRESOLVED_TAG",
    "LOAN_SUBJECT",
    "enumerate_subjects",
    "is_known_enumerator",
    "resolve_accounts",
]
