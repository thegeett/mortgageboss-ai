"""Subject enumerators (LP-324) — resolve a spec's executable ``subject_enumeration`` key.

A rule's spec declares WHERE its subjects come from as a KEY (not prose); the generic evaluators
resolve the key to an enumerator that yields ``(subject_id, subject_tags)`` pairs from a tagged
snapshot. Adding a rule over an existing subject shape needs no new Python — it reuses a key.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from app.verification.rules.specs import DOC_TYPE_TAG
from app.verification.snapshot.content_id import LIABILITY_PREFIX, assign_content_ids
from app.verification.snapshot.fields import Field
from app.verification.snapshot.model import DocumentEntry, Snapshot
from app.verification.snapshot.pii import PiiField
from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage
from app.verification.snapshot.traversal import all_list_rows, all_transactions

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

# --------------------------------------------------------------------------- #
# LP-480 — the per-liability subject shape (ADR-374: UNION, NO MERGE).
#
# Liabilities are described by TWO sources for the same real debts: MISMO file-level ``liability.{n}.*``
# facts (what the borrower DECLARED) and credit-report ``tradelines`` rows (what the bureau REPORTED).
# This enumerator unions them and NEVER merges: every row from either source is its own subject, marked
# with its source. Merging would destroy exactly the signal CR-4 exists to detect — an undisclosed
# tradeline IS a debt present in one source and absent from the other. See ADR-374 for the rejected
# alternatives (match-and-merge; single-source-of-truth).
#
# ⚠️ These are RESERVED STRUCTURAL MARKERS, not vocabulary tags (the DOC_TYPE_TAG / ACCOUNT_UNRESOLVED_TAG
# pattern) — they describe the SUBJECT, never the debt. No threshold, no classification: rules judge.
LIABILITY_SOURCE_TAG = "liability.source"
LIABILITY_UNRESOLVED_TAG = "liability.unresolved"
_SOURCE_MISMO = "mismo_stated"
_SOURCE_CREDIT_REPORT = "credit_report_reported"
_CREDIT_REPORT_DOC_TYPE = "credit_report"
_TRADELINES_LIST_NAME = "tradelines"
# The MISMO liability identity, in the projection's own field order. There is NO account number anywhere
# in the MISMO chain (parser → model → snapshot), so this is the whole of the available identity.
_MISMO_LIABILITY_FIELDS = ("type", "monthly_payment", "unpaid_balance", "holder_name")

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
#
# KNOWN LIMITATION (accepted, LP-336 review): the identity does NOT include account_type. Two accounts at
# the SAME institution sharing a masked last-4 (a checking and a savings both ****1234 at Chase) collide
# into one key. This is rare (a last-4 clash WITHIN one bank on one file) and adding account_type trades it
# for a MORE common over-split (account_type extracts inconsistently across a statement series) — so we keep
# the minimal identity and prefer minimizing over-split. Revisit if a real file surfaces the collision.
# --------------------------------------------------------------------------- #
_INST_PUNCT = re.compile(r"[^\w\s]")
_INST_WS = re.compile(r"\s+")


def _norm_institution(name: str) -> str:
    """Normalize a bank name for the account key — casefold + drop punctuation + collapse whitespace (the
    consistency-evaluator chain), so 'Chase Bank, N.A.' / 'Chase Bank NA' / 'chase bank  n.a.' resolve to
    ONE account rather than over-splitting (an over-split fabricates or hides a chaining break — the LP-336
    danger). It does NOT fuzzy-match substantively different renderings ('Chase' vs 'JPMorgan Chase') — a
    deterministic key cannot, and fail-closed prefers a clean under-match to a guessed merge."""
    return _INST_WS.sub(" ", _INST_PUNCT.sub("", name.casefold())).strip()


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
        account_key = f"account:{_norm_institution(institution)}:{masked}"
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
        # The account subject carries only tags that AGREE across its statements. A per-statement tag that
        # DIFFERS between statements (each statement's own ending_balance) is DROPPED, not kept last-wins —
        # a rule reading it then couldnt_checks (fail-closed) instead of silently getting one arbitrary
        # statement's value. A rule that needs the per-statement series uses resolve_accounts directly.
        merged: dict[str, Tag] = {}
        conflicting: set[str] = set()
        for cid in content_ids:
            for tag_id, tag in by_subject.get(cid, {}).items():
                if tag_id in conflicting:
                    continue
                existing = merged.get(tag_id)
                if existing is None:
                    merged[tag_id] = tag
                elif str(existing.value) != str(tag.value):
                    del merged[tag_id]  # conflicting per-statement values → drop (never last-wins)
                    conflicting.add(tag_id)
        subjects.append((account_key, merged))
    for cid in unresolvable:
        subjects.append((cid, {ACCOUNT_UNRESOLVED_TAG: _account_unresolved_tag(cid)}))
    return subjects


def _liability_marker(value: str, reasoning: str, source_fact: str) -> Tag:
    """A reserved structural marker on a liability subject (the ``_account_unresolved_tag`` shape).

    The marker does NOT carry its own tag id — the caller keys it into the subject's tag map. (Reported
    finding: it previously took a ``tag_id`` it never used, which invited a caller to assume otherwise.)
    """
    return Tag(
        value=value,
        confidence=None,
        reasoning=reasoning,
        source_facts=(source_fact,),
        produced_by=TagProducedBy.DERIVED,
        tag_role=TagRole.STRUCTURAL_FACT,
        stage=TagStage.A,
    )


@dataclass(frozen=True)
class LiabilityRow:
    """One liability from either source, with the identity BOTH enumerations must agree on (LP-483).

    ``per_liability`` (the rule-engine subject enumerator) and the ``liability`` PRODUCTION subject family
    (``tag_materialization/subjects.py``) must key on the SAME ``subject_id``, or a tag materialises under
    an id no rule ever reads. They therefore both build from this one function rather than deriving ids
    twice — the drift is removed by construction, not by a comment asking two call sites to stay in step.

    ``fields`` carries the RAW snapshot fields (a producer reads them); ``values`` is the string projection
    the content hash is taken over (unchanged from LP-480, so existing ids are stable).
    """

    subject_id: str
    source: str
    fields: Mapping[str, Field | PiiField]
    values: Mapping[str, str | None]
    origin: str  # the row_id / the ``liability.{n}`` key — for a marker's reasoning
    unresolved_reason: str | None


def liability_rows(snapshot: Snapshot) -> list[LiabilityRow]:
    """Every liability subject on the file, from BOTH sources, in enumeration order (LP-483).

    The union ADR-374 defines: credit-report tradelines first (keyed by their LP-479 ``row_id``), then the
    idless tradelines, then the MISMO stated liabilities (keyed by a content hash over their four fields).
    Nothing is matched or merged here — that is a rule's judgment, never an enumerator's.
    """
    rows: list[LiabilityRow] = []
    idless: list[tuple[dict[str, str | None], dict[str, Field | PiiField]]] = []
    for row in all_list_rows(
        snapshot, _TRADELINES_LIST_NAME, document_type=_CREDIT_REPORT_DOC_TYPE
    ):
        values = {name: _field_str(f) for name, f in sorted(row.fields.items())}
        if row.row_id is None:
            idless.append((values, dict(row.fields)))
            continue
        rows.append(
            LiabilityRow(
                subject_id=row.row_id,
                source=_SOURCE_CREDIT_REPORT,
                fields=dict(row.fields),
                values=values,
                origin=row.row_id,
                unresolved_reason=None,
            )
        )
    for subject_id, (values, fields) in zip(
        assign_content_ids(LIABILITY_PREFIX, [{"liability": v} for v, _ in idless]),
        idless,
        strict=True,
    ):
        rows.append(
            LiabilityRow(
                subject_id=subject_id,
                source=_SOURCE_CREDIT_REPORT,
                fields=fields,
                values=values,
                origin=subject_id,
                unresolved_reason=(
                    "the tradeline row carries no stable row_id, so it has no identity durable "
                    "across runs — surfaced on its own rather than dropped"
                ),
            )
        )
    mismo = _mismo_liabilities(snapshot)
    for subject_id, (values, mismo_key, fields) in zip(
        assign_content_ids(LIABILITY_PREFIX, [{"liability": v} for v, _, _ in mismo]),
        mismo,
        strict=True,
    ):
        rows.append(
            LiabilityRow(
                subject_id=subject_id,
                source=_SOURCE_MISMO,
                fields=fields,
                values=values,
                origin=mismo_key,
                unresolved_reason=(
                    None
                    if values.get("holder_name") is not None
                    else (
                        f"stated liability {mismo_key} names no holder, so it cannot be identified "
                        "against a reported tradeline — surfaced on its own rather than dropped or "
                        "guess-merged"
                    )
                ),
            )
        )
    return rows


def _mismo_liabilities(
    snapshot: Snapshot,
) -> list[tuple[dict[str, str | None], str, dict[str, Field | PiiField]]]:
    """The file's MISMO liabilities as ``[({field: value}, mismo_key, {field: raw}), …]``, in projection order.

    Reads the ``liability.{n}.{field}`` facts the MISMO section projects. The ``{n}`` index is POSITIONAL
    (``mismo_section`` enumerates sorted by row id), so it is used ONLY to gather a row's fields together —
    never as the subject id (see ``_per_liability``). The third element carries the RAW fields so a parsed
    producer can read them (LP-483); the hashed ``values`` projection is unchanged, so ids are stable.
    """
    if snapshot.mismo.absent:
        return []
    rows: dict[str, dict[str, str | None]] = {}
    raw_rows: dict[str, dict[str, Field | PiiField]] = {}
    for key, field in snapshot.mismo.facts.items():
        parts = key.split(".")
        if len(parts) != 3 or parts[0] != "liability":
            continue
        _, index, name = parts
        if name not in _MISMO_LIABILITY_FIELDS:
            continue
        rows.setdefault(index, {})[name] = _field_str(field)
        raw_rows.setdefault(index, {})[name] = field
    ordered = sorted(rows, key=lambda i: (len(i), i))  # numeric-ish, deterministic
    return [
        (
            {f: rows[i].get(f) for f in _MISMO_LIABILITY_FIELDS},
            f"liability.{i}",
            raw_rows.get(i, {}),
        )
        for i in ordered
    ]


def _per_liability(snapshot: Snapshot) -> list[Subject]:
    """One subject per liability, UNIONED across both sources and NEVER merged (LP-480 / ADR-374).

    * a credit-report ``tradelines`` row → its LP-479 ``row_id`` (a content hash over the whole row,
      already proven unique 35/35 on the stored reports) + ``liability.source = credit_report_reported``;
    * a MISMO ``liability.{n}.*`` row → a CONTENT-derived id over its four available fields (never the
      positional ``{n}``, so the id survives a reordering) + ``liability.source = mismo_stated``.

    ⚠️ NO MATCHING between the sources. The same real debt appears twice, once per source, deliberately:
    CR-4's undisclosed-tradeline signal IS the difference between the two lists, and a merge would erase
    it. A summing rule must therefore filter on ``liability.source`` rather than sum every subject —
    stated in ADR-374 because a naive sum double-counts.

    ⚠️ The ``(creditor, account_number_masked)`` composite that ``_per_account`` uses is NOT usable here:
    the LP-443 redact backstop scrubs unmasked account numbers, leaving 9/35 rows a bare ``[redacted]``
    and collapsing two distinct SETOYOTA tradelines onto one key — a guess-merge on real data.

    A liability whose identity cannot be established (a MISMO row with no holder name, or a tradeline row
    with no ``row_id``) still gets its own subject, carrying ``liability.unresolved`` — never dropped,
    never merged (the ``_per_account`` rule). Absent tags yield subjects with EMPTY maps, so the gate
    reports ``couldnt_check`` per liability rather than the rule silently vanishing.

    ⚠️ **DECIDED, not overlooked — the MISMO subject id is a function of MUTABLE amounts** (reported
    finding). ``_MISMO_LIABILITY_FIELDS`` includes ``monthly_payment`` and ``unpaid_balance``, so when a
    borrower re-submits an updated 1003 with a moved balance, the same real debt hashes to a DIFFERENT id
    — and LP-322 reconciles findings by ``(rule_id, subject_key)``, so the prior finding RETIRES and a
    duplicate is minted, losing any processor resolution on it. It is kept anyway because the alternative
    is worse: ``(holder_name, type)`` alone collides on the two SETOYOTA rows in the real file and would
    fall back to ``assign_content_ids``' order-dependent occurrence tiebreak, making the id depend on
    projection order — the very thing this shape refuses. MISMO carries no account number anywhere in the
    chain (parser → model → snapshot), so there is no stable natural key to use instead. Revisit if a rule
    ever needs a liability finding to survive a re-import; see ADR-374.

    ⚠️ **No dedup WITHIN a source** (reported finding). The union is across sources only. Two
    ``credit_report`` documents on one file — the same report uploaded twice, or a per-borrower report on
    a joint file — carry distinct document content-ids, hence distinct ``row_id``s, hence TWO subjects for
    one debt. ADR-374's "a summing rule must filter on ``liability.source``" does NOT protect against
    this: a sum over ``credit_report_reported`` still double-counts. Same limitation the loan-level
    aggregate already records (``tag_materialization/derived.py``, the ``_credit_tradeline_count``
    preamble); multi-report reconciliation is a rule's concern, once one reconciles bureaus.
    """
    by_subject = {} if snapshot.tags.absent else snapshot.tags.by_subject
    subjects: list[Subject] = []
    for row in liability_rows(snapshot):
        tags = dict(by_subject.get(row.subject_id, {}))
        tags[LIABILITY_SOURCE_TAG] = _liability_marker(
            row.source,
            (
                "reported by the credit bureau on a credit report tradeline"
                if row.source == _SOURCE_CREDIT_REPORT
                else f"stated by the borrower on the application ({row.origin})"
            ),
            row.subject_id,
        )
        if row.unresolved_reason is not None:
            tags[LIABILITY_UNRESOLVED_TAG] = _liability_marker(
                "yes", row.unresolved_reason, row.subject_id
            )
        subjects.append((row.subject_id, tags))
    return subjects


def per_liability_source_is_degraded(snapshot: Snapshot) -> bool:
    """True when the CREDIT-REPORT leg of ``per_liability`` could not contribute (LP-480 review).

    ``_retire_eligible_rules`` (``services/verification_run.py``) protects a document-derived rule from
    retiring its prior findings on a degraded run by asking "did this enumeration yield zero subjects?".
    ``per_liability`` is the FIRST enumeration drawing on two sources, and that heuristic does not hold
    for it: a file with stated MISMO liabilities returns a non-empty union even when the credit report
    failed to build, so the union looks healthy while half the subjects are missing — and every prior
    tradeline finding would retire as "no longer applies".

    So the mixed-source shape needs a PER-SOURCE check. The credit-report leg is the document-derived one
    (the MISMO leg is not: MISMO is parsed, not extracted, and its absence is a real "no stated
    liabilities" answer). It is degraded when the documents section is absent altogether, or when a
    credit_report document IS on the file but contributed no tradeline rows.
    """
    if snapshot.documents.absent:
        return True
    has_credit_report = any(
        entry.document_type == _CREDIT_REPORT_DOC_TYPE for entry in snapshot.documents.entries
    )
    if not has_credit_report:
        return False  # no credit report on the file at all — an honest "nothing reported", not degraded
    return not all_list_rows(snapshot, _TRADELINES_LIST_NAME, document_type=_CREDIT_REPORT_DOC_TYPE)


_ENUMERATORS: dict[str, Enumerator] = {
    "per_deposit": _per_deposit,
    "loan": _loan,
    "per_borrower": _per_borrower,
    "per_document": _per_document,
    "per_account": _per_account,
    "per_liability": _per_liability,
}

# The drift guard (the _COERCERS / _NORMALIZERS pattern): a typo in a registry key fails at IMPORT, not
# at evaluation time on a real file.
KNOWN_ENUMERATORS = frozenset(
    {"per_deposit", "loan", "per_borrower", "per_document", "per_account", "per_liability"}
)
assert set(_ENUMERATORS) == KNOWN_ENUMERATORS, "enumerator registry drifted from KNOWN_ENUMERATORS"


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
    "LIABILITY_SOURCE_TAG",
    "LIABILITY_UNRESOLVED_TAG",
    "LOAN_SUBJECT",
    "enumerate_subjects",
    "is_known_enumerator",
    "per_liability_source_is_degraded",
    "resolve_accounts",
]
