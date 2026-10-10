"""LP-971 — "Describe it": her sentence becomes proposed steps. The model proposes; code checks; she adds.

The owner's design (the "The plan as a path" board): "Or describe what you want to do · Turn it into
steps". She types, for example, "Ask the underwriter to move 1228 to closing, it's new construction", and
gets the steps of a plan she can add with one press.

IT PROPOSES; SHE ADDS. This stores nothing. The screen shows the steps, and "Add these steps" adds them
through LP-969's own doors (`add_item`, `set_next_step`), so each one drafts, links, checks and is recorded
exactly as a step she added by hand. The drafts are the ones those doors already write.

ONLY THE REAL BUILDING BLOCKS. A step the model returns outside LP-969's seven blocks, or an email to
someone the screen cannot email, is left out, and the reason is shown to her. Nothing is coerced into a
block it was not.

NOTHING INVENTED, CHECKED BY CODE (the reading's rule, LP-919; the polish's checker, LP-922). Every step's
words are compared with HER WORDS and THE LENDER'S WORDS by `email_facts.fact_warnings`. A step that adds
an amount, a date, a day word or an account or loan number found in neither is left out, naming the fact.
Asking a model whether a model invented a figure has the same failure mode as the thing being checked.

A REFUSAL OR A FAILURE SAYS SO. Never raises: no answer from the model, an unreadable one, or no steps
come back as a sentence for her.

WHAT GOES TO THE MODEL: her words, the lender's words and the reading's summary — what the reading
already sends. Logs carry counts only.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from app.ai.client import complete
from app.ai.parsing import extract_json_object
from app.ai.prompt_loader import load_prompt
from app.conditions.email_facts import fact_warnings
from app.core.config import settings
from app.core.logging import get_logger
from app.models.condition_vocabulary import Performer

logger = get_logger(__name__)

PROMPT_PATH = "conditions/describe_v1.txt"
_MAX_TOKENS = 1200
MAX_STEPS = 6
_MAX_TEXT = 190

#: LP-969's building blocks, by the names the prompt and the screen share.
BLOCKS = ("email", "upload_ask", "upload_mine", "check", "underwriter", "push_back", "todo")
#: The condition's own question: at most one, because a condition carries one `next_step`.
QUESTION_BLOCKS = ("underwriter", "push_back")

#: Who an email may go to. DERIVED FROM THE PERFORMERS minus three named exclusions, matching the screen's
#: `EMAIL_WHO` (`plan-add-step.tsx`): herself (an email to herself is a to-do), the appraiser (appraisal
#: requests go through the lender), and the attorney (Title and the attorney share one email; the model is
#: told to say "title").
NOT_EMAILED = frozenset({Performer.PROCESSOR, Performer.APPRAISER, Performer.ATTORNEY})
EMAIL_TO = tuple(p.value for p in Performer if p not in NOT_EMAILED)

REFUSAL_UNAVAILABLE = (
    "The AI could not turn that into steps just now. Nothing was changed — try again."
)
REFUSAL_UNREADABLE = "The AI's answer could not be read. Nothing was changed — try again."
REFUSAL_EMPTY = "Write a few words saying what you want to do."
REFUSAL_NO_STEPS = "That didn't turn into any steps. Try saying who should do what."


@dataclass(frozen=True)
class ProposedStep:
    block: str
    text: str
    #: For an email: who it goes to (a `Performer` value).
    to: str | None = None


@dataclass(frozen=True)
class DescribeProposal:
    steps: list[ProposedStep] = field(default_factory=list)
    #: One sentence per step left out, saying why.
    left_out: list[str] = field(default_factory=list)
    refusal: str | None = None


def _user_content(words: str, lender_words: str, summary: str | None) -> str:
    parts = [f"HER WORDS:\n{words}", f"THE LENDER'S WORDS:\n{lender_words}"]
    if summary:
        parts.append(f"WHAT IT ASKS FOR:\n{summary}")
    return "\n\n".join(parts)


def checked_steps(
    raw: object, *, words: str, lender_words: str
) -> tuple[list[ProposedStep], list[str]]:
    """The model's steps, keeping only real blocks with nothing invented. Pure; tested directly."""
    steps: list[ProposedStep] = []
    left_out: list[str] = []
    source = f"{words}\n{lender_words}"
    asked_question = False
    for entry in raw if isinstance(raw, list) else []:
        if not isinstance(entry, dict):
            continue
        block = str(entry.get("block") or "")
        text = " ".join(str(entry.get("text") or "").split())[:_MAX_TEXT]
        if block not in BLOCKS:
            left_out.append(f"Left out a step we can't do here ({block or 'unnamed'}).")
            continue
        if not text:
            left_out.append("Left out a step with no words.")
            continue
        to: str | None = None
        if block == "email":
            to = str(entry.get("to") or "")
            if to == Performer.ATTORNEY.value:
                to = Performer.TITLE.value  # one email for both (see `NOT_EMAILED`)
            if to not in EMAIL_TO:
                left_out.append(f"Left out “{text}”: we can't email {to or 'nobody'} from here.")
                continue
        if block in QUESTION_BLOCKS:
            if asked_question:
                left_out.append(
                    f"Left out “{text}”: a condition carries one question to the underwriter."
                )
                continue
            asked_question = True
        added = [w.fact for w in fact_warnings(source, text) if w.kind == "added"]
        if added:
            left_out.append(
                f"Left out “{text}”: it mentions {', '.join(added)}, which is not in what you wrote "
                "or the lender's words."
            )
            continue
        if len(steps) >= MAX_STEPS:
            left_out.append(f"Left out “{text}”: at most {MAX_STEPS} steps at a time.")
            continue
        steps.append(ProposedStep(block=block, text=text, to=to))
    return steps, left_out


