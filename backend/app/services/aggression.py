"""Aggression dial resolution (LP-79) — the active level + cutoff for a file.

The dial is a per-file **confidence cutoff** with a **user-level default** and a
**per-file override**. This module resolves the *active* level (the file's
override if set, else the user's default) into the confidence cutoff that the
read-time filter applies to BOTH:

* **display** — only findings at/above the cutoff are shown (below-cutoff hidden);
* **blocking** — only open in-scope findings (at/above the cutoff) block submission
  (the cutoff is fed to LP-75's blocking computation).

It is a pure **read-time view filter** over LP-78's already-stored findings — it
never re-runs the AI, never recolors a finding (confidence ≠ severity), and is
instant + free. "Resolve all" therefore means "resolve all at the chosen
thoroughness": a more thorough setting (a lower cutoff) surfaces — and requires
resolving — more findings.
"""

from __future__ import annotations

from app.models.loan_file import LoanFile
from app.models.user import User
from app.verification.confidence import AggressionLevel, cutoff_for_level


def resolve_aggression_level(loan_file: LoanFile, user: User) -> AggressionLevel:
    """The active level for a file: its per-file override if set, else the user default."""
    if loan_file.aggression_level_override is not None:
        return loan_file.aggression_level_override
    return user.default_aggression_level


def active_cutoff(loan_file: LoanFile, user: User) -> float:
    """The confidence cutoff in force for a file (the active level → its cutoff)."""
    return cutoff_for_level(resolve_aggression_level(loan_file, user))
