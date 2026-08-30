/**
 * LEDGER — one status vocabulary                                     LP-UI-005
 * =============================================================================
 * This file replaces SIX independent status maps that each invented their own
 * colour language:
 *
 *   lib/loan-files/status.ts      STATUS_META           (8 loan-file statuses)
 *   lib/loan-files/documents.ts   DOCUMENT_STATUS_META  (7 document statuses)
 *   lib/loan-files/needs.ts       STATE_META            (6 needs statuses)
 *                                 PRIORITY_META         (3 priorities)
 *   lib/verification/rule-findings.ts OUTCOME_META      (7 evaluation outcomes)
 *   components/file/calculators/  STATUS_DOT/STATUS_TONE(7 calculator statuses)
 *
 * A processor was learning "amber" six times, and it meant something different
 * each time. Here every domain resolves onto SIX tones, and a tone always
 * renders the same way: colour + glyph shape + word. Remove the colour and the
 * row still reads — which is what happens for the ~1 in 12 men with a colour
 * vision deficiency, and on a printed file.
 *
 * The LABELS stay domain-specific on purpose. "Must fix" and "Blocked" are the
 * same tone and different words, and the words are the part processors quote.
 *
 * Each map is typed to ITS OWN enum, not to `Record<string, StatusMeta>`. The six
 * maps this file replaced were each exhaustive over their union, and widening to
 * `string` would have thrown that away in one move: adding a member to any of
 * the five unions, or deleting an entry from any map, would compile silently and
 * fall through to `resolveStatus`'s amber fallback at runtime.
 */
import type { DocumentStatus } from "@/lib/types/document";
import type { DtiLimitStatus } from "@/lib/types/dti";
import type { LoanFileStatus } from "@/lib/types/loan-file";
import type { LtvLimitStatus } from "@/lib/types/ltv";
import type { NeedsItemPriority, NeedsItemStatus } from "@/lib/types/needs-item";
import type { Agreement } from "@/lib/types/reconciliation";
import type { EvaluationOutcome, FindingSeverity } from "@/lib/types/verification";

export type Tone =
  | "blocking" // a real problem that stops the file moving
  | "attention" // a human needs to look at this
  | "verified" // checked and good — by a rule or by a person
  | "progress" // in flight; the system is working on it
  | "neutral" // absent, set aside, or simply not applicable
  | "ai"; // provenance, NOT a status. Never means "bad".

export interface StatusMeta {
  tone: Tone;
  label: string;
  /** Spin the glyph (in-flight pipeline states only). */
  spin?: boolean;
}

// --- loan file (lib/types/loan-file.ts LoanFileStatus) ---------------------- //
export const LOAN_FILE_STATUS: Record<LoanFileStatus, StatusMeta> = {
  draft: { tone: "neutral", label: "Draft" },
  in_processing: { tone: "progress", label: "In processing" },
  ready_to_submit: { tone: "verified", label: "Ready to submit" },
  submitted: { tone: "progress", label: "Submitted" },
  in_conditions: { tone: "attention", label: "In conditions" },
  clear_to_close: { tone: "verified", label: "Clear to close" },
  closed: { tone: "neutral", label: "Closed" },
  withdrawn: { tone: "neutral", label: "Withdrawn" },
};

// --- document (lib/types/document.ts DocumentStatus) ------------------------ //
// LABELS ARE THE SHIPPING ONES. An earlier draft of this file renamed `completed`
// to "Verified" and that was wrong, in a way that mattered: `completed` is the
// terminal state of the PROCESSING pipeline (pending -> classifying -> classified
// -> extracting -> completed), and this product tracks stated-vs-verified data as
// a first-class distinction. A document whose extraction finished has been read by
// a model and checked by nobody. Calling that "Verified" tells a processor
// something false, in a compliance tool, using the exact word NEEDS_STATUS.verified
// uses for the case where it is actually true.
//
// This is the rule in SPEC.md doing its job: only the COLOUR vocabulary is being
// unified. The words were argued out already and are not ours to re-open here.
export const DOCUMENT_STATUS: Record<DocumentStatus, StatusMeta> = {
  pending: { tone: "progress", label: "Processing", spin: true },
  classifying: { tone: "progress", label: "Processing", spin: true },
  classified: { tone: "progress", label: "Classified", spin: true },
  extracting: { tone: "progress", label: "Processing", spin: true },
  completed: { tone: "verified", label: "Completed" },
  needs_review: { tone: "attention", label: "Needs review" },
  failed: { tone: "blocking", label: "Failed" },
};

