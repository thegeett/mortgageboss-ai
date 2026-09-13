"""✦ polish — the model tidies a processor's own words, and may not add to them (LP-856).

IT PROPOSES; IT DOES NOT REPLACE. This returns text. Storing it is a separate act the processor
takes, and the original is held on screen until they choose — because a rewrite that lands silently
on save is a message going out in words nobody read, and the processor is the one who will be asked
about those words later.

IT FAILS VISIBLY OR NOT AT ALL. `email_draft_enabled` is off in every environment today, so the
ordinary outcome is a refusal a processor can read. It never returns something subtly different and
calls it polish: a silent degradation is worse than an error here, because the processor cannot tell
which version they are looking at.

WHAT IT MAY CHANGE: tone, grammar, structure, greeting, sign-off. NOT FACTS. The prompt says so and
the guards below enforce it, because a prompt is a request and a guard is a rule. A polish that
invents "by Friday" is a commitment the file did not make.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass

from app.ai.client import complete
from app.ai.email_draft import _REGULATORY_GROUNDS, regulatory_grounds
from app.ai.finding_prose import unsupported_numbers_in
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_MAX_TOKENS = 1400

SYSTEM_PROMPT = """You rewrite a mortgage processor's email so it reads professionally.

You may change: tone, grammar, punctuation, sentence structure, paragraph breaks, the greeting and
the sign-off.

You may NOT add anything that is not already in the message. In particular you may not add:
- a date, a day of the week, or a deadline
- an amount, a rate, a percentage or any other number
- a document that is not already named
- a promise about what will happen or when

If the message does not mention a deadline, the rewrite does not mention a deadline. If it names two
documents, the rewrite names those two.

Keep the message's own meaning. Do not make it longer. Reply with the rewritten message only — no
preamble, no explanation, no quotation marks around it."""


@dataclass(frozen=True)
class PolishOutcome:
    """What the button gets back: a proposal, or a reason there is none."""

    #: The rewritten message, or None when it must not be shown.
    text: str | None
    #: Why there is no proposal, in a word the log can group by. None on success.
    refusal: str | None

    @property
    def ok(self) -> bool:
        return self.text is not None


#: Day and month names, from the calendar rather than typed out.
#:
#: DERIVED, because a list typed by hand is one that misses "Sept" the day somebody writes it. The
#: abbreviations come from the same module, so the two cannot disagree about which months exist.
_DATE_WORDS: frozenset[str] = frozenset(
    word.lower()
    for group in (calendar.day_name, calendar.day_abbr, calendar.month_name, calendar.month_abbr)
    for word in group
    if word
)


def invented_date_words(before: str, after: str) -> set[str]:
    """Day and month names the rewrite introduced.

    ACCEPTANCE 6, AS A RULE RATHER THAN A REQUEST. "A polish prompt given a body with no dates
    returns a body with no dates. Checked, not assumed." The prompt asks; this is what makes it
    true, and the two are not the same thing — a model that ignores an instruction is the ordinary
    case rather than the exceptional one.

    NUMBERS ARE SOMEBODY ELSE'S JOB. `unsupported_numbers_in` already catches "by the 14th" and
    every amount; this catches the half that has no digits in it at all, which is exactly the
    ticket's own example: "by Friday".
    """
    present = {word for word in _DATE_WORDS if re.search(rf"\b{re.escape(word)}\b", before, re.I)}
    return {
        word
        for word in _DATE_WORDS
        if word not in present and re.search(rf"\b{re.escape(word)}\b", after, re.I)
    }


def refusal_for(before: str, after: str) -> str | None:
    """Why this rewrite must not be shown, or None if it may.

    THE REGULATORY FLOOR IS IMPORTED, not restated — `regulatory_refusal` is the same list the
    composed framing is held to, and a second copy would drift silently because each copy's tests
    would pass over its own.

    THE ORIGINAL LICENSES ITS OWN CONTENT. A processor who wrote "$10,000" may have it back; the
    model may not introduce one. That is what makes this a check on what was ADDED rather than a
    check on what the message says.
    """
    if not (after or "").strip():
        return "empty"
    # LP-856 — ONLY A GROUND THE ORIGINAL DID NOT ALREADY TRIP.
    #
    # `regulatory_refusal` was written for a MODEL-COMPOSED framing, where any money amount is
    # invented by definition. Applied flat to a rewrite it refuses the processor's OWN words: "we
    # need proof of the $10,000 gift deposit" is an ordinary thing to ask for, and polishing it
    # would have been refused as `money_amount` — the button doing nothing on exactly the messages
    # that most need tidying, for a reason nobody could work out. Found by the control test rather
    # than by reading.
    #
    # SO THE RULE IS "INTRODUCED", WHICH IS WHAT THE TICKET ACTUALLY SAYS: tone, grammar, structure,
    # greeting and sign-off may change; FACTS may not be added. A ground the original already trips
    # is the processor's own, and theirs to keep.
    # THE SET, NOT THE FIRST GROUND. Comparing heads let a message that already mentioned an amount
    # acquire a COMMITMENT silently: `money_amount` is reported before `commitment`, so both sides
    # read `money_amount` and the new ground was never seen. Found by the test that plants exactly
    # that pair.
    introduced = regulatory_grounds(after) - regulatory_grounds(before)
    if introduced:
        # The ticket's own ordering — the reason that matters, where a rewrite trips several.
        for name, _ in _REGULATORY_GROUNDS:
            if name in introduced:
                return name
        return sorted(introduced)[0]
    if invented := invented_date_words(before, after):
        return f"invented_date:{','.join(sorted(invented))}"
    if numbers := unsupported_numbers_in(before, after):
        return f"unsupported_numbers:{len(numbers)}"
    return None


async def polish(text: str) -> PolishOutcome:
    """Rewrite ``text``, or say why not. Never raises.

    THE FLAG IS CHECKED FIRST AND THE REFUSAL IS NAMED. `email_draft_enabled` is off everywhere, so
    this is the outcome a processor actually gets today — and the button has to say so rather than
    quietly returning the text unchanged, which would look like a polish that decided nothing needed
    changing.
    """
    if not settings.email_draft_enabled:
        return PolishOutcome(text=None, refusal="unavailable")
    if not (text or "").strip():
        return PolishOutcome(text=None, refusal="empty")

    try:
        result = await complete(
            model=settings.anthropic_model_reasoning,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": text}],
            max_tokens=_MAX_TOKENS,
        )
    except Exception:
        # EVERY TRANSPORT FAILURE IS A REFUSAL, not an exception the route has to catch. The caller's
        # answer is the same either way — say so and leave the text alone — and a route that had to
        # know the difference would be a second place deciding what a failed polish means.
        logger.info("polish_unavailable")
        return PolishOutcome(text=None, refusal="unavailable")

    rewritten = (result.text or "").strip()
    if refusal := refusal_for(text, rewritten):
        # METADATA ONLY — never the text, in either direction. This is the fullest copy of a
        # processor's prose the product handles, and `communications.body` is dropped from every
        # readonly view for the same reason.
        logger.info("polish_refused", reason=refusal.split(":", 1)[0])
        return PolishOutcome(text=None, refusal=refusal)
    return PolishOutcome(text=rewritten, refusal=None)


__all__ = ["PolishOutcome", "invented_date_words", "polish", "refusal_for"]
