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
from collections.abc import Iterable
from dataclasses import dataclass, field

from app.ai.client import AIClientError, complete
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_MAX_TOKENS = 400


# Imperatives that turn a PASS into a chore, and — read the other way — the words that make an
# UNSETTLED finding's action an action. One list serving both directions, which is what `asks_for_work`
# is for.
#
# bug-002 — NOT EVERY REMEDIATION IS A DOCUMENT REQUEST. The list held only the words for chasing
# paper, so a fix that CHANGES THE APPLICATION failed the second reading. CR-1's own how_to_fix begins
# "Add the liability to the 1003" and its Apply action is literally `add_liability`; the model wrote
# exactly that, `asks_for_work` saw no approved verb, and all nineteen of LF-AWBB's CR-1 findings were
# rejected as `stating_on_a_review` and shipped the raw template instead. The retry could not rescue
# them either, because `_REJECTION_GUIDANCE` named the same short list back to the model — it was
# steering away from the one verb that fit. 25 of that run's 130 findings went uncomposed.
#
# Widening serves BOTH readings, which is why it is safe to keep one list: a SETTLED finding whose
# action opens "Add …" or "Correct …" is asking for work on a pass, and rejecting it is right.
_ASKING = (
    "obtain",
    "confirm",
    "verify",
    "review",
    "check",
    "upload",
    "provide",
    "request",
    "get ",
    # The application-edit half (bug-002): the remediation is a change to the 1003, not a document.
    "add",
    "correct",
    "disclose",
    "include",
    "update",
    "reconcile",
    "document",
    "remove",
    # bug-005 — THE REST OF THE CORPUS. bug-002 widened this list by hand and stopped when the rule in
    # front of it composed, which is how RE-1 and DT-6 went on shipping raw templates: both open their
    # fixes with "Compare", and nobody had looked at what the OTHER specs open with. Collected from
    # every `how_to_fix` and `couldnt_check_fix` in `rules/specs/`, and `test_every_specs_fix_verb_is_
    # recognised` now fails when a new rule introduces a verb this list does not carry — so the next
    # gap is a red test, not eight findings a processor reads as engineering notes.
    "read",
    "compare",
    "ask",
    "order",
    "identify",
    "recompute",
    "establish",
    "match",
    "exclude",
    "analyze",
    "source",
    "have",
)

#: Verbs a spec opens a fix with that are DELIBERATELY not in `_ASKING`, each because it is also an
#: ordinary way to begin a passing statement, and a word boundary cannot tell the two apart:
#: "Complete the form" against "Complete documentation is in the file", "Total the deposits" against
#: "Total reserves are documented", "Open a claim" against "Open accounts are current". Adding them
#: would trade five findings shipping templates on a review for an unknown number shipping templates
#: on a pass. The rules using them are one apiece; when one of them matters, the fix is to reword the
#: spec's opener, not to loosen this.
_AMBIGUOUS_FIX_VERBS = frozenset({"complete", "total", "open"})


def _asking_phrase() -> str:
    """ "Obtain, Confirm, … or Remove" — the ONE rendering of `_ASKING` every reader of it shares.

    bug-002 — three places named these verbs and only one of them was a list. The system prompt and the
    retry guidance each restated a hand-written subset, so widening `_ASKING` fixed the guard while both
    instructions went on steering the model toward the old words. Same defect twice; rendered once now.
    """
    verbs = [verb.strip().capitalize() for verb in _ASKING]
    return ", ".join(verbs[:-1]) + f" or {verbs[-1]}"