// --- needs (lib/types/needs-item.ts NeedsItemStatus) ------------------------ //
export const NEEDS_STATUS: Record<NeedsItemStatus, StatusMeta> = {
  pending: { tone: "attention", label: "Pending" },
  requested: { tone: "progress", label: "Requested" },
  received: { tone: "progress", label: "Documents attached" },
  verified: { tone: "verified", label: "Verified" },
  rejected: { tone: "blocking", label: "Needs attention" },
  waived: { tone: "neutral", label: "Waived" },
};

export const NEEDS_PRIORITY: Record<NeedsItemPriority, StatusMeta> = {
  blocking: { tone: "blocking", label: "Blocking" },
  standard: { tone: "neutral", label: "Standard" },
  low: { tone: "neutral", label: "Low" },
};

// --- rule engine (lib/types/verification.ts EvaluationOutcome) -------------- //
// Labels preserved verbatim from OUTCOME_META — they were argued over in LP-583
// and LP-581 and are correct. Only the colour mapping is unified.
export const EVALUATION_OUTCOME: Record<EvaluationOutcome, StatusMeta> = {
  open: { tone: "blocking", label: "Must fix" },
  couldnt_check: { tone: "attention", label: "Couldn't check" },
  needs_review: { tone: "attention", label: "Needs review" },
  pending_automation: { tone: "attention", label: "Manual review" },
  satisfied: { tone: "verified", label: "Satisfied" },
  no_longer_applies: { tone: "neutral", label: "No longer applies" },
  not_applicable: { tone: "neutral", label: "Not applicable" },
};

// --- reconciliation (lib/types/reconciliation.ts Agreement) ----------------- //
// Three of the four are `attention`, and that is deliberate rather than lazy.
// Whether a disagreement BLOCKS submission is decided by the rule engine
// (`finding_blocking.py`), not by this ledger — and LP-UI-013 shipped a
// dashboard that re-derived exactly that judgement from enums and disagreed with
// the file screen in both directions. The mockup tints one differing row red and
// another amber; reproducing that split would mean inventing a severity the read
// model does not carry, on the same screen as the findings that own it.
//
// So the tone says "a human needs to look at this" and the WORD says which kind
// of looking: a stated figure no document supports is a gap to chase, a
// documented figure the application never mentioned is a disclosure problem, and
// collapsing those into one word loses which one a processor is holding.
export const RECONCILIATION_AGREEMENT: Record<Agreement, StatusMeta> = {
  match: { tone: "verified", label: "Agrees" },
  differs: { tone: "attention", label: "Differs" },
  missing: { tone: "attention", label: "Not found" },
  not_stated: { tone: "attention", label: "Not stated" },
};

// --- finding severity (lib/types/verification.ts VerificationFinding.status) -- //
// The SEVENTH domain, and the one LP-UI-005 missed: `finding.status` had no meta
// map at all, just `const red = finding.status === "red"` written out wherever it
// was needed. LP-UI-018 needs it as a row verdict, so it joins the vocabulary
// rather than becoming an eighth ad-hoc comparison.
//
// WORDING: "Blocking" and "Warnings" are the shipped labels (finding-filters.tsx,
// verification-stats.tsx), where they count a set. A single row's verdict needs
// the singular, so `yellow` reads "Warning" here. That is a pluralisation, not a
// re-opening of the labels LP-583 and LP-581 settled.
export const FINDING_SEVERITY: Record<FindingSeverity, StatusMeta> = {
  red: { tone: "blocking", label: "Blocking" },
  yellow: { tone: "attention", label: "Warning" },
  green: { tone: "verified", label: "Passed" },
};

