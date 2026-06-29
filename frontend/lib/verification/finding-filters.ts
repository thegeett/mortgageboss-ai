/**
 * Finding filters (LP-88) — the severity + category pills, ORTHOGONAL to the dial.
 *
 * The aggression dial (LP-79) sets the CONFIDENCE floor (which findings are in-scope). These
 * pills filter the in-scope set by SEVERITY (red/yellow) and CATEGORY (income/credit/…). The
 * two compose: dial first (confidence), then pills (severity + category) within it. Pure
 * client-side slicing over the already-fetched findings — instant, no round-trip.
 */
import type { VerificationFinding } from "@/lib/types/verification";

export type SeverityFilter = "all" | "red" | "yellow";

export interface FindingFilters {
  severity: SeverityFilter;
  category: string | "all";
}

export const DEFAULT_FILTERS: FindingFilters = { severity: "all", category: "all" };

export const CATEGORY_LABELS: Record<string, string> = {
  income: "Income",
  assets: "Assets",
  credit: "Credit",
  property: "Property",
  documentation: "Documentation",
  cross_source: "Cross-source",
  regulatory: "Regulatory",
};

export function categoryLabel(category: string): string {
  return CATEGORY_LABELS[category] ?? category;
}

/** Whether a finding passes the severity + category pills (the dial is applied separately). */
export function matchesFilters(finding: VerificationFinding, filters: FindingFilters): boolean {
  if (filters.severity !== "all" && finding.status !== filters.severity) return false;
  if (filters.category !== "all" && finding.category !== filters.category) return false;
  return true;
}

/** The distinct categories present across a set of findings (for the category pills). */
export function categoriesPresent(findings: VerificationFinding[]): string[] {
  const seen = new Set<string>();
  for (const f of findings) seen.add(f.category);
  return Array.from(seen);
}