_SYSTEM_PROMPT_TEMPLATE = """\
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
  NEVER begin the action with any of: __ASKING_VERBS__. A
  task that is already done reads as work outstanding, and it wastes the one signal a passing finding
  exists to give.
  Write it so a processor reading it feels the file is SOLID on this point — not merely that a check
  ran. Say what holds, not what was not found: "The two-year employment history is continuous", not
  "no employment gap was detected".
- The action must make THE SAME REQUEST as "suggested_fix". Sharpen its wording, name the document it
  names — but never ask for a document or a step it does not ask for. "evidence" is context for the
  "why"; it is NOT a list of things to request. A document mentioned there may not exist for this loan.
- WHEN "suggested_fix" IS ABSENT, IT IS STILL AN ACTION. Absent narrows the SCOPE of what you may
  ask for; it does not change the FORM. Begin with what the processor must DO about the thing
  "problem" says is missing, and never hand back the problem as a sentence:
    * "The payment history could not be read from the credit report."   <- the PROBLEM, not an action
    * "Obtain a readable payment history for this mortgage."            <- the action
    * "Which statement matches the stated liability cannot be determined." <- the PROBLEM
    * "Identify which statement matches the liability on the application." <- the action
  A check that could not complete is a task: someone has to go and resolve it, and the sentence you
  write is what tells them to. Restating what the engine could not do reads as a status report and
  leaves them nothing to act on.
- WITH "suggested_fix" ABSENT, ask ONLY for what "problem" says is missing, and introduce NO new
  question. A rule that could not complete its check states what it could not resolve; that, and
  nothing beyond it, is the request. Do not reason from the situation to a DIFFERENT thing a
  processor might want to know — another rule may own that question and be asking it already, and two
  instructions about one fact is worse for a processor than one.
  Real example of the failure: given the problem "no mortgage liability stated on the application
  names a holder matching this statement's lender", the right action asks which liability the
  statement belongs to. Asking whether the mortgage "is being paid off at closing or retained" is a
  different question the problem never raised, and another rule was asking it on the same file.
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
- Never write that something is CORRECTLY, properly, appropriately or accurately done. Describe what
  the file shows — "the application marks this mortgage as paid off at closing" — never your view of
  whether a figure, an exclusion or a calculation is right. Saying a value is correctly excluded
  claims the check confirmed it belongs excluded, which is a different and larger statement than the
  one you were given. (Words like "documented" and "verified" ARE fine: they describe the file's
  evidence, not whether someone got something right.)
- "document_kinds_on_file" lists the KINDS of document actually on the file. Use it to choose which
  half of a suggested_fix applies. When the fix offers both "upload X" and "if X is already in the
  file, confirm Y", pick the branch that matches what is listed — do not ask for a document the list
  says is already there. Naming a kind from that list is allowed; asking for a kind that is in
  NEITHER the list nor the suggested_fix is not.
- NEVER ASSERT THAT A DOCUMENT IS IN THE FILE, and never describe agreement "across the documents".
  "documents_on_file" tells you how many documents exist and nothing about what they are. When it is
  0 the file has NO documents at all, so every sentence implying one — "the file contains pay stubs",
  "consistent across all loan documents" — is simply false. Describe what is stated on the
  application, or say plainly what the file does not have.
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
    # LP-597 — HOW MANY DOCUMENTS ARE ON THE FILE. Nothing in this summary used to say, and the model
    # filled the gap: on a file with ZERO documents, IN-2's couldnt_check was rewritten as "The file
    # contains pay stubs, but none of them display a pay date", and OC-1's "agrees with the file's
    # other occupancy DECLARATIONS" became "consistent across all loan DOCUMENTS". Both invented a
    # corpus to explain an absence — which the rule above ("use ONLY facts present in the summary")
    # forbids, and which the model could not obey because the summary never said.
    documents_on_file: int = 0
    # LP-609 — WHICH kinds are on the file, as readable names ("pay stub", "W-2"). The count above
    # stopped the model inventing a corpus on an EMPTY file; it cannot tell "no pay stub" from "pay
    # stubs are here and something else is missing", which is the state IN-3 was in when it asked a
    # processor to upload a document they had just uploaded twice.
    document_kinds_on_file: tuple[str, ...] = ()
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
        # LP-597 — `if v` DROPS A FALSY VALUE, and `documents_on_file: 0` is the single most
        # load-bearing value this summary carries: zero documents is precisely when the model invents
        # a corpus. Filtering it out would have shipped this fix inert. It is added after the filter.
        kept: dict[str, object] = {k: v for k, v in payload.items() if v}
        kept["documents_on_file"] = self.documents_on_file
        # Added after the filter for the same reason as the count: an empty tuple is falsy, and "the
        # file has none of the kinds this rule reads" is exactly the case worth stating.
        kept["document_kinds_on_file"] = list(self.document_kinds_on_file)
        return json.dumps(kept, sort_keys=True)

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
    # ⚠️ THE DOCUMENT COUNT IS NOT A PERMITTED NUMBER. LP-597 injects `documents_on_file` into the
    # summary so the model can stop inventing a corpus — but this check derives its allow-list from
    # that same JSON, so a file with 24 documents silently licensed the token "24" anywhere in the
    # output ("24 months of reserves"). The count is excluded here rather than kept out of the
    # payload, because the model genuinely needs to see it.
    #
    # LP-613 — AND NEITHER ARE THE DOCUMENT-KIND LABELS, for the same reason and by the same route.
    # `document_kinds_on_file` (LP-610) lists kinds by slug, and several slugs ARE numbers: a file
    # holding a 1099 licensed the literal "1099" anywhere in the output, a 1003 licensed "1003". The
    # field two lines up was given this treatment and the new one was not.
    source = (
        _numbers_in(summary.to_json())
        - _numbers_in(str(summary.documents_on_file))
        - _numbers_in(str(summary.document_kinds_on_file))
    )
    return _numbers_in(composition.message) - source


def unsupported_numbers_in(
    source_json: str, text: str, *, unlicensed: Iterable[str] = ()
) -> set[str]:
    """The same hallucination check over plain text — LP-634's need reasons use it.

    Shared rather than re-derived: the number grammar `_numbers_in` encodes (two-or-more digits, or a
    four-digit year, singles excluded) is a decision, and a second copy of it drifts the way the
    identifier union did in bug-006.

    bug-008 — AND `unlicensed` IS THE OTHER HALF OF THAT SHARING. The caller above does not hand its
    whole payload to this grammar; it subtracts the two fields whose digits are NAMES rather than
    quantities, for reasons LP-597 and LP-613 each cost a shipped defect to learn. The first cut of
    this function dropped both subtractions, which put the same hole back for needs: a file holding a
    1099 licensed the literal token "1099" anywhere in a composed reason, because
    `document_label("1099")` is `"1099"` and it rides in `documents_on_file`. Every caller passes the
    parts of its own summary whose numbers must not become quotable.
    """
    source = _numbers_in(source_json)
    for part in unlicensed:
        source -= _numbers_in(part)
    return _numbers_in(text) - source


# Phrases that describe the SOFTWARE rather than the loan file. The prompt forbids them and a model
# still wrote "The system cannot verify derogatory seasoning requirements" on the first real run — a
# processor does not care what the system can do, only what the file is missing. Enforced rather than
# requested, because a prompt instruction is a hope and a check is a guarantee.
# NARROW ON PURPOSE — only phrases that name the SOFTWARE AS AN ACTOR.
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


#: Adverbs that JUDGE an action rather than describe the file (LP-599).
#:
#: DT-8's template was rewritten to say "the application marks this mortgage as paid off at closing,
#: so it is excluded from the debt ratio" — deliberately, because "CORRECTLY excluded from the
#: BACK-END debt-to-income ratio" claimed two things the rule never established: that the lien sits on
#: the subject property, and a property of a ratio that is gated on any file missing taxes and
#: insurance. The composer put "correctly" straight back, and shipped it to a processor.
#:
#: NARROW BY CONSTRUCTION. "verified", "documented" and "confirmed" are NOT here and must not be: the
#: prompt's own worked examples for a passing finding are "Employment is verified for the full
#: two-year history" and "Reserves are fully documented". Those describe the FILE'S evidence. The six
#: below describe whether something was done RIGHT, which is a judgment about the engine's own work
#: and never needed to state a fact about a loan.
_EDITORIALISING = (
    "correctly",
    "properly",
    "appropriately",
    "accurately",
    "rightly",
    "as it should be",
)


def editorialises_correctness(composition: Composition) -> set[str]:
    """Words asserting that something was done RIGHT, rather than saying what the file shows.

    ⚠️ WORD BOUNDARIES, NOT SUBSTRINGS. A plain `in` check inverts this rule's meaning: "the
    application INcorrectly lists the property as a second home" contains "correctly", so a finding
    reporting a genuine error was rejected as editorialising, retried, rejected again, and shipped the
    raw engine template. Same for "improperly" against "properly". The negated forms are precisely
    what a finding SHOULD say.
    """
    text = composition.message.lower()
    return {word for word in _EDITORIALISING if re.search(rf"\b{re.escape(word)}\b", text)}


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

#: LP-607 — a CONTENT ID, which the dotted pattern above cannot see because it has no dot. ID-4
#: shipped "the borrower's current residence differs across sources (docdbbe8db1f5a7d9ff,
#: doc6abd650d555473b0, docafdf7653352bf74d, ...)" — five internal keys in a sentence a processor
#: reads, straight past a guard whose whole job is keeping them out. The prefixes are the ones the
#: subject-key vocabulary uses (`doc`, `lia`, `txn`, `acct`) followed by a hex run.
CONTENT_ID = re.compile(r"\b(?:doc|lia|txn|acct)[0-9a-f]{8,}\b")

#: LP-611 — a bare UUID, which the pattern above cannot see: it has dashes and no prefix. IN-1
#: shipped "borrower 7558383f-dfbb-47c3-8b3f-aa1ca5494987: documented monthly income is absent" to a
#: processor. Third identifier shape to reach user-facing text (a dotted tag id, then a content id,
#: now this), so the guard covers the family rather than the instance.
UUID_ID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)


def leaked_identifiers_in(text: str) -> set[str]:
    """Tag ids, MISMO paths, content ids or UUIDs in any text bound for a processor.

    THE ONE UNION — bug-006. These three patterns were added one at a time (LP-377-B, LP-607, LP-611),
    and the coverage-flag path grew a second copy of the union with a comment claiming it had imported
    rather than restated them. It had restated them: a fourth pattern here would have left that copy
    checking three while the retraction path leaked the new shape. Every caller reads this.
    """
    return (
        set(IDENTIFIER.findall(text)) | set(CONTENT_ID.findall(text)) | set(UUID_ID.findall(text))
    )


def leaked_identifiers(composition: Composition) -> set[str]:
    """LP-377-B's rule, applied to generated text."""
    return leaked_identifiers_in(composition.message)


