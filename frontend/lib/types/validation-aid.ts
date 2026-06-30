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
  validation_status: string; // grounded_starter / validated / corrected / flagged_remove
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
