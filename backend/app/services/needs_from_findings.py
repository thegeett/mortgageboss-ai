"""Seed the Need List from what the RULES say is missing (LP-623).

THE GAP THIS CLOSES. On LF-ABRS the Need List carried thirteen items and not one of them was the
appraisal, the title commitment, the credit report, the rate lock or the Closing Disclosure — while
ten findings said each was absent. A processor working that list to zero would have submitted a file
with no appraisal, no title and no credit report.

The two halves of the system each knew half the answer. The needs floor is six deterministic rules
(``needs_engine.seed_floor_needs``) and none of them is property- or credit-related; the AI reasoner
(LP-69) is asked what is DISTINCTIVE about a file, so it reliably under-proposes the documents that
are true of every file. Meanwhile every rule already declares the documents it reads
(``requires_documents``, LP-541/620) and the read path already computes which of them no document on
the file satisfies. That answer only ever powered a button a processor had to press per finding.

WHAT THIS IS NOT. It does not decide anything a rule did not already decide, and it cannot invent a
document: a need appears here only because a rule that IS IN SCOPE reported a gap. A rule that
resolved, retired, or was never applicable contributes nothing.
"""

from __future__ import annotations

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from app.models.finding import (
    EvaluationOutcome,
    Finding,
    FindingOrigin,
    FindingResolutionStatus,
    FindingStatus,
)
from app.models.helpers import only_active
from app.models.loan_file import LoanFile
from app.models.needs_item import (
    NeedsItem,
    NeedsItemDisposition,
    NeedsItemOrigin,
    NeedsItemPriority,
)
from app.services.needs_engine import canonical_need_type, category_for_need_type
from app.services.needs_items import create_needs_item
from app.verification.rule_engine.reasons import document_label
from app.verification.rules.specs import RuleSpecNotFound, load_rule_spec

logger = structlog.get_logger(__name__)

#: The outcomes that mean a rule is still WAITING on something. A satisfied rule needs nothing, and a
#: not_applicable one is out of scope — §8's honesty axis is exactly the right filter here.
_UNFINISHED = (
    EvaluationOutcome.COULDNT_CHECK,
    EvaluationOutcome.OPEN,
    EvaluationOutcome.NEEDS_REVIEW,
)