#: The prompt with the verb list rendered in — built here rather than inline, because the template is
#: defined above `_ASKING` and carries JSON braces that rule an f-string out.
SYSTEM_PROMPT = _SYSTEM_PROMPT_TEMPLATE.replace("__ASKING_VERBS__", _asking_phrase())


#: The opening verb, matched on a WORD BOUNDARY.
#:
#: bug-002 review — `startswith` over bare stems was fine while every entry was a word nobody starts a
#: statement with ("obtain", "upload"). Widening the list to the application-edit verbs broke it in
#: both directions at once, because `add`, `document`, `update`, `include`, `correct` and `remove` are
#: all prefixes of ordinary nouns and participles:
#:
#:   "Documentation of the full two-year employment history is in the file."  -> read as a task
#:   "Updated pay stubs for both borrowers are in the file."                  -> read as a task
#:   "Additional reserves beyond the requirement are documented."             -> read as a task
#:   "Included in the ratio is the full PITI on the subject property."        -> read as a task
#:
#: Each of those is a correct PASS sentence rejected as `asking_on_a_pass`, and the same slip runs the
#: other way: "Documentation for the gift funds is not in the file." satisfied `stating_on_a_review`,
#: reopening the hole LP-603 closed when OC-2 shipped a pass-reading sentence into Needs attention.
#: The prompt's own worked example, "Reserves are fully documented.", is one rewrite from it.
_ASKING_RE = re.compile(rf"^(?:{'|'.join(verb.strip() for verb in _ASKING)})\b", re.IGNORECASE)


