"""The document-type catalog — the single source of truth for tier + category (LP-58).

Phase 2 scales the document pipeline from 3 types to ~80-100 via a **three-tier**
model (:class:`~app.models.document.Tier`): not every type earns full structured
extraction. This catalog is where that knowledge lives — one maintainable mapping
of ``document_type -> (tier, category)`` that the pipeline consults *after*
classification to route a document to the right handling path:

  * **Tier 1** → the existing :data:`app.ai.extraction.EXTRACTORS` registry (full
    structured extraction). The 3 Phase-1 types (``pay_stub`` / ``w2`` /
    ``bank_statement``) are Tier 1 and unchanged. The other Tier-1 types are
    *cataloged* here now; their extractors register in LP-60..64.
  * **Tier 2** → recognized: classified + categorized + (LP-65) a short summary.
  * **Tier 3** → long-tail: a generic analyzer (LP-66). Anything not in the
    catalog defaults here.

Why a catalog and not scattered ``if/elif`` or a DB table:

  * **Maintainable** — adding/retiring a type is a one-line edit; no migration
    (tier/category are app-layer knowledge, ADR-053/ADR-167), no code branches.
  * **Single source of truth** — both the tier (for routing) and the category
    (for filing / needs-matching) come from here, so they never drift apart.

The catalog **grows** (LP-59 adds the full ~80-type set + the matching
classification) and **refines with Priya** (the domain expert) as the taxonomy
settles. It is intentionally seeded — not exhaustive — today: the 3 existing
Tier-1 types, the planned Tier-1 types, and a starter Tier-2 set per category
(enough to prove tier-aware routing end to end).
"""

from app.models.document import DocumentCategory, Tier

# --------------------------------------------------------------------------- #
# The catalog — document_type -> (tier, category)
# --------------------------------------------------------------------------- #
# The slugs match the classifier's lowercase ``document_type`` output. Keep this
# grouped by tier (then category) so it reads as a maintainable taxonomy, not a
# flat lookup table. LP-59 fills it out to all ~80 types.
CATALOG: dict[str, tuple[Tier, DocumentCategory]] = {
    # --- Tier 1 — first-class extraction --------------------------------- #
    # Existing (extractors built in Phase 1; route as Tier 1 unchanged).
    "pay_stub": (Tier.TIER_1, DocumentCategory.INCOME_EMPLOYMENT),
    "w2": (Tier.TIER_1, DocumentCategory.INCOME_EMPLOYMENT),
    "bank_statement": (Tier.TIER_1, DocumentCategory.ASSETS),
    # Planned (cataloged as Tier 1 now; extractors arrive in LP-60..64). Until
    # an extractor is registered, the pipeline handles these as classified-only
    # (a terminal status) — see the routing in app.tasks.document_processing.
    "tax_return": (Tier.TIER_1, DocumentCategory.INCOME_EMPLOYMENT),
    "1099": (Tier.TIER_1, DocumentCategory.INCOME_EMPLOYMENT),
    "voe": (Tier.TIER_1, DocumentCategory.INCOME_EMPLOYMENT),
    "profit_and_loss": (Tier.TIER_1, DocumentCategory.INCOME_EMPLOYMENT),
    "investment_account": (Tier.TIER_1, DocumentCategory.ASSETS),
    "retirement_account": (Tier.TIER_1, DocumentCategory.ASSETS),
    "gift_letter": (Tier.TIER_1, DocumentCategory.ASSETS),
    "purchase_agreement": (Tier.TIER_1, DocumentCategory.PROPERTY),
    "homeowners_insurance": (Tier.TIER_1, DocumentCategory.PROPERTY),
    "mortgage_statement": (Tier.TIER_1, DocumentCategory.PROPERTY),
    "property_tax_bill": (Tier.TIER_1, DocumentCategory.PROPERTY),
    "hoa_statement": (Tier.TIER_1, DocumentCategory.PROPERTY),
    "drivers_license": (Tier.TIER_1, DocumentCategory.BORROWER_INFO),
    "divorce_decree": (Tier.TIER_1, DocumentCategory.BORROWER_INFO),
    "letter_of_explanation": (Tier.TIER_1, DocumentCategory.BORROWER_INFO),
    # --- Tier 2 — recognized (starter set; LP-59 adds the full ~80) ------ #
    # A handful per category — enough to prove Tier-2 routing. Summary path
    # (LP-65) is stubbed; these are classified + categorized today.
    "verification_of_deposit": (Tier.TIER_2, DocumentCategory.ASSETS),
    "award_letter": (Tier.TIER_2, DocumentCategory.INCOME_EMPLOYMENT),
    "social_security_statement": (Tier.TIER_2, DocumentCategory.INCOME_EMPLOYMENT),
    "flood_certification": (Tier.TIER_2, DocumentCategory.PROPERTY),
    "appraisal_report": (Tier.TIER_2, DocumentCategory.PROPERTY),
    "title_commitment": (Tier.TIER_2, DocumentCategory.PROPERTY),
    "credit_report": (Tier.TIER_2, DocumentCategory.CREDIT),
    "credit_explanation_letter": (Tier.TIER_2, DocumentCategory.CREDIT),
    "closing_disclosure": (Tier.TIER_2, DocumentCategory.DISCLOSURES),
    "loan_estimate": (Tier.TIER_2, DocumentCategory.DISCLOSURES),
    "passport": (Tier.TIER_2, DocumentCategory.BORROWER_INFO),
    "social_security_card": (Tier.TIER_2, DocumentCategory.BORROWER_INFO),
}

# The default for any type not in the catalog: the long-tail Tier 3 / Misc bucket.
# A confidently-classified but uncataloged type lands here (the generic analyzer,
# LP-66); a low-confidence/unknown classification is gated to NEEDS_REVIEW by the
# pipeline before it ever reaches tier routing.
_DEFAULT: tuple[Tier, DocumentCategory] = (Tier.TIER_3, DocumentCategory.MISC)


def get_tier_and_category(document_type: str | None) -> tuple[Tier, DocumentCategory]:
    """Look up a document type's ``(tier, category)`` — the catalog's core read.

    Unknown or absent types fall back to the long-tail default
    (Tier 3 / Misc). Never raises — every document gets a tier + category.
    """
    if not document_type:
        return _DEFAULT
    return CATALOG.get(document_type, _DEFAULT)


def get_tier(document_type: str | None) -> Tier:
    """The tier the pipeline should handle ``document_type`` as (default Tier 3)."""
    return get_tier_and_category(document_type)[0]


def get_category(document_type: str | None) -> DocumentCategory:
    """The filing category for ``document_type`` (default Misc).

    Catalog-driven (LP-58) — replaces the Phase-1 provisional type→category map.
    """
    return get_tier_and_category(document_type)[1]


def is_cataloged(document_type: str | None) -> bool:
    """Whether ``document_type`` is a known (cataloged) type, vs. long-tail."""
    return bool(document_type) and document_type in CATALOG