async def seed_needs_from_findings(db: AsyncSession, loan_file: LoanFile) -> list[NeedsItem]:
    """Create one need per DOCUMENT the file's unfinished rule findings are waiting on.

    ONE PER DOCUMENT, not one per finding — four credit-report findings are one errand, and the same
    grouping the bulk-request button uses (LP-562). The rules waiting on it go in ``reasoning``, so the
    need is traceable back to why it exists.

    DEDUPED AGAINST THE WHOLE LIST, in any status: a document already requested, already received, or
    already waived must not reappear. Re-running is therefore a no-op once the list is settled, which
    is what makes it safe to call on every verification.

    Idempotence rests on ``needs_type``, so a document type the catalog does not carry is SKIPPED
    rather than seeded under a name nothing can match (LP-623 — the unsatisfiable-need defect this
    ticket also fixes on the AI path). Uses ``flush``; the caller owns the transaction.
    """
    findings = (
        await db.scalars(
            only_active(
                select(Finding).where(
                    Finding.loan_file_id == loan_file.id,
                    Finding.origin != FindingOrigin.AI_CROSS_SOURCE,
                    Finding.evaluation_outcome.in_(_UNFINISHED),
                    Finding.resolution_status == FindingResolutionStatus.OPEN,
                ),
                Finding,
            )
        )
    ).all()
    if not findings:
        return []

    doc_rows = (
        await db.execute(
            only_active(
                select(Document.document_type).where(Document.loan_file_id == loan_file.id),
                Document,
            )
        )
    ).all()
    on_file = {row.document_type for row in doc_rows if row.document_type}
    purpose = loan_file.loan_purpose.value if loan_file.loan_purpose else None

    wanted: dict[str, list[Finding]] = {}
    for finding in findings:
        for slug in _missing_slugs(finding, on_file, purpose):
            wanted.setdefault(slug, []).append(finding)
    if not wanted:
        return []

    # CANONICAL ON BOTH SIDES, or the same document arrives twice under two names. LF-ABRS carries an
    # AI need stored as `verification_of_employment` while IN-4 and IN-8 declare `voe`; compared raw,
    # neither suppresses the other and the list grows a second line for one errand. The needs list has
    # tolerated these aliases at MATCH time since bug-001 — this is the same question asked earlier.
    existing = {
        canonical_need_type(n.needs_type) or n.needs_type
        for n in (
            await db.scalars(
                only_active(
                    select(NeedsItem).where(NeedsItem.loan_file_id == loan_file.id), NeedsItem
                )
            )
        ).all()
        if n.needs_type
    }

    created: list[NeedsItem] = []
    for slug, rule_findings in sorted(wanted.items()):
        if (canonical_need_type(slug) or slug) in existing:
            continue
        rules = ", ".join(sorted({f.rule_id for f in rule_findings if f.rule_id}))
        created.append(
            await create_needs_item(
                db,
                loan_file_id=loan_file.id,
                title=document_label(slug),
                needs_type=slug,
                category=category_for_need_type(slug),
                origin=NeedsItemOrigin.FINDING,
                priority=_priority_for(rule_findings),
                # CONFIRMED, not PROPOSED. A rule declaring a document it needs and the file not
                # holding one is deterministic — the same standing as a floor need, and the opposite
                # of an AI proposal a human must weigh. Making a processor confirm the appraisal is a
                # real need is the click this exists to remove.
                disposition=NeedsItemDisposition.CONFIRMED,
                reasoning=f"Required by verification rule(s) {rules}, which found no {document_label(slug)} on the file.",
                source_facts=[
                    {"kind": "rule", "label": f"{rules} — no {document_label(slug)} on file"}
                ],
            )
        )
        # LP-624 — the CANONICAL form, matching the guard above. Adding the raw slug while checking
        # the canonical one meant two spec groups whose heads canonicalize to the same document type
        # would both seed. No spec declares an aliased head today, so this was latent — and a trap for
        # whoever adds the next alias.
        existing.add(canonical_need_type(slug) or slug)

    if created:
        logger.info(
            "needs_seeded_from_findings",
            loan_file_id=str(loan_file.id),
            count=len(created),
            types=[n.needs_type for n in created],  # document types, not PII
        )
    return created


def _missing_slugs(finding: Finding, on_file: set[str], purpose: str | None) -> list[str]:
    """The CATALOG SLUGS this finding is waiting on — the group's first member, not its label.

    The bulk-request path slugs the readable label back into a type
    (``"credit report"`` -> ``credit_report``), which round-trips for most names and silently mangles
    any that do not. The declaration already holds the slug, so it is read directly.
    """
    try:
        spec = load_rule_spec(finding.rule_id or "")
    except (RuleSpecNotFound, ValueError):
        return []
    slugs: list[str] = []
    for group in spec.requires_documents or ():
        if set(group) & on_file:
            continue
        head = group[0]
        if canonical_need_type(head) is None:
            continue  # not a document anything can be matched against — never seed it
        if purpose == "refinance" and _is_purchase_only(group):
            continue
        slugs.append(head)
    return slugs


def _is_purchase_only(group: tuple[str, ...]) -> bool:
    """A group every alternative of which only exists on a purchase (LP-542's rule, reused).

    A refinance has no purchase contract and never will, so seeding one sends a processor after
    something unobtainable — the mistake LP-542 fixed on the findings side and which would otherwise
    arrive here by another route.
    """
    from app.schemas.verification import _PURCHASE_ONLY

    return set(group) <= _PURCHASE_ONLY


def _priority_for(findings: list[Finding]) -> NeedsItemPriority:
    """BLOCKING if any waiting rule is red — the document blocks the more severe of its reasons."""
    if any(f.status is FindingStatus.RED for f in findings):
        return NeedsItemPriority.BLOCKING
    return NeedsItemPriority.STANDARD
