"""✦ Polish a condition draft (LP-922 follow-up): the model restyles, code checks the facts.

IT PROPOSES; SHE CHOOSES. This returns the polished HTML and the fact warnings; nothing is stored until
she presses "Use this". A changed or dropped fact is SHOWN with a warning rather than refused — the
product owner's rule of 2026-09-29 — because she is the one who can tell a harmless rewording of a date
from a wrong one, and a refusal would hide the whole proposal over it.

ALWAYS ON. Unlike Phase 4's framing, this does not follow `email_draft_enabled`: it runs only when she
clicks, one call per click, and every fact is checked by code afterwards.

WHAT GOES TO THE MODEL: the email body and nothing else — never the loan snapshot. Logs carry counts only.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.ai.client import complete
from app.ai.prompt_loader import load_prompt
from app.communications.sanitise import sanitise_html
from app.conditions.email_facts import FactWarning, fact_warnings
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

PROMPT_PATH = "conditions/polish_v1.txt"
_MAX_TOKENS = 2000

#: What the dialog says when there is no proposal. Never a silent "nothing changed".
REFUSAL_UNAVAILABLE = (
    "The AI could not polish this email just now. Your draft is unchanged — try again."
)
REFUSAL_EMPTY = "The AI returned nothing usable. Your draft is unchanged — try again."


@dataclass(frozen=True)
class PolishProposal:
    #: The polished body, sanitised; None when `refusal` says why not.
    html: str | None
    warnings: list[FactWarning] = field(default_factory=list)
    refusal: str | None = None


def _strip_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[1] if "\n" in stripped else ""
        stripped = stripped.rsplit("```", 1)[0]
    return stripped.strip()


async def polish_draft(body_html: str) -> PolishProposal:
    """One model call. Never raises: a failure is a refusal sentence."""
    if not (body_html or "").strip():
        return PolishProposal(html=None, refusal=REFUSAL_EMPTY)
    try:
        result = await complete(
            model=settings.anthropic_model_reasoning,
            system=load_prompt(PROMPT_PATH),
            messages=[{"role": "user", "content": body_html}],
            max_tokens=_MAX_TOKENS,
        )
    except Exception:
        # Any transport or model failure is the same answer for her: the draft is untouched.
        logger.info("condition_polish_unavailable")
        return PolishProposal(html=None, refusal=REFUSAL_UNAVAILABLE)
    polished = sanitise_html(_strip_fences(result.text or ""))
    if not polished.strip():
        logger.info("condition_polish_empty")
        return PolishProposal(html=None, refusal=REFUSAL_EMPTY)
    warnings = fact_warnings(body_html, polished)
    # COUNTS ONLY: the body names the borrower, the account ending and the amounts.
    logger.info("condition_polish_proposed", warnings=len(warnings))
    return PolishProposal(html=polished, warnings=warnings)


__all__ = ["PROMPT_PATH", "PolishProposal", "polish_draft"]
