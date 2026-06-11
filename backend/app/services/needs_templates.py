"""Provisional initial needs-list templates by loan program (LP-30).

WARNING / TODO(domain): this is a **PROVISIONAL** starter template. The
authoritative, program- and lender-specific needs lists must be captured from
the domain expert (Priya) — a Phase 0 closeout item. This baseline is
intentionally modest and easily extensible (a simple data structure); do NOT
treat it as complete or authoritative. Refine the items, categories, and
priorities — and add the real program-specific requirements — with Priya.
"""

from dataclasses import dataclass

from app.models.document import DocumentCategory
from app.models.lender import LoanProgram
from app.models.needs_item import NeedsItemPriority


@dataclass(frozen=True)
class NeedTemplate:
    """One provisional needs-list entry: what to ask for and how to file it."""

    title: str
    category: DocumentCategory
    needs_type: str
    priority: NeedsItemPriority


# Universal baseline — applies to every file regardless of program. PROVISIONAL.
UNIVERSAL_NEEDS: list[NeedTemplate] = [
    NeedTemplate(
        "Government-issued photo ID",
        DocumentCategory.BORROWER_INFO,
        "government_id",
        NeedsItemPriority.STANDARD,
    ),
    NeedTemplate(
        "Most recent pay stubs (last 30 days)",
        DocumentCategory.INCOME_EMPLOYMENT,
        "paystub",
        NeedsItemPriority.STANDARD,
    ),
    NeedTemplate(
        "Bank statements (last 2 months)",
        DocumentCategory.ASSETS,
        "bank_statement",
        NeedsItemPriority.STANDARD,
    ),
    NeedTemplate(
        "W-2s (last 2 years)",
        DocumentCategory.INCOME_EMPLOYMENT,
        "w2",
        NeedsItemPriority.STANDARD,
    ),
]

# FHA-specific additions. PROVISIONAL — placeholder pending real FHA requirements.
FHA_NEEDS: list[NeedTemplate] = [
    NeedTemplate(
        "Photo ID + SSN verification (FHA)",
        DocumentCategory.BORROWER_INFO,
        "fha_id_ssn",
        NeedsItemPriority.STANDARD,
    ),
    # TODO(domain): add the real FHA-specific requirements (e.g. CAIVRS clearance,
    # gift-letter rules, etc.) with Priya. This single item is a placeholder.
]


def needs_for_program(loan_program: LoanProgram | None) -> list[NeedTemplate]:
    """Return the provisional starter needs templates for a program.

    Always includes the universal baseline; FHA adds its placeholder extras.
    ``None`` (program not yet known) → the universal baseline only.
    """
    needs = list(UNIVERSAL_NEEDS)
    if loan_program == LoanProgram.FHA:
        needs += FHA_NEEDS
    return needs
