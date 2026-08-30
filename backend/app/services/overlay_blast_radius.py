"""What a proposed overlay would change, before it is saved (LP-UI-027).

An overlay moves every file at a lender, which is exactly why an admin should see
the consequence before committing to it rather than after.

**It computes rather than reads.** The estimate resolves each file's rules, swaps
in the proposed thresholds, and evaluates the pure engine twice — once as things
stand, once as they would be — then diffs the two. Nothing is written, no
verification run is enqueued, and no stored finding is consulted.

That choice is not a preference. Reading stored findings would return nothing:
`services/verification_engine` — the only caller of the overlay-aware
`evaluate()` — **has no production caller** (recorded in
`finding_source_matching.py`), so no finding on any file comes from a rule an
overlay can target. Measured, not assumed: zero findings exist for any `conv.*`,
`fha.*` or sample rule id. An estimate built on stored findings would answer
"no files affected" for every proposed change, which is the most dangerous
possible answer — it reads as reassurance.

Because `evaluate()` is pure, this works today regardless. The comparison is
honest about its own basis: it says what would happen **if the overlay were in
force**, and `applies_today` records whether it is.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.finding import FindingStatus
from app.models.helpers import only_active, scope_to_company
from app.models.lender import Lender
from app.models.loan_file import LoanFile, LoanFileStatus
from app.schemas.overlay_admin import OverlayOverrideInput
from app.services.verification_engine import _SEVERITY_TO_STATUS, build_file_facts
from app.verification.engine import evaluate
from app.verification.facts import FileFacts
from app.verification.registry import default_registry
from app.verification.rules.schema import Condition, VerificationRule

#: A file in one of these is still being worked, so a threshold change can still
#: change its outcome. A closed or withdrawn file is history.
_OPEN_STATUSES = (
    LoanFileStatus.DRAFT,
    LoanFileStatus.IN_PROCESSING,
    LoanFileStatus.READY_TO_SUBMIT,
    LoanFileStatus.SUBMITTED,
    LoanFileStatus.IN_CONDITIONS,
)


class AffectedFile(BaseModel):
    """One file whose outcome the proposed overlay would move."""

    loan_file_id: UUID
    #: How the pipeline identifies a file, and what an admin would search for.
    #: The borrower's name is deliberately absent: it would cost a query per file
    #: for a list an admin clicks through anyway.
    display_id: str
    #: The rules that changed verdict on this file — the reason it is listed.
    rules: list[str]


class BlastRadius(BaseModel):
    """What a proposed overlay would do to the lender's open files."""

    #: Files examined. The denominator for both lists.
    evaluated_files: int
    #: Files with no blocking rule today that would gain one.
    newly_blocking: list[AffectedFile]
    #: Files with a blocking rule today that would lose it.
    newly_clearing: list[AffectedFile]
    #: Files where a rule changed verdict without changing whether the file blocks.
    changed_only: list[AffectedFile]
    #: Whether the saved overlay is read by the engine today. **False** right now:
    #: the column this editor writes is not wired into the registry. The estimate
    #: is still correct about the rules — it says what WOULD happen — and a screen
    #: showing it must not imply the change takes effect on save.
    applies_today: bool = False


def _blocks(rule: VerificationRule, passed: bool) -> bool:
    """Whether a failing rule would block, by the same mapping the writer uses.

    `_SEVERITY_TO_STATUS` and `_BLOCKING_SEVERITIES` are the engine's own, not a
    second opinion formed here — the estimate and a real run must agree about what
    "blocking" means or the number is worse than no number.
    """
    if passed:
        return False
    return _SEVERITY_TO_STATUS[rule.severity] in (FindingStatus.RED, FindingStatus.YELLOW)


def _with_proposed(
    rules: list[VerificationRule], proposed: dict[str, Condition]
) -> list[VerificationRule]:
    """The same rule set with the proposed thresholds swapped in.

    `with_condition` is the model's own overlay mechanism — the estimate applies a
    proposal exactly the way a real overlay would, rather than simulating one.
    """
    return [
        rule.with_condition(proposed[rule.rule_id], overlay="proposed")
        if rule.rule_id in proposed
        else rule
        for rule in rules
    ]


def _verdicts(
    facts: FileFacts, rules: list[VerificationRule], loan_file: LoanFile
) -> dict[str, bool]:
    """Which rules would block this file, by rule id. Not-evaluated rules are absent.

    A module-level function rather than a closure over the loop: a closure that
    captures `facts` and `loan_file` reads correctly only while it is called
    inside the same iteration, and that is a footgun the day someone defers it.
    """
    return {
        result.rule.rule_id: _blocks(result.rule, result.passed)
        for result in evaluate(
            facts,
            rules,
            loan_purpose=loan_file.loan_purpose,
            refinance_type=loan_file.refinance_type,
        )
        if result.evaluated
    }


async def estimate_blast_radius(
    db: AsyncSession,
    *,
    company_id: UUID,
    lender_id: UUID,
    overrides: list[OverlayOverrideInput],
) -> BlastRadius | None:
    """Estimate a proposed overlay's effect. Read-only. `None` if not this company's lender."""
    lender = (
        await db.scalars(
            only_active(
                scope_to_company(select(Lender).where(Lender.id == lender_id), Lender, company_id),
                Lender,
            )
        )
    ).first()
    if lender is None:
        return None

    registry = default_registry()
    base_index = {rule.rule_id: rule for rule in registry.rules}
    proposed: dict[str, Condition] = {}
    for override in overrides:
        rule = base_index.get(override.rule_id)
        if rule is None:
            # An unknown rule cannot move anything. The PUT rejects these; this
            # read-only estimate skips rather than raising, so a half-typed
            # proposal still returns a useful answer for the rules it does name.
            continue
        proposed[override.rule_id] = Condition(
            op=rule.condition.op, value=override.value, unit=rule.condition.unit
        )

    files = list(
        (
            await db.scalars(
                only_active(
                    scope_to_company(
                        select(LoanFile).where(
                            LoanFile.lender_id == lender_id,
                            LoanFile.status.in_(_OPEN_STATUSES),
                        ),
                        LoanFile,
                        company_id,
                    ),
                    LoanFile,
                )
            )
        ).all()
    )

    newly_blocking: list[AffectedFile] = []
    newly_clearing: list[AffectedFile] = []
    changed_only: list[AffectedFile] = []
    as_of = date.today()

    for loan_file in files:
        facts = await build_file_facts(db, loan_file=loan_file, as_of=as_of)
        current = registry.resolve(program=loan_file.loan_program, lender_slug=lender.slug)
        after = _with_proposed(current, proposed)

        before_v = _verdicts(facts, current, loan_file)
        after_v = _verdicts(facts, after, loan_file)
        moved = sorted(k for k in after_v if before_v.get(k) != after_v[k])
        if not moved:
            continue

        entry = AffectedFile(
            loan_file_id=loan_file.id, display_id=loan_file.display_id, rules=moved
        )
        blocked_before = any(before_v.values())
        blocked_after = any(after_v.values())
        if blocked_after and not blocked_before:
            newly_blocking.append(entry)
        elif blocked_before and not blocked_after:
            newly_clearing.append(entry)
        else:
            # A rule moved but the file's overall answer did not — still worth
            # reporting, and NOT worth reporting as "newly blocking", which would
            # overstate what changed.
            changed_only.append(entry)

    return BlastRadius(
        evaluated_files=len(files),
        newly_blocking=newly_blocking,
        newly_clearing=newly_clearing,
        changed_only=changed_only,
    )