def asks_for_work(composition: Composition) -> bool:
    """Does this action ask for something, when nothing is being asked for?"""
    return _ASKING_RE.match(composition.action.strip()) is not None


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


#: Rejections worth a second attempt. Every one of them is the model producing something MALFORMED or
#: OVERREACHING rather than the summary being uncomposable — a different sample usually complies, and
#: at temperature 0 the retry gets the reason appended so it is not simply the same draw again.
#: `asking_on_a_pass` is here too: it is a tone failure, not a factual one.
_RETRYABLE = frozenset(
    {
        "unsupported_numbers",
        "machinery_talk",
        "identifier",
        "asking_on_a_pass",
        "malformed",
        "editorialising",
        "stating_on_a_review",
    }
)


def rejection_reason(summary: FactSummary, composition: Composition) -> str | None:
    """Why this composition must not reach a processor, or None if it may (LP-601).

    ONE function, called from TWO places, and that is the point. `compose` runs only on a cache MISS
    (`finding_prose.py`'s `misses = [... if key not in cache]`), so a composition stored before a guard
    existed is served forever and the guard never sees it. LP-599 added the "correctly" check, and
    DT-8's already-cached "is correctly excluded from the debt-to-income ratio" went on shipping —
    a fix that was right and unreachable.

    The cache is now filtered through this on the way in, so ANY guard added later heals the stored
    prose on the next run rather than applying only to findings nobody had composed yet.
    """
    if invented := unsupported_numbers(summary, composition):
        return f"unsupported_numbers:{len(invented)}"
    if editorialises_correctness(composition):
        return "editorialising"
    if machinery_talk(composition):
        return "machinery_talk"
    if leaked_identifiers(composition):
        return "identifier"
    if summary.settled and asks_for_work(composition):
        return "asking_on_a_pass"
    # LP-603 — THE INVERSE, which had no check at all. A finding that is NOT settled is on the
    # processor's list because something is outstanding, and its action must say what to do about it.
    # OC-2 shipped "The stated primary residence occupancy is supported by the application." on a
    # `needs_review`: a sentence that reads as a pass, sitting in Needs attention, asking for nothing.
    # OC-2 is a judgment rule and ratifies every verdict (ADR-336), so even a confident "yes" reaches a
    # human — and the text has to make the ratification the ask, not report that all is well.
    if not summary.settled and not asks_for_work(composition):
        return "stating_on_a_review"
    return None


