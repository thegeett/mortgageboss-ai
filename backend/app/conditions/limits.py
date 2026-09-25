"""How long reading a condition sheet may take, and when a round counts as abandoned.

⚠️ THESE LIVE IN A MODULE OF THEIR OWN BECAUSE THREE LAYERS NEED THEM AND THEY CANNOT SHARE THEM
ANYWHERE ELSE. The Celery task sets its time limits from them; the reparse SERVICE refuses a round
that is still legitimately being read; and `tests/test_condition_type_mirror.py` pins the frontend's
copy against them. `app/schemas/` importing from `app/tasks/` would invert the one direction this
repo's imports run — the same argument `sheet_read.py` makes for its own existence.

This module imports NOTHING, deliberately: it cannot participate in a cycle, and a constant that can
be read without dragging in Celery is a constant anything may read.
"""

from __future__ import annotations

#: A sheet is small work next to a document pipeline, but a scanned multi-page letter still
#: rasterises. Its own limits rather than the global 180s, which is below what OCR can need.
PARSE_SOFT_LIMIT_SECONDS = 300
PARSE_HARD_LIMIT_SECONDS = 360

#: How long past the HARD limit a round must sit in `PARSING` before a processor may ask for it to
#: be read again.
#:
#: ⚠️ DERIVED, NOT A LITERAL, AND THE LITERAL WAS THE FIRST VERSION (LP-909 review). Written as
#: `600` its justification lived in a comment saying "clear of 360" — so moving
#: `PARSE_HARD_LIMIT_SECONDS` would leave the window where it was and quietly make that sentence
#: false. Stating it as the timeout plus a grace makes the relationship the code's rather than the
#: comment's: the window follows the limit it exists to exceed.
_REPARSE_GRACE_SECONDS = 240

#: ⚠️ THE SERVER OWNS THIS NUMBER, AND THE CLIENT'S OWN GUESS WAS WRONG IN THE DANGEROUS DIRECTION.
#: `frontend/lib/api/conditions.ts` had `STRANDED_AFTER_MS = 5 * 60 * 1000`, justified by S1-02's
#: "usually under 30 seconds" — a sentence about the healthy case, which is not what a bound is for.
#: It consulted neither limit above.
#:
#: 300 seconds is not merely below the hard limit: it is EXACTLY `PARSE_SOFT_LIMIT_SECONDS`, so the
#: client declared a round dead at the precise instant Celery raises `SoftTimeLimitExceeded` — with
#: 60 seconds of hard-limit runway left in which the task can still finish, or settle `PARSE_FAILED`
#: itself with a reason. A reparse offered at that moment would have raced a live worker rather than
#: rescued a stuck one.
#:
#: Past this bound the worker has certainly been killed, so the round is genuinely abandoned rather
#: than slow. `tests/test_condition_type_mirror.py` pins the TypeScript copy to it, the same way it
#: pins `MAX_PASTE_CHARS` — a number both sides enforce has to be one number.
STRANDED_AFTER_SECONDS = PARSE_HARD_LIMIT_SECONDS + _REPARSE_GRACE_SECONDS

__all__ = [
    "PARSE_HARD_LIMIT_SECONDS",
    "PARSE_SOFT_LIMIT_SECONDS",
    "STRANDED_AFTER_SECONDS",
]
