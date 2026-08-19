"""LP-527 — the finding COMPOSER: a model rewrites a finding's text from a fixed fact summary.

WHY A MODEL AT ALL. The template floor (LP-524/525) gives every finding an action and a fix, but a
template is static per rule: the gate short-circuits at the FIRST missing input and the wording cannot
see which one it was, so IH-3 has to hedge across "the insurance effective date or the closing date".
And ~65 active rules still have no hand-written text, each of which reads as badly as IH-1 did before
someone sat down with it. Generation solves both — a specific sentence per situation, with no authoring
queue.

⚠️ FOUR CONSTRAINTS MAKE IT SAFE, and none of them is optional.

1. **It only ever rewrites.** The composer runs AFTER the verdict, over a finding that already exists.
   No verdict, no outcome, no tag depends on it. A failure changes prose and nothing else.
2. **It cannot introduce a fact.** Every number, date and quoted string in the output must already
   appear in the input summary — checked deterministically, no model involved. A generation that
   invents "the 2024 W-2" is REJECTED, not repaired.
3. **It falls back to the template**, which is a real sentence rather than a blank. That is why the
   floor was built first: without it, rejection would leave a hole.
4. **It is cached by the hash of its input**, so identical facts produce identical prose. Without that
   the same unchanged problem reads differently every run — a processor re-reads it thinking something
   changed, and cross-run diffing becomes noise.

NEVER LOGS THE SUMMARY OR THE OUTPUT — a finding's text carries borrower names, employers and account
descriptions. Counts and decisions only.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field

from app.ai.client import AIClientError, complete
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_MAX_TOKENS = 400

SYSTEM_PROMPT = """\
You rewrite one mortgage loan-file finding so a loan processor can act on it.

You are given a JSON summary of a finding that a deterministic rule engine has ALREADY decided. Your
job is presentation only: make it clear and specific. You are NOT deciding anything.

Return ONLY a JSON object:
{"action": "<one imperative sentence>", "why": "<one or two sentences>"}

RULES, all mandatory:
- Use ONLY facts present in the summary. Never introduce a number, date, document name, party, year or
  amount that is not there. If a detail would help and is absent, leave it out.
- "action" is what the processor should DO, in the imperative: "Obtain the...", "Confirm that...".
- UNLESS "already_resolved" is true. Then NOTHING IS BEING ASKED FOR — this check PASSED, and the
  two halves change meaning:
    * "action" becomes the RESULT, written as a short positive statement in the processor's terms —
      what is in order, and settled. "Reserves are fully documented." "Employment is verified for the
      full two-year history." "This payment is on the application's liability list."
    * "why" becomes the EVIDENCE that settles it, in the same plain language.
  NEVER begin the action with Obtain, Confirm, Verify, Review, Check, Upload, Provide or Request. A
  task that is already done reads as work outstanding, and it wastes the one signal a passing finding
  exists to give.
  Write it so a processor reading it feels the file is SOLID on this point — not merely that a check
  ran. Say what holds, not what was not found: "The two-year employment history is continuous", not
  "no employment gap was detected".
- The action must make THE SAME REQUEST as "suggested_fix". Sharpen its wording, name the document it
  names — but never ask for a document or a step it does not ask for. "evidence" is context for the
  "why"; it is NOT a list of things to request. A document mentioned there may not exist for this loan.
- "why" explains why this is in their queue, in plain language a processor uses. Name the specific
  document or fact when the summary gives it.
- When "evidence" is present it is what the check actually relied on. USE IT: name those documents and
  facts in the "why" so the reader can check the conclusion instead of taking it on trust. A finding
  asking someone to confirm something must show them what they are confirming.
- Never mention the AI, the rule engine, rule ids, tags, confidence, or that a check "could not run".
  Describe the loan file, not the software. In particular NEVER write "the system" — say what the FILE
  is missing ("the file does not contain a credit report"), not what the software cannot do.
  The problem text you are given is written for engineers and often reads impersonally. Do not
  mirror that register: rewrite it as something a person does about a document.
