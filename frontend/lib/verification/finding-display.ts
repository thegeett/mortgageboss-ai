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

const CROSS_SOURCE_PREFIX = "cross_source.";

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

/** The canonical cross-source type for a finding (e.g. "income_variance"), or null. */
export function findingType(finding: VerificationFinding): string | null {
  if (finding.rule_id.startsWith(CROSS_SOURCE_PREFIX)) {
    return finding.rule_id.slice(CROSS_SOURCE_PREFIX.length);
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

/** A short label for the finding type (humanized) — for the meta line. */
export function findingTypeLabel(finding: VerificationFinding): string {
  const type = findingType(finding);
  const raw = type ?? finding.rule_id;
  return raw.replace(/[._]/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

/** Whether the finding can be APPLIED (it declares a structured-data change). */
export function canApply(finding: VerificationFinding): boolean {
  return Boolean((finding.details as { apply?: unknown }).apply);
}
