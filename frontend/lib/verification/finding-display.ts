/**
 * Finding display helpers (LP-81) — templated wording for re-run stability.
 *
 * Known/canonical finding types get a DETERMINISTIC headline rendered from their
 * type (so a known finding reads IDENTICALLY every run — the AI's free-form wording
 * varies run to run and shows only as secondary detail). Novel ("other") and
 * deterministic-rule findings keep their own message (already deterministic for the
 * engine; the frontier for novel cross-source findings).
 */
import type { VerificationFinding } from "@/lib/types/verification";

// The two cross-source namespaces: the AI layer (LP-78) emits `cross_source.<type>`; the
// deterministic rules (LP-86) emit `xsrc.<category>.<check>`. The display layer recognizes
// BOTH so neither degrades to a raw-rule-id meta-label (LP-92).
const CROSS_SOURCE_PREFIX = "cross_source.";
const XSRC_PREFIX = "xsrc.";

/** Readable label per finding category — the meta-label fallback (never a raw rule_id). */
const CATEGORY_LABELS: Record<string, string> = {
  income: "Income",
  assets: "Assets",
  credit: "Credit",
  property: "Property",
  documentation: "Documentation",
  cross_source: "Cross-source",
  regulatory: "Regulatory",
};

/** The readable label for a finding's category (a safe generic when the category is novel). */
function categoryLabel(finding: VerificationFinding): string {
  return CATEGORY_LABELS[finding.category] ?? "Verification check";
}

/** The deterministic headline per canonical cross-source type. "other" is omitted. */
const TEMPLATES: Record<string, string> = {
  income_variance: "Stated income doesn’t match the documents",
  employer_mismatch: "Stated employer doesn’t match the documents",
  gift_discrepancy: "Gift-funds discrepancy",
  asset_discrepancy: "Stated assets don’t match the documents",
  liability_discrepancy: "Undisclosed obligation in the documents",
  property_address_discrepancy: "Property address discrepancy",
  co_borrower_discrepancy: "Co-borrower discrepancy",
  identity_discrepancy: "Borrower identity discrepancy",
  missing_documentation: "Stated item lacks supporting documentation",
};

/**
 * The canonical cross-source type for a finding (e.g. "income_variance"), or null.
 *
 * Recognizes BOTH cross-source namespaces — the AI layer's `cross_source.` (LP-78) and the
 * deterministic rules' `xsrc.` (LP-86) — so an `xsrc.*` finding resolves to a type instead of
 * returning null (LP-92). Single-source deterministic rules (`conv.*` / `fha.*`) and document
 * findings return null (their headline is already their own message).
 */
export function findingType(finding: VerificationFinding): string | null {
  if (finding.rule_id.startsWith(CROSS_SOURCE_PREFIX)) {
    return finding.rule_id.slice(CROSS_SOURCE_PREFIX.length);
  }
  if (finding.rule_id.startsWith(XSRC_PREFIX)) {
    return finding.rule_id.slice(XSRC_PREFIX.length);
  }
  return null;
}

/**
 * The stable, user-facing headline. Known cross-source types → a deterministic
 * template (identical every run); everything else → the finding's own message.
 */
export function findingHeadline(finding: VerificationFinding): string {
  const type = findingType(finding);
  if (type && TEMPLATES[type]) return TEMPLATES[type];
  return finding.message;
}

/**
 * The AI's free-form description, shown as SECONDARY detail only when a template
 * supplied the headline (so it isn't duplicated for novel/deterministic findings).
 */
export function findingDetail(finding: VerificationFinding): string | null {
  const type = findingType(finding);
  if (type && TEMPLATES[type] && finding.message) return finding.message;
  return null;
}

/**
 * A short, READABLE label for the finding — the gray meta line (LP-92). Never a raw rule_id.
 *
 * - AI cross-source (`cross_source.`, LP-78): the canonical type, e.g. "Income Variance".
 * - Deterministic cross-source (`xsrc.`, LP-86): the category + a descriptor, e.g.
 *   "Income · Cross-source check" — NOT the raw path ("Xsrc Income Employer Count Matches …").
 * - Everything else (single-source `conv.*` / `fha.*`, document findings): the readable
 *   category label ("Income" / "Credit" / …) — never a prettified raw rule_id ("Conv Dti …").
 */
export function findingTypeLabel(finding: VerificationFinding): string {
  if (finding.rule_id.startsWith(CROSS_SOURCE_PREFIX)) {
    const type = finding.rule_id.slice(CROSS_SOURCE_PREFIX.length);
    return type.replace(/[._]/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  }
  if (finding.rule_id.startsWith(XSRC_PREFIX)) {
    return `${categoryLabel(finding)} · Cross-source check`;
  }
  return categoryLabel(finding);
}

/** Whether the finding can be APPLIED (it declares a structured-data change). */
export function canApply(finding: VerificationFinding): boolean {
  return Boolean((finding.details as { apply?: unknown }).apply);
}
