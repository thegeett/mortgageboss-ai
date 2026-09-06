"""LP-634 — the need COMPOSER: a model writes the one sentence that says WHY a document is needed.

THE PAGE THIS EXISTS FOR. The Need List is the first thing a processor opens, and on LF-AWBB it
carried 19 needs and explained almost none of them. The six FLOOR needs — the deterministic ones, the
ones we are surest about — showed a title and a blank space. The five finding-derived needs read
"Required by verification rule(s) CL-1, CR-13, DT-7, ID-5, IH-2, IH-3, PR-6". The eight AI-reasoned
ones carried prose and then a line telling the reader the AI may have misread it.

STRATMOR's document-collection research puts a number on what that costs: failing to clearly explain a
documentation request happens on nearly one in three loans and costs 47 points of NPS. Not explaining
WHY is the most expensive communication failure in this phase of a loan.

ONE VOICE ACROSS ALL THREE ORIGINS, deliberately. A processor should not be able to tell a floor need
from an AI proposal by its prose; `disposition` already carries how much the system is claiming, in one
place instead of two.

**The same four constraints as the finding composer (LP-527), for the same reasons.**

1. **It only ever rewrites.** The need already exists, with a title and a type. Nothing about what is
   REQUESTED depends on this; a failure changes a sentence.
2. **It cannot introduce a fact.** Every number and name in the output must already be in the input
   summary — checked deterministically.
3. **It falls back to what is stored**, which for a floor need is a template floor rather than the
   blank that ships today.
4. **It is cached by the hash of its input**, so an unchanged need reads identically next run. Without
   that a processor re-reads a reworded sentence and thinks something changed.

NEVER LOGS THE SUMMARY OR THE OUTPUT — a need's reason names employers, creditors and amounts.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field

from app.ai.client import AIClientError, complete
from app.ai.finding_prose import leaked_identifiers_in, unsupported_numbers_in
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_MAX_TOKENS = 300

SYSTEM_PROMPT = """\
You write ONE short reason explaining why a loan file still needs a document.

A mortgage loan processor reads this on the first page they open. They already know WHAT is being
asked for — the request is the heading above your sentence. Your job is the WHY, and it is the thing
that is missing today.

Return ONLY a JSON object:
{"why": "<one or two plain sentences>"}

RULES, all mandatory:

- NAME THE STATED FACT, WITH ITS NUMBER. The summary carries what the application itself states — the
  employer, the creditor, the payment, the balance, the purpose. Use it. "The application states a
  $438/month lease with Ally Financial" is checkable in one glance at the 1003; "a lease liability is
  stated" is not, and neither is anything vaguer.
- SAY WHAT THE DOCUMENT SETTLES. Not that something asked for it — what it establishes, or what it
  lets the file do. "The payoff statement gives the exact amount due on the closing date." "An
  appraisal confirms the value the loan is based on."
- USE ONLY FACTS IN THE SUMMARY. Never introduce a number, date, name, year or amount that is not
  there. If a detail would help and is absent, leave it out and write the shorter sentence.
- NEVER MENTION THE MACHINERY. No rule identifiers (CL-1, IN-4), no "the system", no "the AI", no
  "verification", no confidence, no origin. Describe the LOAN FILE. The reason a processor cares is
  never that a check ran; it is that something about this borrower's file requires the document.
  The text you are given is often written for engineers — do not mirror that register, rewrite it as
  something a person says about a document.
- ONE OR TWO SENTENCES. Under 45 words. No markdown, no bullets, no headings.
- PLAIN, CALM, SPECIFIC. Not salesy, not apologetic, not hedged. A colleague explaining a request.

WHAT A GOOD ONE LOOKS LIKE, given a summary that carries the facts each names:

  "The application states base salary from Amazon Com Services LLC, started October 2022. Recent pay
   stubs show current earnings and year-to-date totals."

  "This refinance pays off the United Wholesale Mortgage loan at closing — $588,224 as stated. The
   payoff statement gives the exact amount due on the closing date, including interest and fees."

  "The pay stubs and W-2s show income, but not a continuous employment history or that the position is
   ongoing. A verification of employment states the start date, position and current status directly."

