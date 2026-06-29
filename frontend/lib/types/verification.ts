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

/** The three aggression levels (LP-79) — confidence cutoffs, Conservative highest. */
export type AggressionLevel = "conservative" | "balanced" | "thorough";

/**
 * The aggression dial's state for a file (LP-79). `level` is the active level (the
 * per-file `override` if set, else the user's `default`); `cutoff` is the confidence
 * threshold it applies. `cutoffs` maps every level to its cutoff so the client can
 * re-filter the (already-returned) findings instantly when the dial moves — no AI re-run.
 */
export interface Aggression {
  level: AggressionLevel;
  default: AggressionLevel;
  override: AggressionLevel | null;
  cutoff: number;
  cutoffs: Record<AggressionLevel, number>;
}

export interface VerificationStatus {
  stale: boolean;
  latest_run: VerificationRun | null;
  /** The full stored cross-source set; the client shows only those at/above `aggression.cutoff`. */
  findings: VerificationFinding[];
  aggression: Aggression;
  /** Authoritative: any open in-scope finding at the active cutoff blocks submission. */
  blocked: boolean;
  in_scope_open_count: number;
}
