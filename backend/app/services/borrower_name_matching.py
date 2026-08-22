"""Deterministic document→borrower name matching (LP-202, ADR-239).

Pure, **no AI, no DB**: given the name(s) a document asserts and the loan file's
borrowers, decide which borrower(s) the document is about. Given the same inputs
it returns the same links every time.

The approach is normalize + score:

* **Normalize** — accents stripped, lowercased, punctuation dropped, ``"Last,
  First"`` reordered, name suffixes (Jr/Sr/III) and joint connectors (``and`` /
  ``&``) removed, tokenized.
* **Score** each borrower against the asserted name. The **last name is the
  anchor**: if it doesn't match (exact or close-fuzzy) there is no link, full
  stop — a shared first name is never enough. The first name then matches by
  exact / nickname (a small common-nickname map) / initial / fuzzy.
* **Threshold** — :data:`NAME_MATCH_THRESHOLD`. Below it, **no link is emitted**;
  a low-similarity near-miss is a correct no-match, never forced to the "closest"
  borrower.
* **Joint documents** — the asserted string may contain several people (a joint
  bank statement / joint tax return). Each borrower is scored independently
  against the whole string, so more than one borrower can match one document.

The result carries a ``method`` tag (``exact`` / ``normalized`` / ``fuzzy``) and a
``confidence`` score, for storage + later review. Nothing here fabricates a match.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any
from uuid import UUID

from app.models.document_borrower_link import MatchMethod

# The similarity at/above which a (document, borrower) pair becomes a link. Tuned
# so exact/nickname/initial matches clear it and genuine near-misses (a one-letter
# surname typo, a shared surname with a different first name) fall below it. A
# named, documented constant so it is easy to find and adjust.
NAME_MATCH_THRESHOLD = 0.80

# The last name is the anchor: below this last-name similarity there is no match,
# regardless of the first name. Prevents "different person, same first name".
_LAST_NAME_MIN = 0.85

# Minimum token similarity for a first/last token to count as a fuzzy match.
_FUZZY_MIN = 0.85

# Fuzzy needs enough characters for an edit to be meaningful: a single edit on a
# 3-4 char name (Han/Hahn, Lee/Li, Ng/Ngo) sits ABOVE _FUZZY_MIN, so short tokens
# must match exactly or by nickname — never fuzzily — or distinct short surnames
# would falsely clear the anchor and link different families.
_FUZZY_MIN_LEN = 5

# Trailing generational suffixes dropped during normalization (not name content).
_SUFFIXES = frozenset({"jr", "sr", "ii", "iii", "iv", "v"})

# Joint / alias connectors dropped so a joint string tokenizes to its people.
_CONNECTORS = frozenset({"and", "or", "aka", "fka", "n"})

# A small, common English nickname map (canonical → nicknames). Deliberately
# modest — it is cheap, high-precision, and documented; not an exhaustive name
# database. Matching is symmetric via the canonical form.
_NICKNAMES: dict[str, set[str]] = {
    "robert": {"rob", "bob", "bobby", "robbie"},
    "william": {"will", "bill", "billy", "willy"},
    "richard": {"rich", "rick", "ricky", "dick"},
    "james": {"jim", "jimmy", "jamie"},
    "john": {"johnny", "jack", "jon"},
    "michael": {"mike", "mikey", "mick"},
    "david": {"dave", "davey"},
    "joseph": {"joe", "joey"},
    "charles": {"charlie", "chuck"},
    "thomas": {"tom", "tommy"},
    "christopher": {"chris"},
    "daniel": {"dan", "danny"},
    "matthew": {"matt"},
    "anthony": {"tony"},
    "donald": {"don", "donnie"},
    "steven": {"steve"},
    "stephen": {"steve"},
    "edward": {"ed", "eddie", "ted", "teddy"},
    "andrew": {"andy", "drew"},
    "joshua": {"josh"},
    "kenneth": {"ken", "kenny"},
    "benjamin": {"ben", "benny"},
    "samuel": {"sam", "sammy"},
    "nicholas": {"nick", "nicky"},
    "alexander": {"alex", "al"},
    "timothy": {"tim", "timmy"},
    "elizabeth": {"liz", "beth", "betty", "lizzie", "eliza"},
    "margaret": {"maggie", "meg", "peggy", "peg"},
    "katherine": {"kate", "katie", "kathy", "kat"},
    "catherine": {"kate", "katie", "cathy"},
    "jennifer": {"jen", "jenny"},
    "jessica": {"jess", "jessie"},
    "patricia": {"pat", "patty", "trish", "tricia"},
    "deborah": {"deb", "debbie"},
    "susan": {"sue", "susie"},
    "barbara": {"barb", "babs"},
    "rebecca": {"becca", "becky"},
    "cynthia": {"cindy"},
    "kimberly": {"kim"},
    "stephanie": {"steph"},
    "priyanka": {"priya"},
}

# A nickname → the SET of canonical names it can stand for. A nickname shared by
# two canonicals (``steve`` → steven AND stephen; ``kate`` → katherine AND
# catherine) maps to BOTH, so neither canonical silently loses the nickname (a
# plain dict with setdefault dropped the second one — Stephen/Catherine never
# matched ``Steve``/``Kate``). Two names nickname-match iff their canonical sets
# intersect.
_NICK_TO_CANONS: dict[str, set[str]] = {}
for _canon_name, _nicks in _NICKNAMES.items():
    for _n in _nicks:
        _NICK_TO_CANONS.setdefault(_n, set()).add(_canon_name)


# The borrower-name field(s) each document type asserts, most authoritative first.
# Counterparties (gift donor, purchase seller) are deliberately EXCLUDED so they
# never mislink. A type absent here asserts no borrower name → no candidate.
BORROWER_NAME_FIELDS: dict[str, tuple[str, ...]] = {
    "pay_stub": ("employee_name",),
    "w2": ("employee_name",),
    "voe": ("employee_name",),
    "bank_statement": ("account_holder_name",),
    "investment_account": ("account_holder",),
    "retirement_account": ("account_holder",),
    "drivers_license": ("full_name",),
    "gift_letter": ("recipient_name",),  # NOT donor_name (the counterparty)
    "purchase_agreement": ("buyer_name",),  # NOT seller_name (the counterparty)
    "1099": ("recipient_name",),  # the EXTRACTORS/catalog slug is "1099", not "form_1099"
    "tax_return": ("taxpayer_names",),
    "homeowners_insurance": ("named_insured",),  # added in LP-202 Phase 1
    "mortgage_statement": ("borrower_name",),  # added in LP-202 Phase 1
    "property_tax_bill": ("owner_name",),  # added in LP-202 Phase 1
    "hoa_statement": ("owner_name",),  # added in LP-202 Phase 1
}


@dataclass(frozen=True)
class BorrowerName:
    """A borrower's identity for matching (DB-free input)."""

    borrower_id: UUID
    first_name: str | None
    middle_name: str | None
    last_name: str | None


