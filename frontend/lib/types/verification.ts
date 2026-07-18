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
  /** LP-114: WHICH document grounds the finding — its id (to open it) + readable filename (to name
   * it), so the processor can verify the judgment against the actual document. Null when there's no
   * single source document (a file-level/computed rule, or an AI finding whose type didn't resolve). */
  source_document_id: string | null;
  source_document_filename: string | null;
  /** LP-114.1: ALL documents this finding was derived from (a cross-source finding spans several —
   * a pay stub AND a W-2 for one employer). The single fields above are the primary/trigger; this
   * is the full set. Empty when no source could be attributed (graceful). */
  source_documents: FindingSourceDocument[];
  resolution_status: string;
  /** The recorded reason for an OVERRIDDEN finding (LP-81). */
  resolution_note: string | null;
  /** What an APPLIED finding changed (the effect shown in Resolved + the Undo basis, LP-98). */
  applied_record: Record<string, unknown> | null;
  details: Record<string, unknown>;
}

/** One document a finding was derived from (LP-114.1) — id (to open it) + readable filename. */
export interface FindingSourceDocument {
  id: string;
  filename: string;
}

/**
 * The five §8 outcome states a rule evaluation can conclude (LP-316). Orthogonal to the RED/YELLOW/GREEN
 * severity color: this is the VERDICT itself. `not_applicable` subjects are not persisted (so they never
 * arrive as a finding — Tab 4 is structurally empty, LP-375/376); `no_longer_applies` only appears across
 * runs (the subject left the file), so run #1 never has one.
 */
export type EvaluationOutcome =
  | "open"
  | "satisfied"
  | "needs_review"
  | "couldnt_check"
  | "no_longer_applies";

/** One load-bearing tag inline (LP-316) — the provenance a human reads to see WHY a verdict held. */
export interface RuleFindingTag {
  tag_id: string;
  value: unknown;
  confidence: number | null;
  reasoning: string | null;
  source_facts: string[];
}

/**
 * A GOVERNED rule-engine finding (LP-316/375) — a DISTINCT shape from `VerificationFinding` (the legacy
 * AI sweep / retired xsrc quarantine). The two are deliberately different TYPES so their lists can never
 * be concatenated or their counts summed. Carries the §8 outcome (the tab), the reason, the SPEC's
 * guideline citation (read-time, never AI-recalled), inline provenance, and the ratification marker.
 */
export interface RuleFinding {
  id: string;
  rule_id: string;
  evaluation_outcome: EvaluationOutcome;
  status: "red" | "yellow" | "green";
  category: string;
  /** The reason — every non-satisfied outcome carries one (§8's honesty contract). */
  message: string;
  /** The stable per-subject content-id (LP-312) — the reconciler's KEY (LP-322), NEVER rendered to a user. */
  subject_key: string | null;
  /** The processor-facing subject name (LP-377-B) — a filename / amount / borrower / "Loan-level", resolved
   *  read-time per subject TYPE. This is what a row and the provenance card show; never the content-id. */
  subject_label: string;
  /** The rule's guideline citation, from the SPEC (never AI-recalled). */
  guideline: string | null;
  load_bearing_tags: RuleFindingTag[];
  /** A judgment/AI verdict awaiting human ratification (not a violation). */
  ratification_pending: boolean;
  how_to_fix: string | null;
  confidence: number;
  resolution_status: string;
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
  /** The LEGACY quarantine (Tab 5) — the AI sweep + retired xsrc rows (evaluation_outcome null). The
   * client shows only those at/above `aggression.cutoff`. Unchanged shape + behaviour (LP-375). */
  findings: VerificationFinding[];
  /** The GOVERNED rule-engine findings (LP-316) — a SEPARATE typed list (LP-375) driving §8 tabs 1-4,
   * including `satisfied` (Tab 2). Never merged/summed with `findings`. */
  rule_findings: RuleFinding[];
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