- Do NOT state or paraphrase a materiality threshold ("exceeds the materiality threshold", "is above
  the floor"). The exact arithmetic is appended to your text automatically, so writing your own version
  says the same thing twice, once vaguely and once precisely. Say what to obtain and why the source
  matters; leave the size of the deposit to the appended clause.
- Plain sentences. No markdown, no bullet points, no headings.
- Keep the whole thing under 60 words."""


@dataclass(frozen=True)
class FactSummary:
    """The ONLY input a composition may draw on. Anything absent here cannot appear in the output."""

    rule_name: str
    subject: str
    problem: str  # the template message — what the engine concluded
    fix: str | None  # the template fix — what it asked for
    facts: dict[str, str] = field(default_factory=dict)  # load-bearing tag label -> value
    # LP-537 — the tag's OWN reasoning, per load-bearing tag. A value alone is a conclusion; this is
    # what the conclusion rested on ("W-2s for 2023 and 2024, pay stubs from March 2025, ..."). DT-7
    # and OC-2 shipped a bare assertion for exactly this reason: the summary carried "complete" and
    # dropped the sentence naming the documents, so the model had nothing specific to write.
    evidence: dict[str, str] = field(default_factory=dict)
    # LP-552 — is this finding a PASS? Without it the composer wrote "Confirm that ..." on a satisfied
    # finding, because the prompt asks for an imperative and nothing said the work was already done.
    # A processor closing a green item should finish the line feeling the file is in order, not be
    # handed a task that has been completed. NOT the verdict enum: the summary still carries no engine
    # vocabulary, only the one fact that changes how a sentence should read.
    settled: bool = False
    guideline: str | None = None

    def to_json(self) -> str:
        payload = {
            "check": self.rule_name,
            "subject": self.subject,
            "problem": self.problem,
            "suggested_fix": self.fix,
            "facts": self.facts,
            "evidence": self.evidence,
            "already_resolved": self.settled,
            "guideline": self.guideline,
        }
        return json.dumps({k: v for k, v in payload.items() if v}, sort_keys=True)

    def cache_key(self) -> str:
        """Identical facts → identical key → identical prose, without a second model call."""
        return hashlib.sha256(self.to_json().encode()).hexdigest()


@dataclass(frozen=True)
class Composition:
    action: str
    why: str

    @property
    def message(self) -> str:
        return f"{self.action}\n\n{self.why}"


# A number of two or more digits, or any 4-digit year — the shapes a hallucination takes on a loan
# file ("the 2024 W-2", "$4,500", "60 days"). Single digits are excluded deliberately: they appear in
# ordinary prose ("one of the two binders") and would reject almost every generation.
_NUMBERS = re.compile(r"\d[\d,.]*\d|\b\d{4}\b")


def _numbers_in(text: str) -> set[str]:
    return {match.group().rstrip(".,").replace(",", "") for match in _NUMBERS.finditer(text)}


def unsupported_numbers(summary: FactSummary, composition: Composition) -> set[str]:
    """Numbers in the output that appear NOWHERE in the input — the hallucination check.

    ⚠️ DETERMINISTIC ON PURPOSE. Asking a model whether a model hallucinated has the same failure mode
    as the thing it is checking. A number is either in the source text or it is not, and that is
    decidable without judgement.
    """
    source = _numbers_in(summary.to_json())
    return _numbers_in(composition.message) - source


# Phrases that describe the SOFTWARE rather than the loan file. The prompt forbids them and a model
# still wrote "The system cannot verify derogatory seasoning requirements" on the first real run — a
# processor does not care what the system can do, only what the file is missing. Enforced rather than
# requested, because a prompt instruction is a hope and a check is a guarantee.
# ⚠️ NARROW ON PURPOSE — only phrases that name the SOFTWARE AS AN ACTOR.
#
# "this check" and "could not be determined" were on this list and are not: both appear in our own
# TEMPLATE messages, which the model receives as its `problem` input, so banning them would reject a
# faithful composition for echoing its source. (They never actually fired — every rejection on the
# first composed run was "the system" — so this is a correctness fix, not a regression fix.)
_MACHINERY = (
    "the system",
    "the rule engine",
    "the engine",
    "the ai ",
    "this software",
    "automated check",
)


def machinery_talk(composition: Composition) -> set[str]:
    """Phrases naming the software instead of the loan file."""
    text = composition.message.lower()
    return {phrase for phrase in _MACHINERY if phrase in text}


# A dotted lowercase identifier — a tag id ("occupancy.consistent_with_signals") or a MISMO path
# ("declaration.intenttooccupytype"). Tag reasoning is written for engineers and is REQUIRED by several
# prompts to cite tags by id, so the evidence text is full of them. They are stripped on the way in and
# rejected on the way out: the strip keeps the model from seeing them, and the check catches the case
# where it produced one anyway.
IDENTIFIER = re.compile(r"\b[a-z][a-z_]{2,}\.[a-z][a-z_.]{2,}[a-z]\b")


def leaked_identifiers(composition: Composition) -> set[str]:
    """Tag ids or MISMO paths in the output — LP-377-B's rule, applied to generated text."""
    return set(IDENTIFIER.findall(composition.message))


# Imperatives that turn a PASS into a chore. Only checked on a settled finding — everywhere else these
# are exactly the words an action should start with.
_ASKING = ("obtain", "confirm", "verify", "review", "check", "upload", "provide", "request", "get ")


def asks_for_work(composition: Composition) -> bool:
    """Does this action ask for something, when nothing is being asked for?"""
    return composition.action.strip().lower().startswith(_ASKING)


def _parse(text: str) -> Composition | None:
    """Defensive parse — a malformed response is a rejected composition, never a partial one."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        payload = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    action, why = payload.get("action"), payload.get("why")
    if not isinstance(action, str) or not isinstance(why, str):
        return None
    action, why = action.strip(), why.strip()
    return Composition(action, why) if action and why else None


async def compose(summary: FactSummary) -> Composition | None:
    """Rewrite one finding, or ``None`` when the caller should keep the template.

    Returns None — never raises — for every failure mode: transport, truncation, malformed JSON, and a
    generation that introduced a fact. The caller's fallback is the template it already has.
    """
    try:
        result = await complete(
            model=settings.anthropic_model_reasoning,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": summary.to_json()}],
            max_tokens=_MAX_TOKENS,
            temperature=0.0,
        )
    except AIClientError:
        logger.warning("finding_prose_call_failed")
        return None

    if result.stop_reason == "max_tokens":
        logger.warning("finding_prose_truncated", output_tokens=result.output_tokens)
        return None

    composition = _parse(result.text or "")
    if composition is None:
        logger.warning("finding_prose_malformed")
        return None

    if invented := unsupported_numbers(summary, composition):
        # NOT logged with the text — the count and the fact of rejection are the signal.
        logger.warning("finding_prose_rejected_unsupported_numbers", count=len(invented))
        return None
    if machinery := machinery_talk(composition):
        logger.warning("finding_prose_rejected_machinery_talk", phrases=sorted(machinery))
        return None
    if leaked := leaked_identifiers(composition):
        logger.warning("finding_prose_rejected_identifier", count=len(leaked))
        return None
    if summary.settled and asks_for_work(composition):
        # The template stands — it already states the pass rather than asking for it.
        logger.warning("finding_prose_rejected_asking_on_a_pass")
        return None
    return composition


__all__ = [
    "SYSTEM_PROMPT",
    "Composition",
    "FactSummary",
    "asks_for_work",
    "compose",
    "leaked_identifiers",
    "machinery_talk",
    "unsupported_numbers",
]
