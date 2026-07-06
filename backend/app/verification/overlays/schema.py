"""The lender-overlay structure (LP-74) — an overlay is a DIFF, not a copy.

A lender overlay (Layer 3) is the small set of places a *lender* deviates from
the *investor* default. It is stored as a **diff**, never a full per-lender copy
of the rule set:

* :class:`ThresholdOverride` — "for rule ``X``, use *this* threshold instead".
  Keyed by the stable ``rule_id``; only the :class:`Condition` (the
  threshold-as-data) changes. The rule's identity and logic are untouched.
* a custom :class:`VerificationRule` — a rule the lender adds that the investor
  default does not have (a LENDER-scoped rule).

Everything the overlay does **not** mention falls through to the investor
default. No overlay at all → every rule is the investor default. Keeping overlays
as diffs is what keeps them small, maintainable and auditable (you can see at a
glance exactly where a lender differs).

LP-74 ships the overlay-*application* mechanism plus a SAMPLE overlay
(:mod:`app.verification.overlays.samples`); the real UWM / Sun-West overlays are
LP-80.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.verification.rules.schema import Condition, VerificationRule


class ThresholdOverride(BaseModel):
    """Override one base rule's threshold, by stable ``rule_id`` (a diff entry).

    Only the :attr:`condition` (threshold-as-data) is supplied; the rule's
    identity, the field(s) it reads and the comparison logic are inherited
    unchanged from the base rule. This is the entire reason the two linchpins
    matter: a stable id to reference, and a data threshold to swap.
    """

    model_config = ConfigDict(frozen=True)

    rule_id: str
    condition: Condition
    # Why this lender deviates from the investor default — auditable and editable
    # (LP-80 populates it on the real overlays; LP-87's admin UI edits it). Optional
    # so the LP-74 sample overlay (mechanism-only) stays valid without one.
    reason: str | None = None


class LenderOverlay(BaseModel):
    """A lender's overlay — overrides (by id) plus custom rules. A pure diff."""

    model_config = ConfigDict(frozen=True)

    lender_slug: str
    overrides: tuple[ThresholdOverride, ...] = ()
    custom_rules: tuple[VerificationRule, ...] = ()
