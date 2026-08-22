"""Finding source-document matching (LP-114.1) — derive the SET of documents a finding came from.

A cross-source finding is derived from MULTIPLE documents (an employer appears on a pay stub AND a
W-2; a discrepancy compares stated data against one-or-more documents). LP-114 stored a single
``source_document_id`` and nulled out whenever a value spanned several same-type documents. This
derives the full SET by value-matching the finding's **cited value(s)** against every document whose
current extraction contains them.

**Honest by construction — the precision discipline.** The match keys on the finding's SPECIFIC
distinctive cited value (its ``document_value``; a dollar amount / address / account fragment in the
snippet) — NOT on generic tokens. A document is in the set only if its extraction genuinely contains
that distinctive value, so a common token ("Health", a round number) that merely coincides in an
unrelated document does NOT over-include it. Showing every document that truly contains the value
(the pay stub AND the W-2 for one employer) both completes the provenance and removes the
"which one?" wrong-pick risk that made LP-114 null out.
"""

import json
import re
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.documents.catalog import get_category
from app.models.document import Document, DocumentCategory
from app.models.finding import Finding, FindingCategory
from app.models.helpers import only_active

# A finding derives from documents of a COMPATIBLE category (LP-114.1 precision) — so an employer
# (INCOME) finding is NOT over-attributed to a savings statement (ASSETS) merely because the bank
# name coincides. Cross-cutting finding categories (cross-source / documentation / regulatory) are
# UNCONSTRAINED (any document type) — they legitimately span sources. GROUNDED STARTER —
# validate-with-Priya (the exact finding→document-category compatibility).
_COMPATIBLE_DOC_CATEGORIES: dict[FindingCategory, set[DocumentCategory]] = {
    FindingCategory.INCOME: {DocumentCategory.INCOME_EMPLOYMENT},
    FindingCategory.ASSETS: {DocumentCategory.ASSETS},
    FindingCategory.CREDIT: {DocumentCategory.CREDIT, DocumentCategory.PROPERTY},
    FindingCategory.PROPERTY: {DocumentCategory.PROPERTY},
}

# Minimum length for a distinctive value — shorter strings are too common to attribute a document.
_MIN_LEN = 5
# Bare words that are too common to be a distinctive source key on their own (a value is kept only
# when it is a MULTI-word phrase or carries digits; a single common word alone is dropped).
_STOPWORDS = frozenset(
    {
        "charlotte",
        "north",
        "carolina",
        "united",
        "states",
        "america",
        "national",
        "association",
        "bank",
        "current",
        "statement",
        "account",
        "patel",
        "llc",
    }
)


def _norm(value: str) -> str:
    """Lowercase + drop thousands-commas so "8,076.93" matches "8076.93". Whitespace-collapse."""
    return re.sub(r"\s+", " ", re.sub(r"(?<=\d),(?=\d)", "", value.lower())).strip()


def distinctive_values(finding: Finding) -> list[str]:
    """The finding's SPECIFIC cited value(s) — the distinctive things it is about (LP-114.1).

    Keys on the actual cited value (``details["document_value"]``; amounts / addresses / account
    fragments in the snippet), NOT generic tokens — so a document is a source only if it genuinely
    contains that value. A lone common word is dropped (precision); a multi-word phrase or a
    digit-bearing value is kept.
    """
    details = finding.details or {}
    raw: list[str] = []
    document_value = details.get("document_value")
    if isinstance(document_value, str):
        raw.append(document_value)
    snippet = finding.source_snippet
    if isinstance(snippet, str):
        raw += re.findall(r"\d{1,3}(?:,\d{3})*\.\d{2}", snippet)  # dollar-ish amounts
        raw += re.findall(  # street addresses
            r"\d+\s+[A-Z0-9 .]+(?:ST|RD|DR|AVE|BLVD|LN|CT|WAY|COVE|PL|TER|PKWY)\b[A-Z0-9 ,#-]*",
            snippet,
        )
        raw += re.findall(r"\.\.\.\s*(\d{4,})", snippet)  # account fragments (...6684)

    out: list[str] = []
    seen: set[str] = set()
    for value in raw:
        norm = _norm(value)
        # A 4+ digit number (an account-number tail / zip) is distinctive despite being short.
        is_numeric_fragment = norm.isdigit() and len(norm) >= 4
        if (len(norm) < _MIN_LEN and not is_numeric_fragment) or norm in seen:
            continue
        has_digit = any(c.isdigit() for c in norm)
        is_multiword = " " in norm
        # Precision: keep a value only if it's distinctive — multi-word, digit-bearing, or a single
        # non-stopword long token. A lone common word alone is not enough to attribute a document.
        if not (has_digit or is_multiword or norm not in _STOPWORDS):
            continue
        seen.add(norm)
        out.append(norm)
    return out


