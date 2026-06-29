"""The three-layer composition (LP-74) — base + overlay-diff → effective set.

Given a file's **program** and **lender**, resolve the one flat *effective* rule
set with final thresholds:

1. **Base** = all regulatory rules (Layer 1, every file) + the investor rules for
   the file's program (Layer 2 — Conventional **or** FHA, never both).
2. **Patch** with the lender's overlay (Layer 3), applied as a diff:
   * an override replaces the matching base rule's threshold *by ``rule_id``*
     (identity and logic unchanged — only the :class:`Condition` data);
   * a custom rule is appended.
3. **Output** = a flat list of :class:`VerificationRule` with final thresholds.

**The investor rule is the default.** A rule the overlay does not mention falls
through to its investor value; no overlay at all → every rule is the investor
default. The overlay value, where specified, wins. Overlays are diffs, not
full per-lender copies.

This module is pure — it composes rule *definitions*. Reading a file's program /
lender / typed values and persisting findings is the service layer
(:mod:`app.services.verification_engine`).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.models.lender import LoanProgram
from app.verification.overlays.schema import LenderOverlay
from app.verification.rules.schema import RuleLayer, VerificationRule


def apply_overlay(
    base: Sequence[VerificationRule], overlay: LenderOverlay | None
) -> list[VerificationRule]:
    """Apply a lender overlay (a diff) to a base rule set, by ``rule_id``.

    Overrides replace a base rule's threshold (identity/logic preserved via
    :meth:`VerificationRule.with_condition`); custom rules are appended. Any base
    rule the overlay does not mention falls through unchanged — the *investor
    default*. ``overlay is None`` → the base set, verbatim.
    """
    if overlay is None:
        return list(base)

    overrides = {override.rule_id: override for override in overlay.overrides}
    resolved: list[VerificationRule] = []
    for rule in base:
        override = overrides.get(rule.rule_id)
        if override is not None:
            # Patch ONLY the threshold; rule_id, reads, layer, logic unchanged.
            resolved.append(rule.with_condition(override.condition, overlay=overlay.lender_slug))
        else:
            # Un-overridden → the investor (or regulatory) default falls through.
            resolved.append(rule)
    resolved.extend(overlay.custom_rules)
    return resolved


@dataclass(frozen=True)
class RuleRegistry:
    """The catalog of rule definitions + lender overlays, with composition.

    Holds the shared rule *definitions* and the overlays keyed by lender slug.
    :meth:`resolve` performs the three-layer composition for one file's program
    and lender. The registry is config-like (built from
    :mod:`app.verification.rules.samples` in LP-74; the real content is
    LP-82..85, the real overlays LP-80).
    """

    rules: tuple[VerificationRule, ...]
    overlays: Mapping[str, LenderOverlay]

    def regulatory(self) -> list[VerificationRule]:
        """All Layer-1 regulatory rules (apply to every file)."""
        return [r for r in self.rules if r.layer is RuleLayer.REGULATORY]

    def investor(self, program: LoanProgram) -> list[VerificationRule]:
        """Layer-2 investor rules for one program (Conventional OR FHA)."""
        return [
            r
            for r in self.rules
            if r.layer is RuleLayer.INVESTOR and r.applicability.program is program
        ]

    def resolve(
        self, *, program: LoanProgram | None, lender_slug: str | None
    ) -> list[VerificationRule]:
        """Resolve the effective rule set for a file's program + lender.

        Base = regulatory + investor(program); patched by the lender overlay if
        one exists for ``lender_slug``. A file with no program gets only
        regulatory rules; a file with no (or an unknown) lender gets all investor
        defaults.
        """
        base = self.regulatory()
        if program is not None:
            base = base + self.investor(program)
        overlay = self.overlays.get(lender_slug) if lender_slug is not None else None
        return apply_overlay(base, overlay)


def default_registry() -> RuleRegistry:
    """The registry built from the LP-74 SAMPLE rules + the SAMPLE + STARTER overlays.

    Imported lazily so the pure composition code above carries no dependency on
    the content. The real rule content is LP-82..85; the **starter** UWM / Sun-West
    overlays (LP-80) slot in here keyed by lender slug, so a file's target lender
    selects its overlay automatically (the calculators + engine resolve through
    here). The overlay VALUES are starter placeholders to validate with Priya; the
    per-company, hand-edited overlays + the admin editing UI are LP-87.
    """
    from app.verification.overlays.samples import SAMPLE_OVERLAYS
    from app.verification.overlays.starter import STARTER_OVERLAYS
    from app.verification.rules.conventional import CONVENTIONAL_RULES
    from app.verification.rules.samples import SAMPLE_RULES

    return RuleRegistry(
        # The LP-74 sample rules (DTI/LTV limits the calculators resolve) + the real
        # Conventional content: income/asset (LP-82) + credit/DTI/property/doc (LP-83),
        # grounded starters. FHA is LP-84/85.
        rules=(*SAMPLE_RULES, *CONVENTIONAL_RULES),
        overlays={**SAMPLE_OVERLAYS, **STARTER_OVERLAYS},
    )
