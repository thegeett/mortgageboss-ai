/**
 * Verification types (LP-78) — the run + the cross-source status/findings.
 *
 * Mirrors the backend `VerificationStatusPublic`. The minimal shapes the
 * trigger/staleness UI needs; the rich findings UI is LP-81.
 */
import type { DtiCalculation } from "@/lib/types/dti";
import type { LtvCalculation } from "@/lib/types/ltv";

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
  /** The recorded reason for an OVERRIDDEN finding (LP-81). */
  resolution_note: string | null;
  /** What an APPLIED finding changed (the effect shown in Resolved + the Undo basis, LP-98). */
  applied_record: Record<string, unknown> | null;
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
  /** The file's loan program (conventional / fha) — drives the rule set + the tab header. */
  program: string | null;
  latest_run: VerificationRun | null;
  /** The full stored cross-source set; the client shows only those at/above `aggression.cutoff`. */
  findings: VerificationFinding[];
  aggression: Aggression;
  /** Authoritative: any open in-scope finding at the active cutoff blocks submission. */
  blocked: boolean;
  in_scope_open_count: number;
}

/**
 * The "View fix" apply-impact preview (LP-97) — the DRY-RUN itemized before/after. Reuses the
 * calculator types; only the calculator(s) the apply moves are populated (`affects`).
 */
export interface FindingImpactPreview {
  finding_id: string;
  summary: string;
  applied_record: Record<string, unknown>;
  affects: string[]; // "dti" / "ltv"
  dti_before: DtiCalculation | null;
  dti_after: DtiCalculation | null;
  ltv_before: LtvCalculation | null;
  ltv_after: LtvCalculation | null;
}