WHAT A BAD ONE LOOKS LIKE, and why:

  "Required by verification rule(s) IN-4, IN-7, IN-8."       -> machinery, and says nothing
  "This document is needed for underwriting."                -> true of everything, explains nothing
  "The borrower's 2023 tax return shows $84,000 of income."  -> invented; the summary said neither"""


@dataclass(frozen=True)
class NeedFacts:
    """The ONLY input a reason may draw on. Anything absent here cannot appear in the output."""

    #: What is being asked for — the heading the reason sits under, so it need not be restated.
    request: str
    #: The document kind, in the catalog's words, or None for a free-form ask.
    document_kind: str | None
    #: WHY THE NEED EXISTS, as whatever produced it recorded: a floor rule's trigger, the rules that
    #: asked, or the model's own earlier prose. Engineering register on purpose — turning it into a
    #: processor's sentence is the whole job.
    trigger: str
    #: The application's own data, already in a processor's vocabulary. `_file_facts` builds it.
    loan: dict[str, str] = field(default_factory=dict)
    employment: tuple[str, ...] = ()
    #: bug-008 — WHICH KINDS of income the application states (Base, Bonus, Commission, Self
    #: Employment). `_file_facts` was already paying for this query and then dropping it on the floor:
    #: `summarize` never passed it and this dataclass had no field for it. It is what lets an income
    #: reason say which earnings the document has to evidence.
    income_types: tuple[str, ...] = ()
    liabilities: tuple[str, ...] = ()
    assets: tuple[str, ...] = ()
    #: Which KINDS of document the file already holds — so a reason can say "the pay stubs show income
    #: but not continuity" without inventing a corpus, and never asks for something already there.
    documents_on_file: tuple[str, ...] = ()

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, ensure_ascii=False)

    def cache_key(self) -> str:
        """Identical facts → identical key → identical prose, without a second model call."""
        return hashlib.sha256(self.to_json().encode()).hexdigest()


#: Rule ids (CL-1, IN-13, DT-6) and the words that name our own plumbing. A reason carrying any of
#: these has described the software instead of the file — the register LP-527 spent four tickets
#: removing from findings, and which needs have been shipping untouched.
#:
#: bug-008 — THE PREFIXES ARE THE REAL ONES, not "any two capitals and a number". Mortgage forms are
#: named that way too: `HO-6` is a unit owner's walls-in policy (`specs/IH-7.yaml`,
#: `classification_prompt.py`) and `HO-3` a homeowner's. A correct condo hazard-insurance reason —
#: "the project's master policy does not cover the unit interior; an HO-6 walls-in policy does" — was
#: rejected as machinery talk, retried, rejected again, and dropped, leaving the need blank. The
#: prefixes are the spec-file families; a new family adds itself here.
_RULE_ID = re.compile(r"\b(?:AS|AU|CL|CO|CR|DT|FR|ID|IH|IN|LO|MI|OC|PC|PE|PR|RE|TI)-\d{1,3}\b")
#: bug-008 — `origin` and `confidence` were on this list as BARE NOUNS and are not. The finding
#: composer's equivalent carries a comment reading "NARROW ON PURPOSE — only phrases that name the
#: SOFTWARE AS AN ACTOR", and two ordinary English words are not that: "a letter explaining the
#: origin of the $12,000 deposit" is the exact sentence a source-of-funds need wants, and it was
#: rejected twice and dropped. The phrases that name our plumbing are still here.
_MACHINERY = re.compile(
    r"\b(?:the system|the ai|verification rule|rule engine|the engine|couldn'?t[- ]check|"
    r"needs[- ]item|the model|confidence score|load[- ]bearing|need origin)\b",
    re.IGNORECASE,
)


def machinery_talk_in(text: str) -> bool:
    """Does this reason describe the software rather than the loan file?"""
    return bool(_RULE_ID.search(text) or _MACHINERY.search(text))


def rejection_reason(facts: NeedFacts, why: str) -> str | None:
    """Why this reason must not reach a processor, or None if it may.

    ONE function, called on a fresh composition AND on a cached one — LP-601's lesson, which cost DT-8
    a fix that was right and unreachable because `compose` runs only on a cache miss and a stored
    composition never saw the guard added after it.
    """
    if not why.strip():
        return "empty"
    if len(why.split()) > 60:
        return "too_long"
    # IDENTIFIER FIRST. A UUID is mostly digits, so checking numbers ahead of it reported "you
    # invented a number" for a leaked document id — a true statement that sends the retry after the
    # wrong thing, and at temperature 0 the retry is only as good as the sentence it is given.
    if leaked_identifiers_in(why):
        return "identifier"
    if machinery_talk_in(why):
        return "machinery_talk"
    # bug-008 — TWO FIELDS WHOSE DIGITS ARE NAMES, NOT QUANTITIES, and neither may license a number
    # into the output. `documents_on_file` holds catalog labels and several ARE numbers, so a file
    # holding a 1099 licensed the literal "1099" anywhere in the reason (LP-613, by the same route
    # that cost the finding composer the same defect). `trigger` often opens "Required by
    # verification rule(s) CR-13", and the rule ids license their own numerals. Only the RULE IDS are
    # withdrawn from the trigger rather than the whole of it: an AI-reasoned need's trigger carries
    # real amounts ("the $12,000 deposit"), and those are exactly what the reason should quote.
    unlicensed = (str(facts.documents_on_file), " ".join(_RULE_ID.findall(facts.trigger)))
    if invented := unsupported_numbers_in(facts.to_json(), why, unlicensed=unlicensed):
        return f"unsupported_numbers:{len(invented)}"
    return None


#: What to tell the model on a retry. Specific, because "try again" at temperature 0 mostly reproduces
#: the same draw — the appended sentence is what makes the second attempt different from the first.
_REJECTION_GUIDANCE = {
    "unsupported_numbers": (
        "you introduced a number that is not in the summary. Use only figures that appear there, or "
        "none at all."
    ),
    "machinery_talk": (
        "you described the software rather than the loan file — a rule identifier, 'the system', 'the "
        "AI', or a check running. Say what about THIS BORROWER'S FILE makes the document necessary."
    ),
    "identifier": "you included an internal identifier that must never reach a processor. Remove it.",
    "too_long": "it was too long. Two sentences at most, under 45 words.",
    "empty": "you returned nothing. Write the reason.",
}
_RETRYABLE = frozenset(_REJECTION_GUIDANCE)


def _parse(text: str) -> str | None:
    """Defensive parse — a malformed response is a rejected reason, never a partial one."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        payload = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    why = payload.get("why")
    return why.strip() if isinstance(why, str) and why.strip() else None


def _user_message(facts: NeedFacts, retry_of: str | None) -> str:
    if retry_of is None:
        return facts.to_json()
    return (
        f"{facts.to_json()}\n\nYour previous answer was REJECTED for: {_REJECTION_GUIDANCE[retry_of]} "
        "Write it again, obeying that rule exactly."
    )


async def compose(facts: NeedFacts, *, _retry_of: str | None = None) -> str | None:
    """One reason, or None if the model failed or its answer could not be admitted.

    None is a real outcome and not an error: the stored reason stands, which is what makes this pass
    safe to run over a page a processor trusts.
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
        logger.warning("need_prose_ai_failed")  # never the summary
        return None

    why = _parse(result.text)
    if why is None:
        return None if _retry_of else await compose(facts, _retry_of="empty")
    if reason := rejection_reason(facts, why):
        logger.warning("need_prose_rejected", reason=reason)
        if _retry_of is None and reason.split(":")[0] in _RETRYABLE:
            return await compose(facts, _retry_of=reason.split(":")[0])
        return None
    return why


__all__ = ["SYSTEM_PROMPT", "NeedFacts", "compose", "machinery_talk_in", "rejection_reason"]