def _user_message(summary: FactSummary, retry_of: str | None) -> str:
    """The summary, plus — on a retry — what was wrong with the previous attempt."""
    if retry_of is None:
        return summary.to_json()
    return (
        f"{summary.to_json()}\n\n"
        f"Your previous answer was REJECTED for: {_REJECTION_GUIDANCE[retry_of]} "
        "Write it again, obeying that rule exactly."
    )


#: What to tell the model on a retry. Specific, because "try again" at temperature 0 mostly reproduces
#: the same draw — the appended sentence is what makes the second attempt different from the first.
_REJECTION_GUIDANCE = {
    "unsupported_numbers": (
        "you introduced a number that is not in the summary. Use only figures that appear there, or "
        "none at all."
    ),
    "machinery_talk": (
        "you described the software rather than the loan file. Say what the FILE is missing, never "
        "what a system or a check did."
    ),
    "identifier": "you included an identifier that must never reach a processor. Remove it.",
    # bug-002 — DERIVED FROM `_ASKING`, never restated. The two drifted apart the moment the list
    # needed a new verb: the guidance kept naming the document-chasing words back to the model, so a
    # retry on a rule whose fix EDITS the application was steered away from the only verb that fit and
    # failed the same guard twice.
    "stating_on_a_review": (
        "this check is NOT resolved — something is still outstanding — and you wrote it as a "
        "statement. Begin the action with what the processor must DO about it: "
        + _asking_phrase()
        + "."
    ),
    "editorialising": (
        "you wrote that something was done correctly, properly or accurately. Say what the file "
        "SHOWS, never whether a figure or a calculation is right — that is not yours to assert."
    ),
    # bug-002 review — THE FOURTH SITE, and the one the first fix missed while its own commit message
    # claimed all three were done. This entry still named the pre-widening nine, so a settled finding
    # composed as "Add the account to the application" was rejected `asking_on_a_pass` and then handed
    # guidance that never mentioned "Add" — at temperature 0 the retry re-emits the same opener, the
    # second rejection is final, and the raw template ships. Exactly the retry-cannot-rescue-it defect
    # bug-002 set out to remove, left standing in the opposite direction.
    "asking_on_a_pass": (
        "this check PASSED, and you wrote it as a task. State what is in order, and never begin with "
        + _asking_phrase()
        + "."
    ),
    "malformed": 'you did not return a single JSON object of exactly {"action": "...", "why": "..."}.',
}


async def _maybe_retry(
    summary: FactSummary, reason: str, already_retried: str | None
) -> Composition | None:
    """One retry, and only one — a second rejection means the template stands."""
    if already_retried is not None or reason not in _RETRYABLE:
        return None
    return await compose(summary, _retry_of=reason)


async def compose(summary: FactSummary, *, _retry_of: str | None = None) -> Composition | None:
    """Rewrite one finding, or ``None`` when the caller should keep the template.

    Returns None — never raises — for every failure mode: transport, truncation, malformed JSON, and a
    generation that introduced a fact. The caller's fallback is the template it already has.

    LP-597 — ONE RETRY on a rejection the model can fix. Rejection is a real safety mechanism (it is
    what keeps an invented number or an unrequested document off a processor's screen), but a rejected
    composition means the finding ships the raw template — and the templates read as engine prose,
    lowercase and mid-sentence, because they were written to be rewritten. On a real run that left
    DT-8 and MI-1 reading quite differently from every finding beside them. Retrying the recoverable
    rejections keeps the guard and narrows the fallback to what genuinely cannot be composed.
    """
    try:
        result = await complete(
            model=settings.anthropic_model_reasoning,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": _user_message(summary, _retry_of)}],
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
        return await _maybe_retry(summary, "malformed", _retry_of)

    # LP-601 — THROUGH THE SHARED VERDICT, so this path and the cache filter cannot drift apart. A
    # guard that lived only here would be invisible to prose composed before it existed, which is
    # exactly how DT-8 kept shipping "correctly excluded" after LP-599 banned it.
    #
    # NOT logged with the text — the reason and the fact of rejection are the signal.
    if reason := rejection_reason(summary, composition):
        logger.warning("finding_prose_rejected", reason=reason)
        return await _maybe_retry(summary, reason.split(":")[0], _retry_of)
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
