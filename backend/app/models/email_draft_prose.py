"""The email-draft prose cache (LP-810) — composed wording, keyed by the facts it was composed from.

A PURE CACHE, on the same terms as :class:`~app.models.finding_prose.FindingProse` and
:class:`~app.models.needs_prose.NeedProse`: no foreign key, no loan file, no draft. A row is a
function of its key alone, so it can be truncated at any time and two files whose facts coincide
share the wording.

DETERMINISM IS THE POINT, more here than anywhere else it has been applied. A processor reads a
draft, edits it, and comes back to it. Without a cache the same unchanged draft is worded
differently every time it regenerates — and LP-809 regenerates on every add and every remove, so a
processor adding one document would find the other five paragraphs rewritten underneath their
cursor. That is bug-008's lesson arriving in the place it does the most damage.

WHAT IS AND IS NOT IN THE KEY is therefore the whole design. The key covers the facts a draft is
composed FROM — the documents being asked for, the borrower's first name, the file's basics — and
nothing else. LP-822's style profile is deliberately keyed separately (its own fingerprint), so
editing a signature block invalidates voice without touching content, and a new document on the file
re-derives content without touching voice.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utcnow


class EmailDraftProse(Base):
    """One cached draft body, plus the guard verdict that let it through.

    ``rejection_reason`` is stored as NULL for every row that is served. Rejected compositions are
    never cached — the column exists so the *absence* is explicit rather than implied, and so a later
    guard can be told from a row composed before it existed. See ``ai/email_draft.rejection_reason``:
    the cache is filtered through the same function on the way in, so a guard added later heals
    stored prose on the next run instead of applying only to drafts nobody had composed yet. That is
    LP-601's lesson, and it cost a shipped defect to learn the first time.
    """

    __tablename__ = "email_draft_prose"

    fact_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    #: The composed body. Borrower-facing prose about one file's documents — never logged, and
    #: dropped by the readonly view for the same reason `communications.body` is.
    body: Mapped[str] = mapped_column(Text, nullable=False)
    #: Which template the plain fallback would have used, so a stored row names the shape it replaces.
    template_key: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