def _is_compatible(finding: Finding, doc_category: DocumentCategory) -> bool:
    """Whether a document of ``doc_category`` can be a source for this finding (LP-114.1 precision).

    Cross-cutting finding categories are unconstrained (any); a category-specific finding matches
    only compatible document categories — so a common institution name in an off-category document
    doesn't over-include it.
    """
    compatible = _COMPATIBLE_DOC_CATEGORIES.get(finding.category)
    return compatible is None or doc_category in compatible


def match_source_documents(
    finding: Finding, doc_index: list[tuple[UUID, DocumentCategory, str]]
) -> list[UUID]:
    """The document ids whose extraction contains one of the finding's distinctive cited values AND
    whose category is compatible with the finding (LP-114.1).

    ``doc_index`` is ``[(document_id, document_category, normalized_extraction_text)]``. Honest by
    construction: a doc is included only if it genuinely contains a distinctive value (never a
    coincidental common token) and is a category the finding could derive from.
    """
    needles = distinctive_values(finding)
    if not needles:
        return []
    return [
        doc_id
        for doc_id, category, text in doc_index
        if _is_compatible(finding, category) and any(n in text for n in needles)
    ]


async def _document_index(
    db: AsyncSession, loan_file_id: UUID
) -> list[tuple[UUID, DocumentCategory, str]]:
    """Each active document's category + current extraction, normalized to searchable text."""
    docs = (
        await db.scalars(
            only_active(
                select(Document)
                .where(Document.loan_file_id == loan_file_id)
                .options(selectinload(Document.extractions)),
                Document,
            )
        )
    ).all()
    index: list[tuple[UUID, DocumentCategory, str]] = []
    for doc in docs:
        extraction = doc.current_extraction
        text = (
            _norm(json.dumps(extraction.extracted_data))
            if extraction and extraction.extracted_data
            else ""
        )
        index.append((doc.id, doc.category or get_category(doc.document_type), text))
    return index


async def populate_finding_source_documents(db: AsyncSession, *, loan_file_id: UUID) -> int:
    """Derive + store each finding's source-document SET (LP-114.1). Idempotent; re-derives.

    Value-matches every active finding's distinctive cited value(s) to ALL documents that contain
    them; stores the set in ``source_document_ids``. LP-114's exact ``source_document_id`` (the
    primary) is always retained + included in the set; if it was null and the set is non-empty, the
    first becomes the primary. Uses ``flush``; the caller owns the transaction. Returns the count of
    findings whose set changed.
    """
    index = await _document_index(db, loan_file_id)
    findings = (
        await db.scalars(
            only_active(select(Finding).where(Finding.loan_file_id == loan_file_id), Finding)
        )
    ).all()
    changed = 0
    for finding in findings:
        # LP-620 — A GOVERNED FINDING IS SKIPPED, because for one this function truncates rather than
        # enriches. `distinctive_values` returns [] for it (no `details["document_value"]`, no
        # `source_snippet`), so `matched` is empty; LP-617 then made `source_document_id` non-null, so
        # the primary is inserted at index 0 and the set is rewritten to that ONE id — a two-document
        # ID-4 provenance collapsing to one. The rule engine resolves its own provenance from snapshot
        # content ids, which is exact where this is a value match. Both callers are currently dead
        # (`cross_source._run` returns early since LP-614; `verification_engine` has no caller), so this
        # is a guard for whoever re-enables one, not a live fix.
        #
        # KEYED ON `evaluation_outcome`, NOT `origin` — LP-375's discriminator, for its reason:
        # `deterministic_rule` spans BOTH the governed engine AND the retired xsrc findings, and the
        # xsrc ones are exactly what this populator is for. Keying on origin skipped them too and broke
        # the provenance it exists to build.
        if finding.evaluation_outcome is not None:
            continue
        matched = match_source_documents(finding, index)
        ids: list[UUID] = list(matched)
        # LP-114's exact primary is authoritative — always included, first.
        if finding.source_document_id is not None and finding.source_document_id not in ids:
            ids.insert(0, finding.source_document_id)
        new_value = [str(i) for i in ids] or None
        if finding.source_document_ids != new_value:
            finding.source_document_ids = new_value
            changed += 1
        if finding.source_document_id is None and ids:
            finding.source_document_id = ids[0]  # promote the first as the primary (back-compat)
    await db.flush()
    return changed