@dataclass(frozen=True)
class MatchResult:
    """One (document, borrower) link the matcher produced."""

    borrower_id: UUID
    confidence: float
    method: MatchMethod  # the one CHECK-constrained vocabulary, shared with the DB row


def _canons(token: str) -> set[str]:
    """Every canonical name a token could stand for (itself + any it nicknames)."""
    return _NICK_TO_CANONS.get(token, set()) | {token}


def _strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def normalize_name(raw: str | None) -> list[str]:
    """Normalize a name to a list of comparable tokens (empty when no name)."""
    if not raw or not isinstance(raw, str):
        return []
    text = _strip_accents(raw).lower()
    # "Last, First" → "First Last" (only the simple two-part case).
    if "," in text:
        parts = [p.strip() for p in text.split(",")]
        text = (
            f"{parts[1]} {parts[0]}" if len(parts) == 2 and all(parts) else text.replace(",", " ")
        )
    text = re.sub(r"[^a-z0-9&\s]", " ", text)  # keep & (a connector), drop other punctuation
    tokens = [t for t in text.split() if t]
    return [t for t in tokens if t not in _SUFFIXES and t not in _CONNECTORS]


def _adjacent_joins(tokens: list[str]) -> set[str]:
    """Concatenations of two or more ADJACENT tokens (bug-001).

    A name is written one way on the application and another on the document, and the difference is
    often only WHERE THE SPACES ARE: `Vidulasrri` on the 1003 and `Vidula Srri` on every pay stub and
    bank statement; `Maryann` and `Mary Ann`; `Delacruz` and `De La Cruz`. Token-by-token matching
    cannot see through that — `vidulasrri` is never close enough to `vidula` for the fuzzy ratio, so
    a file whose surname anchors at 1.0 links NOTHING.

    ADJACENT only, and used for EXACT membership only (see `_best_token_match`). Both restrictions
    are precision, not tidiness: joining non-adjacent tokens would let a middle name be spliced onto a
    surname, and allowing a join to also match FUZZILY would stack a re-spacing on top of an edit,
    which is two liberties at once on the evidence that two people are the same person.
    """
    joins: set[str] = set()
    for i in range(len(tokens)):
        acc = tokens[i]
        for j in range(i + 1, len(tokens)):
            acc += tokens[j]
            joins.add(acc)
    return joins