// --- calculators ------------------------------------------------------------ //
// THREE producers feed this map through CalculatorsSection's `Tile`, and the
// union must be derived from all three. An earlier version of this type was
// written from the display map it replaced instead, which left it exhaustive
// over the wrong set: `binding:*` and `unknown` both fell through to
// `humanizeUnknown`, and because a `variant="dot"` tile carries its label ONLY
// in `title` and an `sr-only` span, the Maximum-loan tile showed the tooltip
// "Binding:dti" and read that string out to a screen reader.
//
//  1. DtiTile   — `DtiLimitStatus`, plus a literal "unknown" for a gated DTI.
//  2. LtvTile   — `LtvLimitStatus`.
//  3. CalcTile  — `CalculatorView.status`, which is `str | None` on the wire.
//
// The first two are pulled in BY TYPE rather than retyped, so a new member there
// breaks this map at compile time. The third has no frontend union to import;
// its values are listed below against the lines that emit them, which is the
// only place they can be checked against.
export type CalculatorStatus =
  | DtiLimitStatus // "pass" | "over" | "unknown"
  | LtvLimitStatus // "pass" | "over" | "unknown"
  // services/calculators.py:267 — mortgage insurance
  | "required"
  | "not_required"
  // services/calculators.py:342 — self-employed income
  | "declining"
  // services/calculators.py:455 — reserves
  | "sufficient"
  | "insufficient"
  // services/calculators.py:573 — max loan, as "binding:" + MaxLoanConstraint.key
  | "binding:dti"
  | "binding:ltv"
  | "binding:loan_limit";

export const CALCULATOR_STATUS: Record<CalculatorStatus, StatusMeta> = {
  pass: { tone: "verified", label: "Within limit" },
  sufficient: { tone: "verified", label: "Sufficient" },
  not_required: { tone: "neutral", label: "Not required" },
  required: { tone: "attention", label: "Required" },
  declining: { tone: "attention", label: "Declining" },
  over: { tone: "blocking", label: "Over the limit" },
  insufficient: { tone: "blocking", label: "Insufficient" },
  // Not a finding: it says the limit (or the ratio, for a gated DTI) could not be
  // determined, which is honest rather than alarming.
  unknown: { tone: "neutral", label: "Not determined" },
  // Which of the three ceilings came out lowest. EVERY file with a computed max
  // loan has one, so this is information, not a problem — `neutral`, never amber.
  "binding:dti": { tone: "neutral", label: "Limited by DTI" },
  "binding:ltv": { tone: "neutral", label: "Limited by LTV" },
  "binding:loan_limit": { tone: "neutral", label: "Limited by the program limit" },
};

/**
 * Never returns undefined: an enum the backend grew resolves to a visible,
 * honest fallback rather than crashing the row. Mirrors the FALLBACK_META
 * pattern already in lib/verification/rule-findings.ts.
 *
 * Generic in the map's key so a caller keeps its own exhaustiveness — passing
 * `LOAN_FILE_STATUS` does not launder it into `Record<string, StatusMeta>`.
 * `value` stays `string` on purpose: the point of this function is the value the
 * backend sent that this build has never heard of.
 *
 * `fallbackTone` defaults to `attention` because an unrecognised value is
 * usually work someone has to look at. It is a parameter because that is wrong
 * on a numeric headline, where an unknown enum would paint an amber warning over
 * a figure that has nothing wrong with it — see CalculatorCard.
 */
export function resolveStatus<K extends string>(
  map: Record<K, StatusMeta>,
  value: string | null | undefined,
  fallbackTone: Tone = "attention",
): StatusMeta {
  if (!value) return { tone: "neutral", label: "—" };
  const known = (map as Record<string, StatusMeta | undefined>)[value];
  return known ?? { tone: fallbackTone, label: humanizeUnknown(value) };
}

function humanizeUnknown(value: string): string {
  return value.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
}