async def describe_steps(
    *, words: str, lender_words: str, summary: str | None = None
) -> DescribeProposal:
    """One model call. Never raises: a failure is a refusal sentence."""
    words = " ".join((words or "").split())
    if not words:
        return DescribeProposal(refusal=REFUSAL_EMPTY)
    try:
        result = await complete(
            model=settings.anthropic_model_reasoning,
            system=load_prompt(PROMPT_PATH),
            messages=[{"role": "user", "content": _user_content(words, lender_words, summary)}],
            max_tokens=_MAX_TOKENS,
            temperature=0.0,
        )
    except Exception:
        # Any transport or model failure is the same answer for her: nothing was changed.
        logger.info("condition_describe_unavailable")
        return DescribeProposal(refusal=REFUSAL_UNAVAILABLE)
    snippet = extract_json_object(result.text or "")
    try:
        payload = json.loads(snippet) if snippet else None
    except (json.JSONDecodeError, ValueError):
        payload = None
    if not isinstance(payload, dict):
        logger.info("condition_describe_unreadable")
        return DescribeProposal(refusal=REFUSAL_UNREADABLE)
    steps, left_out = checked_steps(payload.get("steps"), words=words, lender_words=lender_words)
    # COUNTS ONLY: her words and the lender's can name the borrower, amounts and accounts.
    logger.info("condition_describe_proposed", steps=len(steps), left_out=len(left_out))
    if not steps:
        unclear = payload.get("unclear")
        sentence = (
            " ".join(str(unclear).split())[:200]
            if isinstance(unclear, str) and unclear.strip()
            else None
        )
        # The model's own sentence reaches her too, so it is held to the same rule as a step.
        if sentence and any(
            w.kind == "added" for w in fact_warnings(f"{words}\n{lender_words}", sentence)
        ):
            sentence = None
        return DescribeProposal(left_out=left_out, refusal=sentence or REFUSAL_NO_STEPS)
    return DescribeProposal(steps=steps, left_out=left_out)


__all__ = [
    "BLOCKS",
    "EMAIL_TO",
    "PROMPT_PATH",
    "DescribeProposal",
    "ProposedStep",
    "checked_steps",
    "describe_steps",
]
