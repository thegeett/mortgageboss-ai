"""Composing the framing of a borrower document request (LP-810), and refusing what must not go out.

FOLLOWS `ai/finding_prose.py` LAYER FOR LAYER: a facts dataclass that is the only permitted input, a
strict parse, a set of DETERMINISTIC guards, one shared `rejection_reason` the compose path and the
cache filter both run, and one corrective retry before the caller falls back to the plain template.

TWO THINGS ARE DIFFERENT HERE, AND BOTH ARE BECAUSE THE READER IS A BORROWER.

**The model does not write the document instructions.** It writes an opening, a bridge and a closing;
the list of documents is interpolated deterministically from LP-800's catalog. The plan asked for the
"never invents an instruction" rule to be enforced the way `unsupported_numbers_in` enforces numbers,
and this is that rule made STRUCTURAL instead — a check would have to decide whether a reworded
instruction was still supported, which is a judgement, and the numbers check works precisely because
it is not one. What remains checkable is checked: `states_a_requirement` refuses an obligation
sentence anywhere in the model's three fields, because in this design there is no legitimate reason
for one to be there.

**The compliance scanner is regulatory, not stylistic.** `finding_prose`'s guards keep a processor
from reading something silly. These keep a lender from making a statement it is not allowed to make.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field

from app.ai.client import AIClientError, complete
from app.ai.finding_prose import leaked_identifiers_in, unsupported_numbers_in
from app.ai.prompt_loader import load_prompt
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_MAX_TOKENS = 800

SYSTEM_PROMPT = load_prompt("communication/borrower_request.txt")


@dataclass(frozen=True)
class DraftFacts:
    """The ONLY input a composition may draw on. Anything absent here cannot appear in the output.

    DELIBERATELY NARROW, and the narrowness is the ticket's central design decision rather than an
    economy. bug-008: a wide bundle reworded every draft whenever anything in it changed, so a
    processor mid-edit watched paragraphs move under their cursor. The requested documents, the
    borrower's first name and the file's basics — nothing else. Not the findings, not the document
    corpus, not the loan's numbers.
    """

    borrower_first_name: str
    loan_reference: str
    #: The borrower-facing labels of what is being asked for, in the order they will be listed.
    #: Labels only — the instructions themselves never reach the model, because the model is not
    #: writing them.
    requested_labels: tuple[str, ...] = ()
    #: LP-839 — the processor's own notes on what is being asked for, one per note, unordered pairs
    #: with `requested_labels` deliberately NOT reconstructed here.
    #:
    #: PART OF THE BUNDLE BECAUSE IT IS PART OF THE ASK. A note ("the March one specifically, not
    #: February") is text the BORROWER now reads — `_document_line` renders it under its document —
    #: so the model seeing it is not a new exposure, and a composition written as though it were not
    #: there would open a message it does not match.
    #:
    #: AND BECAUSE THE CACHE KEY IS THE POINT. `cache_key` is a digest of this payload: without the
    #: notes in it, adding one leaves the key unchanged, `_cached_prose` hits, and no composition
    #: runs at all — the framing would stay written for a request that has since changed.
    #:
    #: The guard still applies to the OUTPUT: a note naming a money amount cannot make the model
    #: state one, because `rejection_reason` reads the composition and falls back to the plain
    #: template when it does.
    requested_notes: tuple[str, ...] = ()
    #: True when this is a follow-up rather than a first ask, which changes how an opening reads.
    is_follow_up: bool = False
    facts: dict[str, str] = field(default_factory=dict)

    def to_json(self) -> str:
        payload: dict[str, object] = {
            "borrower_first_name": self.borrower_first_name,
            "loan_reference": self.loan_reference,
            "requested": list(self.requested_labels),
            "notes": list(self.requested_notes),
            "is_follow_up": self.is_follow_up,
        }
        if self.facts:
            payload["facts"] = self.facts
        return json.dumps(payload, sort_keys=True)

    def cache_key(self) -> str:
        """Identical facts → identical key → identical wording, without a second model call."""
        return hashlib.sha256(self.to_json().encode()).hexdigest()


@dataclass(frozen=True)
class DraftComposition:
    """The three fields the model writes. Everything else in the email comes from elsewhere."""

    opening: str
    bridge: str
    closing: str

    @property
    def message(self) -> str:
        return f"{self.opening}\n\n{self.bridge}\n\n{self.closing}"


# --------------------------------------------------------------------------------------------- #
# The compliance scanner — deterministic, never a prompt instruction
# --------------------------------------------------------------------------------------------- #
# A prompt instruction is a hope; a check is a guarantee. Every pattern below matches a shape that is
# a violation WHEREVER it appears in a document-request email, so none of them can turn away a
# legitimate sentence — the property that keeps a guard from quietly costing more than it saves.

#: Any percentage, and the words for one. Reg Z governs how a rate may be stated; a document request
#: has no business stating one at all, so the guard is "none" rather than "correctly disclosed".
_RATE = re.compile(r"\d+(?:\.\d+)?\s*%|\bAPR\b|\bannual percentage rate\b|\binterest rate\b", re.I)

#: Any money amount. Reg Z §1026.24(d)(1) makes "the amount of any payment", "the amount or
#: percentage of any downpayment" and "the amount of any finance charge" triggering terms — stating
#: one in an advertisement obliges a set of further disclosures no email carries. Whether a request
#: to an existing applicant is an "advertisement" is a question this code should not be deciding on
#: the fly, so the scanner refuses the amount rather than the argument.
_MONEY = re.compile(r"[$£€]\s?\d|\b\d[\d,]*(?:\.\d{2})?\s*dollars\b", re.I)

#: §1026.24(d)(1)'s triggering terms in their PHRASE form, plus one house rule. Verified against the
#: regulation's own text at consumerfinance.gov/rules-policy/regulations/1026/24 on 2026-09-07, under
#: the heading "Advertisement of terms that require additional disclosures" — the four are
#: (i) the amount or percentage of any downpayment, (ii) the number of payments or period of
#: repayment, (iii) the amount of any payment, (iv) the amount of any finance charge.
#:
#: `closing costs` IS NOT ONE OF THE FOUR and is refused anyway, as a house rule rather than as a
#: requirement of this section: a document request has no reason to quote them, and quoting them
#: invites the payment-amount conversation the four terms govern. Named separately so nobody reads
#: the regulation as demanding it, and so removing it is a product decision rather than a compliance
#: one.
_TRIGGERING_TERMS = re.compile(
    r"\b(?:down\s?payment|monthly payment|number of payments|period of repayment|"
    r"repayment period|finance charge|closing costs?)\b",
    re.I,
)

#: Approval, denial and commitment language. A processor may not tell a borrower where their loan
#: stands with the underwriter, and a drafted email is exactly where a reassuring phrase gets added.
_COMMITMENT = re.compile(
    r"\b(?:pre-?approved|approved|approval|denied|denial|declined|"
    r"committed|commitment|guarantee[ds]?|cleared to close|underwrit(?:ten|ing) decision)\b",
    re.I,
)

#: Settlement-service recommendations — RESPA territory. Matched as a RECOMMENDATION plus a service,
#: not either alone: "your title company will send it" is ordinary and must not be refused.
_RECOMMENDS = re.compile(
    r"\b(?:we recommend|you should use|we (?:use|prefer|suggest)|go with)\b", re.I
)
_SETTLEMENT_SERVICE = re.compile(
    r"\b(?:title (?:company|agent)|escrow (?:company|agent|officer)|closing attorney|"
    r"settlement agent|insurance agent|home ?inspector|appraiser)\b",
    re.I,
)

#: Payment routing. Nine consecutive digits is an ABA routing number; the phrases cover the rest.
_ROUTING = re.compile(
    r"\b\d{9}\b|\b(?:routing number|account number|wire (?:instructions|transfer))\b", re.I
)

#: An obligation sentence. In this design the model does not write instructions at all — the document
#: list is interpolated from the catalog — so an obligation phrase in its three fields is always the
#: model having invented one. This is the "never invents an instruction" rule, made decidable by
#: removing the legitimate case rather than by trying to judge a reworded one.
_REQUIREMENT = re.compile(
    r"\b(?:must (?:be|show|include|contain|cover)|make sure|be sure to|needs? to (?:show|include)|"
    r"we (?:cannot|can't|do not|don't) accept|all pages|every page)\b",
    re.I,
)


def states_a_rate(composition: DraftComposition) -> bool:
    return bool(_RATE.search(composition.message))


def states_a_money_amount(composition: DraftComposition) -> bool:
    return bool(_MONEY.search(composition.message))


def states_a_triggering_term(composition: DraftComposition) -> bool:
    """12 CFR §1026.24(d)(1)'s triggering terms in phrase form, plus `closing costs` as a house rule.

    See the pattern's own comment: the regulation lists four, `closing costs` is not among them, and
    the distinction matters because one of those is a compliance obligation and the other is ours.
    """
    return bool(_TRIGGERING_TERMS.search(composition.message))


def states_a_commitment(composition: DraftComposition) -> bool:
    return bool(_COMMITMENT.search(composition.message))


def recommends_a_settlement_service(composition: DraftComposition) -> bool:
    """A recommendation AND a service, in the same message — either alone is ordinary English."""
    text = composition.message
    return bool(_RECOMMENDS.search(text) and _SETTLEMENT_SERVICE.search(text))


def states_payment_routing(composition: DraftComposition) -> bool:
    return bool(_ROUTING.search(composition.message))


def states_a_requirement(composition: DraftComposition) -> bool:
    """The model wrote a document instruction. It is not supposed to write any."""
    return bool(_REQUIREMENT.search(composition.message))


def rejection_reason(facts: DraftFacts, composition: DraftComposition) -> str | None:
    """Why this composition must not reach a borrower, or None if it may.

    ONE function, called from TWO places — the compose path and the cache filter — for the reason
    LP-601 established the hard way: `compose` runs only on a cache MISS, so a composition stored
    before a guard existed is served forever and the guard never sees it. Filtering the cache through
    the same verdict means any guard added later heals stored prose on the next run.

    Order is deliberate: the regulatory refusals come before the stylistic ones, so a message that is
    both reports the reason that matters.
    """
    if states_a_rate(composition):
        return "rate"
    if states_a_money_amount(composition):
        return "money_amount"
    if states_a_triggering_term(composition):
        return "triggering_term"
    if states_a_commitment(composition):
        return "commitment"
    if recommends_a_settlement_service(composition):
        return "settlement_service"
    if states_payment_routing(composition):
        return "payment_routing"
    if states_a_requirement(composition):
        return "invented_instruction"
    if leaked_identifiers_in(composition.message):
        return "identifier"
    # The hallucination check, shared with `finding_prose` rather than re-derived — the number grammar
    # is a decision, and a second copy of it drifts (bug-006). `requested_labels` is unlicensed: a
    # label like "W-2s — the last two years" would otherwise license "2" anywhere in the output, the
    # same hole LP-597 and LP-613 each cost a shipped defect to find.
    # LP-839 — `requested_notes` JOINS THE UNLICENSED SET, and it has to. Adding notes to the facts
    # put them in `to_json()`, which is what licenses a number — so a processor typing "the one
    # showing the $10,000 deposit" would have licensed "10,000" anywhere in the model's output. A
    # note is the same shape of thing as a label: processor prose that happens to contain digits, and
    # never a fact the model may restate.
    if invented := unsupported_numbers_in(
        facts.to_json(),
        composition.message,
        unlicensed=(*facts.requested_labels, *facts.requested_notes),
    ):
        return f"unsupported_numbers:{len(invented)}"
    return None


#: Rejections worth one more attempt. Every one is the model overreaching rather than the facts being
#: uncomposable, and at temperature 0 the retry carries the reason so it is not the same draw again.
_RETRYABLE = frozenset(
    {
        "rate",
        "money_amount",
        "triggering_term",
        "commitment",
        "settlement_service",
        "payment_routing",
        "invented_instruction",
        "identifier",
        "unsupported_numbers",
        "malformed",
    }
)


def _parse(text: str) -> DraftComposition | None:
    """Defensive parse — a malformed response is a rejected composition, never a partial one."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        payload = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    parts = [payload.get(name) for name in ("opening", "bridge", "closing")]
    if not all(isinstance(part, str) and part.strip() for part in parts):
        return None
    opening, bridge, closing = (str(part).strip() for part in parts)
    return DraftComposition(opening, bridge, closing)


