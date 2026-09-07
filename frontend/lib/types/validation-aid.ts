/**
 * Validation aid types (LP-89) — the starter inventory + the verdict capture.
 * Mirrors the backend schema. HONEST: validation_status defaults to "grounded_starter";
 * the verdict captures Priya's judgment, it does not fabricate validation.
 */

export interface VerdictView {
  kind: string; // validated / corrected / flagged_remove / add_new
  corrected_value: string | null;
  title: string | null;
  note: string | null;
  recorded_at: string | null;
}

/**
 * Where an item stands in Priya's review (LP-UI-028).
 *
 * A union rather than `string`, so `VALIDATION_STATUS` in lib/status.ts is
 * exhaustive over it — the `CalculatorStatus` lesson: a map written from its own
 * display list instead of its producers ends up exhaustive over the wrong set.
 */
export type ValidationStatus = "grounded_starter" | "validated" | "corrected" | "flagged_remove";

export interface InventoryItem {
  item_id: string;
  item_kind: string; // "rule" | "cross_source" | "calculator"
  program: string | null;
  category: string;
  description: string;
  value: string | null;
  op: string | null;
  unit: string | null;
  citation: string | null;
  source_type: string | null;
  to_verify: boolean;
  starter: boolean;
  validation_status: ValidationStatus;
  verdict: VerdictView | null;
}

export interface ValidationInventory {
  total: number;
  grounded_starter: number;
  validated: number;
  corrected: number;
  flagged_remove: number;
  additions: VerdictView[];
  items: InventoryItem[];
}

export interface VerdictInput {
  item_id?: string | null;
  kind: "validated" | "corrected" | "flagged_remove" | "add_new";
  corrected_value?: string | null;
  title?: string | null;
  note?: string | null;
}