def _best_token_match(borrower_tok: str, doc_tokens: list[str]) -> tuple[float, str]:
    """Best ``(score, kind)`` of a borrower token against any document token.

    A token that does not clear a *real* match test scores ``0.0`` / ``"none"`` —
    a non-matching component must contribute **nothing** to the combined score, so
    a strong surname can never drag a failed first name over the threshold (and a
    weak surname can never clear the anchor on a raw ratio). Two rules make this
    precision-safe against the same-surname family case:

    * **A bare initial confers no match.** A single-letter token (a stray middle
      initial, or a first name given only as an initial) is not evidence that two
      full names are the same person, so it never scores as a match.
    * **Short names must match exactly, not fuzzily.** ``difflib`` inflates the
      ratio of short near-misses (Han/Hahn), so fuzzy only counts when both tokens
      are at least ``_FUZZY_MIN_LEN`` characters (:data:`_FUZZY_MIN_LEN`).
    """
    # A bare initial confers no match — enforced HERE, before the exact-membership
    # test, so a single-letter borrower token can't score 1.0 by landing on a stray
    # single-letter doc token (a middle initial) and forge a same-person link.
    if len(borrower_tok) < 2:
        return 0.0, "none"
    if borrower_tok in doc_tokens:
        return 1.0, "exact"
    bc = _canons(borrower_tok)
    if any(bc & _canons(t) for t in doc_tokens):
        return 0.95, "nickname"
    # bug-001 — the document spells as several tokens what the application spells as one
    # (`Vidula Srri` vs `Vidulasrri`). EXACT membership against adjacent joins only: the name is the
    # same name, so it scores as one, but a join is never allowed to also match fuzzily.
    if borrower_tok in _adjacent_joins(doc_tokens):
        return 1.0, "exact"
    best_ratio, best_tok = 0.0, ""
    for t in doc_tokens:
        ratio = SequenceMatcher(None, borrower_tok, t).ratio()
        if ratio > best_ratio:
            best_ratio, best_tok = ratio, t
    if best_ratio >= _FUZZY_MIN and min(len(borrower_tok), len(best_tok)) >= _FUZZY_MIN_LEN:
        return best_ratio, "fuzzy"
    return 0.0, "none"  # below the bar / too short / bare initial → not a match


