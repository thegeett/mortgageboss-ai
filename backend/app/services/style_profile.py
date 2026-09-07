"""Resolving a processor's writing voice, and the neutral default when they have none (LP-822).

Two things live here, and the second is the one the ticket turns on:

* :func:`resolve_style` — the profile for a user, or :data:`NEUTRAL_STYLE` when there is none. It
  returns a value object rather than ``StyleProfile | None`` so no caller has to branch, and so the
  drafter cannot accidentally send with a half-populated voice.
* :attr:`ResolvedStyle.fingerprint` — the cache key that makes the whole design work. LP-810 caches
  style on this and its fact bundle on its own key, so editing a signature block invalidates voice
  and leaves every draft's content alone, and a new document on a file re-derives content without
  touching voice. Keyed together — which is what a wider fact bundle would amount to — bug-008
  repeats: everything rewords whenever anything changes.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.style_profile import MAX_EXEMPLAR_CHARS, MAX_EXEMPLARS, StyleProfile


class InvalidExemplar(ValueError):
    """An exemplar was rejected before it could be stored."""


@dataclass(frozen=True)
class ResolvedStyle:
    """The voice a draft is written in, and whether it is anybody's in particular."""

    greeting: str
    closing: str
    signature_block: str
    exemplars: tuple[str, ...]
    #: True when no profile existed and this is the neutral default.
    #:
    #: The one bit that separates "her voice" from "not her voice", and the spec's own failure mode
    #: is what makes it worth carrying: a drafter writing in generic assistant voice produces email
    #: the processor rewrites every time, and an AI drafter whose output is always rewritten is
    #: slower than a template. That failure is silent unless something can say which happened.
    is_default: bool

    @property
    def fingerprint(self) -> str:
        """A stable hash over the voice, and nothing else.

        Over the CONTENT rather than the row's ``updated_at``: a save that changed nothing should not
        invalidate a cache, and two users who happen to write identically should share one entry.
        The neutral default hashes like any other voice, so a user who later fills in a profile gets
        a different key without any special case.
        """
        material = "\x1f".join((self.greeting, self.closing, self.signature_block, *self.exemplars))
        return hashlib.sha256(material.encode("utf-8")).hexdigest()


#: What a draft sounds like before anyone has told us how this person writes.
#:
#: Plain and warm, with nothing pretending to be a particular individual. `is_default=True` is the
#: honest label, and it is what a UI should use to tell a processor their voice has not been set up
#: rather than letting them discover it in a draft.
NEUTRAL_STYLE = ResolvedStyle(
    greeting="Hello $borrower_first_name,",
    closing="Thanks,",
    signature_block="$processor_name",
    exemplars=(),
    is_default=True,
)


#: Identifier SHAPES a stored exemplar must not contain. Scoped to exactly that: each pattern below
#: matches something that is an identifier wherever it appears, so refusing it cannot turn away a
#: legitimate sentence about how to write an email.
#:
#: IT IS A TRIPWIRE, NOT A GUARANTEE, and the distinction matters enough to state twice. A borrower's
#: NAME is the likeliest thing to be left in a pasted email and is not shaped like anything a regex
#: can find. The control that actually holds is that whoever enters an exemplar redacts it first;
#: this catches the cases where they forgot the obvious ones.
_IDENTIFIER_SHAPES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("a Social Security number", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("an email address", re.compile(r"[^\s@]+@[^\s@]+\.[A-Za-z]{2,}")),
    ("a phone number", re.compile(r"\b\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b")),
    # Account and loan numbers. Eight or more consecutive digits is not a figure anyone writes in
    # prose about tone; a money amount carries separators or a decimal point and stays under it.
    ("an account or loan number", re.compile(r"\b\d{8,}\b")),
)


def validate_exemplars(exemplars: tuple[str, ...]) -> tuple[str, ...]:
    """Refuse exemplars that are too many, too long, empty, or carry an identifier shape.

    Raises :class:`InvalidExemplar` naming what was found and which exemplar it was in — but NOT
    quoting the match, because the message travels into logs and an error about a leaked identifier
    should not be the thing that leaks it.
    """
    if len(exemplars) > MAX_EXEMPLARS:
        raise InvalidExemplar(f"at most {MAX_EXEMPLARS} exemplars, got {len(exemplars)}")
    for index, exemplar in enumerate(exemplars, start=1):
        if not exemplar.strip():
            raise InvalidExemplar(f"exemplar {index} is empty")
        if len(exemplar) > MAX_EXEMPLAR_CHARS:
            raise InvalidExemplar(
                f"exemplar {index} is {len(exemplar)} characters; the limit is {MAX_EXEMPLAR_CHARS}"
            )
        for description, pattern in _IDENTIFIER_SHAPES:
            if pattern.search(exemplar):
                raise InvalidExemplar(
                    f"exemplar {index} looks like it still contains {description}. "
                    "Exemplars are shown to the model on every draft, for every borrower — "
                    "redact it before saving."
                )
    return exemplars


async def resolve_style(db: AsyncSession, *, user_id: UUID) -> ResolvedStyle:
    """This user's voice, or the neutral default. Never raises, never returns a partial voice."""
    profile = (
        await db.execute(select(StyleProfile).where(StyleProfile.user_id == user_id))
    ).scalar_one_or_none()
    if profile is None:
        return NEUTRAL_STYLE
    return ResolvedStyle(
        greeting=profile.greeting,
        closing=profile.closing,
        signature_block=profile.signature_block,
        exemplars=tuple(profile.exemplars),
        is_default=False,
    )


async def set_style_profile(
    db: AsyncSession,
    *,
    user_id: UUID,
    greeting: str,
    closing: str,
    signature_block: str = "",
    exemplars: tuple[str, ...] = (),
) -> StyleProfile:
    """Create or replace this user's profile. Validates exemplars BEFORE any write. ``flush`` only.

    One row per user, so this is an upsert rather than an insert: a second call replaces the voice
    instead of leaving two and making the drafter choose.
    """
    validate_exemplars(exemplars)
    if not greeting.strip() or not closing.strip():
        raise InvalidExemplar("a profile needs both a greeting and a closing")
    profile = (
        await db.execute(select(StyleProfile).where(StyleProfile.user_id == user_id))
    ).scalar_one_or_none()
    if profile is None:
        profile = StyleProfile(user_id=user_id)
        db.add(profile)
    profile.greeting = greeting
    profile.closing = closing
    profile.signature_block = signature_block
    profile.exemplars = list(exemplars)
    await db.flush()
    return profile
