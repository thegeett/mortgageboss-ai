/**
 * Verification types (LP-78) — the run + the cross-source status/findings.
 *
 * Mirrors the backend `VerificationStatusPublic`. The minimal shapes the
 * trigger/staleness UI needs; the rich findings UI is LP-81.
 */

export interface VerificationRun {
  id: string;
  status: "running" | "completed" | "failed";
  trigger: string;
  started_at: string | null;
  completed_at: string | null;
  red_count: number;
  yellow_count: number;
  green_count: number;
  total_cost_estimate: number | null;
}

export interface VerificationFinding {
  id: string;
  rule_id: string;
  origin: string;
  status: "red" | "yellow" | "green";
  category: string;
  message: string;
  confidence: number;
  source_page: number | null;
  source_snippet: string | null;
  resolution_status: string;
  details: Record<string, unknown>;
}

export interface VerificationStatus {
  stale: boolean;
  latest_run: VerificationRun | null;
  findings: VerificationFinding[];
}