def _score_one(borrower: BorrowerName, doc_tokens: list[str]) -> MatchResult | None:
    """Score one borrower against one already-tokenized asserted name."""
    if not doc_tokens:
        return None
    last_tokens = normalize_name(borrower.last_name)
    if not last_tokens:
        return None  # no surname → no anchor → no match
    last_tok = last_tokens[-1]
    first_tokens = normalize_name(borrower.first_name)
    first_tok = first_tokens[0] if first_tokens else None

    last_score, last_kind = _best_token_match(last_tok, doc_tokens)
    # bug-001 — the same asymmetry on the ANCHOR. `last_tok` is the LAST token of the surname, so an
    # application spelling `Van Der Berg` anchors on `berg` alone and a document printing
    # `VANDERBERG` fails, even though the two are one surname. Tried only when the plain token did
    # not already match, and only as an EXACT membership test — the anchor is what stops two
    # different families linking, so it is never widened fuzzily.
    if last_score < 1.0 and len(last_tokens) > 1 and "".join(last_tokens) in doc_tokens:
        last_score, last_kind = 1.0, "exact"
    if last_score < _LAST_NAME_MIN:
        return None  # anchor failed

    if first_tok is not None:
        first_score, first_kind = _best_token_match(first_tok, doc_tokens)
        # bug-001, the OTHER direction: the APPLICATION spells as several tokens what the document
        # spells as one (`Mary Ann` on the 1003, `MARYANN` on the pay stub). Only `first_tokens[0]`
        # was ever scored, so the rest of a multi-token given name was invisible.
        if first_score < 1.0 and len(first_tokens) > 1:
            joined = "".join(first_tokens)
            if joined in doc_tokens:
                first_score, first_kind = 1.0, "exact"
    else:
        first_score, first_kind = 1.0, "exact"  # no known first name → last-only

    combined = round(0.5 * last_score + 0.5 * first_score, 4)
    if combined < NAME_MATCH_THRESHOLD:
        return None

    full_tokens = normalize_name(
        " ".join(p for p in (borrower.first_name, borrower.middle_name, borrower.last_name) if p)
    )
    method: MatchMethod
    if full_tokens and set(full_tokens) == set(doc_tokens):
        method = MatchMethod.EXACT
    elif last_kind in {"exact", "nickname"} and first_kind in {"exact", "nickname"}:
        method = MatchMethod.NORMALIZED
    else:
        method = MatchMethod.FUZZY

    return MatchResult(
        borrower_id=borrower.borrower_id, confidence=round(combined, 2), method=method
    )


def match_document(asserted_names: list[str], borrowers: list[BorrowerName]) -> list[MatchResult]:
    """Match a document's asserted name(s) to the loan file's borrowers.

    Returns one :class:`MatchResult` per borrower that clears
    :data:`NAME_MATCH_THRESHOLD` (zero, one, or many — many for a joint document).
    A borrower is scored against every asserted string; the best wins.
    """
    token_lists = [normalize_name(name) for name in asserted_names]
    token_lists = [t for t in token_lists if t]
    if not token_lists:
        return []

    results: list[MatchResult] = []
    for borrower in borrowers:
        best: MatchResult | None = None
        for doc_tokens in token_lists:
            candidate = _score_one(borrower, doc_tokens)
            if candidate is not None and (best is None or candidate.confidence > best.confidence):
                best = candidate
        if best is not None:
            results.append(best)
    return results


def asserted_names_for(extracted_data: dict[str, Any], document_type: str | None) -> list[str]:
    """Pull the borrower-name string(s) a document asserts from its extracted_data.

    Reads only the borrower-name field(s) registered for the type (counterparties
    excluded). Returns the non-empty values; empty when the type asserts no
    borrower name or the field is absent — an honest "no name".
    """
    if not document_type:
        return []
    names: list[str] = []
    for field in BORROWER_NAME_FIELDS.get(document_type, ()):
        entry = extracted_data.get(field)
        value = entry.get("value") if isinstance(entry, dict) else entry
        if isinstance(value, str) and value.strip():
            names.append(value.strip())
    return names
