/**
 * The reconciliation read model (LP-UI-017), as the browser sees it.
 *
 * Mirrors `backend/app/services/reconciliation.py`. Every field here is decided
 * on the server: which rows exist, whether the two sides agree, and why a row
 * has no source. Nothing in this shape is re-derived in the UI — the ledger and
 * the findings list appear on the same screen, and a second opinion about
 * whether two numbers agree would put them at odds. See ADR-391.
 */

import type { FindingSeverity } from "@/lib/types/verification";

/** What the two columns say about one field. */
export type Agreement = "match" | "differs" | "missing" | "not_stated";

/**
 * How to render the two values. The server knows which rows are amounts; the
 * browser cannot tell `"85087.00"` from a name by looking at it, and a
 * comparison only reads if its two columns line up digit against digit.
 */
export type RowUnit = "money" | "text";

/** Where the found value came from — the audit anchor for one row. */
export interface RowSource {
  document_id: string;
  filename: string;
  page: number | null;
  snippet: string | null;
}

/**
 * The rule engine's verdict on the same question a row asks (A20).
 *
 * When this is present the FINDING is the authority and the row's own comparison
 * is the evidence beneath it. The two can genuinely disagree: LP-80 makes the
 * income variance overrideable per lender and the read model does not resolve
 * overlays, so under an overlay the ledger compares against the default while
 * the engine compares against the lender's number. A screen that averaged them,
 * or picked one silently, would be the LP-UI-013 defect again.
 */
export interface RowFinding {
  finding_id: string;
  rule_id: string;
  status: FindingSeverity;
  message: string;
  /** Open findings on this rule for this file. One verdict shows; this says how many exist. */
  count: number;
}

export interface ReconciliationRow {
  field_key: string;
  label: string;
  /** Raw for `money` rows — format with `formatMoneyPrecise`, never by hand. */
  stated_value: string | null;
  found_value: string | null;
  unit: RowUnit;
  agreement: Agreement;
  source: RowSource | null;
  /** Why this row has no `source`. Never null when `source` is null. */
  source_note: string | null;
  finding: RowFinding | null;
}