def _user_message(facts: DraftFacts, retry_of: str | None) -> str:
    if retry_of is None:
        return facts.to_json()
    return (
        f"{facts.to_json()}\n\n"
        f"Your previous attempt was rejected: {retry_of}. "
        "Write it again without that."
    )


async def _maybe_retry(
    facts: DraftFacts, reason: str, already_retried: str | None
) -> DraftComposition | None:
    """One retry, and only one — a second rejection means the plain template stands."""
    if already_retried is not None or reason not in _RETRYABLE:
        return None
    return await compose(facts, _retry_of=reason)


async def compose(facts: DraftFacts, *, _retry_of: str | None = None) -> DraftComposition | None:
    """Compose the framing, or ``None`` when the caller should use the plain template.

    Returns None — never raises — for every failure mode: transport, truncation, malformed JSON, and
    any guard rejection. The caller's fallback is LP-817's deterministic render, which is a complete
    email on its own; nothing is degraded by this returning None except the tone.
    """
    try:
        result = await complete(
            model=settings.anthropic_model_reasoning,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": _user_message(facts, _retry_of)}],
            max_tokens=_MAX_TOKENS,
            temperature=0.0,
        )
    except AIClientError:
        logger.warning("email_draft_call_failed")
        return None

    if result.stop_reason == "max_tokens":
        logger.warning("email_draft_truncated", output_tokens=result.output_tokens)
        return None

    composition = _parse(result.text or "")
    if composition is None:
        logger.warning("email_draft_malformed")
        return await _maybe_retry(facts, "malformed", _retry_of)

    # NOT logged with the text. The reason and the fact of rejection are the signal, and the text is
    # a borrower-facing email — the one thing the standing reviewer check says must never be logged.
    if reason := rejection_reason(facts, composition):
        logger.warning("email_draft_rejected", reason=reason)
        return await _maybe_retry(facts, reason.split(":")[0], _retry_of)
    return composition


__all__ = [
    "SYSTEM_PROMPT",
    "DraftComposition",
    "DraftFacts",
    "compose",
    "rejection_reason",
]
