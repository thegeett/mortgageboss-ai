"""Borrower↔document matching (LP-118.8) — "whose document is this".

Determines which borrower each document belongs to by fuzzy-matching the name(s) the document
carries (from its extraction) against the file's borrowers, then persists the links. Correct
identity checking (ID-1/2/3, IN-5) is PER-BORROWER, so the rules need this link. This module builds
it; it does NOT run any rule.

THE SAFETY RULE (the heart of this ticket): **a wrong assignment is worse than none.** A document
mis-filed under the wrong borrower would make the identity rules produce FALSE findings. So:

  * a **clear, unambiguous** high-confidence name match → assign;
  * a name that matches **two borrowers** too closely (ambiguous), a **weak** match, or **no**
    borrower name at all → leave the document **UNASSIGNED** (no link rows), with a recorded reason;
  * a document with **multiple** borrower names (a joint statement) → link to **each** borrower;
  * never force a low-confidence guess.

The matcher is pure + testable; :func:`assign_documents_to_borrowers` loads the data, runs it, and
replaces the file's link rows. A cousin of the LP-120 DET-FUZZY name/employer matching, kept
distinct (this is document ownership, not a verification check).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.logging import get_logger
from app.models.borrower import Borrower
from app.models.document import Document
from app.models.document_borrower_link import DocumentBorrowerLink
from app.models.helpers import only_active
from app.models.loan_file import LoanFile

logger = get_logger(__name__)

# The extraction typed-core keys that denote THIS document's owner (the borrower it belongs to).
# Deliberately conservative: buyer/seller/donor names are ambiguous ownership and are excluded, so
# a purchase contract / gift-donor name never invents a borrower.
_OWNER_NAME_KEYS = (
    "full_name",
    "employee_name",
    "account_holder_name",
    "borrower_name",
    "recipient_name",
    "name",
)
# Split a joint name field ("Bansari Patel and Akash Patel" / "A & B") into candidates. NOT commas
# (a "Last, First" would be mis-split).
_JOINT_SPLIT = re.compile(r"\s*(?:\band\b|&|;)\s*", re.IGNORECASE)
_SUFFIXES = frozenset({"jr", "sr", "ii", "iii", "iv", "v"})

# Assignment thresholds. A borrower is a contender at >= MATCH_MIN; assignment needs a CLEAR
# winner (ahead of the runner-up by >= MARGIN) — two close contenders are ambiguous, not assigned.
_MATCH_MIN = 0.7
_MARGIN = 0.2


# --------------------------------------------------------------------------- #
# Pure inputs / outputs
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class BorrowerRef:
    id: str
    first_name: str
    last_name: str
    full_name: str | None


@dataclass(frozen=True)
class DocumentNames:
    document_id: str
    names: tuple[str, ...]  # candidate owner names extracted from the document


@dataclass(frozen=True)
class BorrowerLink:
    borrower_id: str
    confidence: float
    method: str  # "exact" | "name" | "initial"


@dataclass(frozen=True)
class DocumentAssignment:
    document_id: str
    links: tuple[BorrowerLink, ...]  # empty → unassigned
    status: str  # "assigned" | "joint" | "unassigned"
    note: str | None  # unassigned reason: "no_name" | "no_match" | "ambiguous"


# --------------------------------------------------------------------------- #
# Name normalization + scoring
# --------------------------------------------------------------------------- #


def _tokens(name: str) -> list[str]:
    """Normalized name tokens: lowercase, punctuation-stripped, suffixes dropped ("B." → "b")."""
    cleaned = re.sub(r"\s+", " ", name.strip().lower())
    out: list[str] = []
    for raw in cleaned.split():
        tok = raw.strip(".,")
        if tok and tok not in _SUFFIXES:
            out.append(tok)
    return out


def _score(name: str, borrower: BorrowerRef) -> tuple[float, str]:
    """Score a document name against one borrower → (confidence, method). 0.0 = no match.

    Requires the LAST name to match (a strong anchor); then rewards a full first-name match, an
    initial match, and penalizes a same-last-different-first (a different person, same surname).
    """
    dtok = _tokens(name)
    if not dtok:
        return 0.0, "none"
    bfirst, blast = _tokens(borrower.first_name), _tokens(borrower.last_name)
    bfirst_s = bfirst[0] if bfirst else ""
    blast_s = blast[-1] if blast else ""

    # Exact full-name token match (handles a stored full_name with middle names).
    if borrower.full_name and dtok == _tokens(borrower.full_name):
        return 1.0, "exact"

    dfirst, dlast = dtok[0], dtok[-1]
    if not blast_s or dlast != blast_s:
        return 0.0, "none"  # last name must match
    if dfirst == bfirst_s:
        return 0.9, "name"  # first + last match (middle names ignored)
    if len(dfirst) == 1 and bfirst_s.startswith(dfirst):
        return 0.7, "initial"  # "B. Patel" → Bansari Patel
    if len(bfirst_s) == 1 and dfirst.startswith(bfirst_s):
        return 0.7, "initial"
    if len(dtok) == 1:
        return 0.3, "last_only"  # only a surname — too weak to identify
    return 0.2, "surname_only"  # same last, different first → likely a different person


def _identify(name: str, borrowers: list[BorrowerRef]) -> tuple[BorrowerLink | None, bool]:
    """Which borrower (if any) a single document name confidently identifies.

    Returns ``(link, ambiguous)``. A confident link needs the best score >= MATCH_MIN AND a clear
    margin over the runner-up. Two close contenders → ``ambiguous=True`` (no link).
    """
    scored = [(b, *_score(name, b)) for b in borrowers]
    scored.sort(key=lambda x: x[1], reverse=True)
    if not scored:
        return None, False
    best_b, best, method = scored[0]
    second = scored[1][1] if len(scored) > 1 else 0.0
    if best < _MATCH_MIN:
        return None, False  # weak/no match
    if best - second < _MARGIN:
        return None, True  # two contenders too close → ambiguous
    return BorrowerLink(borrower_id=best_b.id, confidence=best, method=method), False


def match_documents(
    borrowers: list[BorrowerRef], documents: list[DocumentNames]
) -> list[DocumentAssignment]:
    """Assign each document to its borrower(s) — pure, conservative, testable."""
    out: list[DocumentAssignment] = []
    for doc in documents:
        if not doc.names:
            out.append(DocumentAssignment(doc.document_id, (), "unassigned", "no_name"))
            continue
        best_per_borrower: dict[str, BorrowerLink] = {}
        any_ambiguous = False
        for name in doc.names:
            link, ambiguous = _identify(name, borrowers)
            any_ambiguous = any_ambiguous or ambiguous
            if link is not None:
                prior = best_per_borrower.get(link.borrower_id)
                if prior is None or link.confidence > prior.confidence:
                    best_per_borrower[link.borrower_id] = link
        links = tuple(sorted(best_per_borrower.values(), key=lambda x: x.borrower_id))
        if links:
            status = "joint" if len(links) > 1 else "assigned"
            out.append(DocumentAssignment(doc.document_id, links, status, None))
        else:
            note = "ambiguous" if any_ambiguous else "no_match"
            out.append(DocumentAssignment(doc.document_id, (), "unassigned", note))
    return out


# --------------------------------------------------------------------------- #
# DB-facing: extract names, run the matcher, persist the links
# --------------------------------------------------------------------------- #


def _extract_names(extracted_data: dict[str, Any]) -> tuple[str, ...]:
    """The candidate owner names on a document (from its typed-core extraction), joint-split."""
    names: list[str] = []
    seen: set[str] = set()
    for key in _OWNER_NAME_KEYS:
        node = extracted_data.get(key)
        value = node.get("value") if isinstance(node, dict) else None
        if not value:
            continue
        for part in _JOINT_SPLIT.split(str(value)):
            candidate = part.strip()
            norm = " ".join(_tokens(candidate))
            if candidate and norm and norm not in seen:
                seen.add(norm)
                names.append(candidate)
    return tuple(names)


async def assign_documents_to_borrowers(
    db: AsyncSession, loan_file: LoanFile
) -> list[DocumentAssignment]:
    """Match the file's documents to its borrowers and REPLACE the persisted links (LP-118.8).

    Loads the borrowers + documents (with current extraction), runs the pure matcher, deletes the
    file's existing links, inserts the fresh ones, and records the unassigned reason on
    ``Document.borrower_match_note``. ``flush`` only; the caller owns the transaction. Reads only the
    identity data; executes no verification rule. Metadata-only logging (no names — PII).
    """
    borrowers = (
        (
            await db.execute(
                only_active(
                    select(Borrower)
                    .where(Borrower.loan_file_id == loan_file.id)
                    .order_by(Borrower.borrower_position),
                    Borrower,
                )
            )
        )
        .scalars()
        .all()
    )
    documents = (
        (
            await db.execute(
                only_active(
                    select(Document)
                    .where(Document.loan_file_id == loan_file.id)
                    .options(selectinload(Document.extractions))
                    .order_by(Document.created_at, Document.id),
                    Document,
                )
            )
        )
        .scalars()
        .all()
    )

    borrower_refs = [
        BorrowerRef(
            id=str(b.id),
            first_name=b.first_name,
            last_name=b.last_name,
            full_name=f"{b.first_name} {b.last_name}".strip() or None,
        )
        for b in borrowers
    ]
    doc_names = [
        DocumentNames(
            document_id=str(doc.id),
            names=_extract_names(
                doc.current_extraction.extracted_data if doc.current_extraction else {}
            ),
        )
        for doc in documents
    ]

    assignments = match_documents(borrower_refs, doc_names)

    # Replace the file's links (idempotent re-match). Delete then insert.
    doc_ids = [doc.id for doc in documents]
    if doc_ids:
        await db.execute(
            delete(DocumentBorrowerLink).where(DocumentBorrowerLink.document_id.in_(doc_ids))
        )
    by_note = {a.document_id: a.note for a in assignments}
    for doc in documents:
        doc.borrower_match_note = by_note.get(str(doc.id))
    for a in assignments:
        for link in a.links:
            db.add(
                DocumentBorrowerLink(
                    document_id=UUID(a.document_id),
                    borrower_id=UUID(link.borrower_id),
                    confidence=link.confidence,
                    method=link.method,
                )
            )
    await db.flush()

    counts = {"assigned": 0, "joint": 0, "unassigned": 0}
    for a in assignments:
        counts[a.status] += 1
    logger.info(
        "document_borrower_matching_done",
        loan_file_id=str(loan_file.id),
        documents=len(assignments),
        **counts,  # counts only — never names (PII)
    )
    return assignments
