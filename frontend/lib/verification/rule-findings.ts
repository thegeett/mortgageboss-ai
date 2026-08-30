/**
 * The §8 tab model (LP-376) — the FIVE outcome states → FOUR governed tabs (+ the legacy quarantine).
 *
 * This is the architecture, implemented (not a decision): `open`/`couldnt_check`/`needs_review` all live in
 * Tab 1 (Needs attention) — different WORK, so they are grouped and labelled, never merged; `satisfied` is
 * Tab 2; `no_longer_applies` is Tab 3; `not_applicable` is Tab 4 (structurally empty — those subjects are not
 * persisted). The legacy AI-sweep / retired-xsrc list is Tab 5, kept SEPARATE (never summed with the governed
 * counts — LP-375 made that structural; this must not undo it).
 *
 * THE HONESTY CONTRACT the UI must preserve (LP-329/330): `couldnt_check` BLOCKS and lives in Tab 1 — never a
 * pass, never Tab 2/4. Tab 3 ≠ Tab 4 (the subject left vs never relevant). `needs_review` ≠ `open` (a
 * ratification-pending judgment is not a violation) — same tab, the detail says which.
 */
import { humanize } from "@/lib/format";
import { EVALUATION_OUTCOME, type Tone, resolveStatus } from "@/lib/status";
import type { EvaluationOutcome, RuleFinding } from "@/lib/types/verification";

export type GovernedTabId = "attention" | "satisfied" | "no_longer_applies" | "not_applicable";
// LP-586 — `cross_source` is neither governed nor legacy: a separate AI pass over the SNAPSHOT,
// with its own stability contract and no apply. It gets its own id rather than being folded
// into either family, because it answers a different question from both.
export type TabId = GovernedTabId | "legacy" | "cross_source";

/** The §8 outcomes → their governed tab. */
const OUTCOME_TAB: Record<EvaluationOutcome, GovernedTabId> = {
  open: "attention",
  couldnt_check: "attention",
  needs_review: "attention",
  pending_automation: "attention", // LP-391 — a manual-review flag lives where the work is (Tab 1)
  satisfied: "satisfied",
  no_longer_applies: "no_longer_applies",
  // LP-588 — routed explicitly rather than left to the fallback. The backend does not emit this
  // today, but the fallback sends anything unrecognised to "attention", so the day it does, a
  // subject the rule does NOT apply to would appear as work to do.
  not_applicable: "not_applicable",
};

export function tabForOutcome(outcome: EvaluationOutcome): GovernedTabId {
  // Fallback to "attention" for an outcome this union doesn't know (a backend enum that grew past the
  // frontend): an unrecognised verdict must surface where action lives — never silently dropped, and
  // never crash the whole panel via `buckets[undefined].push`.
  return OUTCOME_TAB[outcome] ?? "attention";
}

/** Tab 1's three outcomes in PRIORITY order — `open` first so the real violations never drown in a pile
 * of `couldnt_check` (LP-333's warning, one layer up). */
export const ATTENTION_ORDER: readonly EvaluationOutcome[] = [
  "open",
  "couldnt_check",
  "needs_review",
  "pending_automation",
] as const;

export interface OutcomeMeta {
  /** The short label a processor triages on. */
  label: string;
  /** One line: what THIS outcome means (so `couldnt_check` reads as a gap, not a violation). */
  blurb: string;
  tone: Tone;
}

/**
 * The prose. LP-UI-005 moved the LABEL and the TONE to `lib/status.ts`
 * (EVALUATION_OUTCOME) so every domain shares one colour vocabulary; what stays
 * here is the domain writing, which is not presentation and was argued out in
 * LP-583 and LP-581.
 *
 * Two outcomes changed TONE and neither changed wording: `needs_review` and
 * `pending_automation` were `info` and are now `attention`. Both mean a human
 * must look — which is what `attention` means, and which is the tab they were
 * already bucketed into by ATTENTION_ORDER.
 */
const OUTCOME_BLURB: Record<EvaluationOutcome, string> = {
  // LP-583 — "Violation" is not vocabulary at any stage of the loan: processors and underwriters
  // say "condition", post-close QC says "defect" (Fannie's and FHA's taxonomies are both Defect
  // Taxonomies). It was also the only severity NOUN in a set of action phrases — "Needs review",
  // "Couldn't check". "Must fix" matches the register and says what to do.
  open: "A rule fired — a real finding that needs action.",
  couldnt_check:
    "The rule applies and the thing might exist, but a required input is missing — a gap, not a pass.",
  // LP-581 — plain English: "ratification" is the engine's word (ADR-336), not a processor's.
  needs_review: "A judgment awaiting your sign-off — not a violation.",
  pending_automation:
    "This file has something in scope, but the automated check isn't active yet — a human must review it. The system has NOT judged it (not a pass/fail).",
  satisfied: "The rule ran and passed — with evidence.",
  no_longer_applies: "The subject left the file since a prior run.",
  not_applicable: "The rule is irrelevant to this subject's nature — not a pass, and not a gap.",
};

/** Shown for an outcome outside this union (a backend enum that grew) — surfaced, never crashed on. */
const FALLBACK_META: OutcomeMeta = {
  label: "Unknown outcome",
  blurb:
    "An outcome this view doesn't recognise yet — surfaced here so it is never silently dropped.",
  tone: "attention",
};

/** Never returns undefined: an outcome outside the union → a safe fallback, so one unexpected value
 *  degrades a single row instead of crashing the whole tabs render. */
export function outcomeMeta(outcome: EvaluationOutcome): OutcomeMeta {
  const blurb = OUTCOME_BLURB[outcome];
  if (!blurb) return FALLBACK_META;
  const { label, tone } = resolveStatus(EVALUATION_OUTCOME, outcome);
  return { label, blurb, tone };
}

export interface GovernedBuckets {
  attention: RuleFinding[];
  satisfied: RuleFinding[];
  no_longer_applies: RuleFinding[];
  not_applicable: RuleFinding[];
}

/** Bucket the governed `rule_findings` into their §8 tabs (Tab 4 stays empty — those never persist). */
export function bucketRuleFindings(findings: RuleFinding[]): GovernedBuckets {
  const buckets: GovernedBuckets = {
    attention: [],
    satisfied: [],
    no_longer_applies: [],
    not_applicable: [],
  };
  for (const finding of findings) {
    buckets[tabForOutcome(finding.evaluation_outcome)].push(finding);
  }
  return buckets;
}

/**
 * Group a tab's findings BY RULE — so N subjects of one check render as ONE summary row a processor can
 * act on, not N lines. Each group keeps its members (the model is untouched — this is a display collapse
 * only), so a reader can expand to WHICH ones. Order is preserved.
 *
 * LP-376-C keyed this on `rule_id + message`, which collapsed only findings whose text was IDENTICAL.
 * That works for a deterministic rule (ID-7's 4 unclassified documents all read the same) and does
 * nothing at all for a JUDGMENT rule: the model writes a distinct sentence per subject, so AS-12's ten
 * deposits produced ten groups of one and never collapsed. LP-518 keys on the rule alone.
 *
 * Callers group WITHIN one outcome bucket (Tab 1 splits by outcome first, and the other tabs are a single
 * outcome by construction), so a group never mixes an `open` with a `satisfied`. The header must not
 * assume a shared message — see `CollapsedFindings`, which summarises when the members disagree.
 */
/** Order two rule ids the way a processor reads them: by family, then NUMERICALLY (LP-613).
 *
 * ⚠️ NOT a string sort. Rule ids are `AS-1`, `AS-4`, `AS-8`, `AS-10` — lexicographically that is
 * AS-1, AS-10, AS-4, which puts the tenth rule second and reads as an accident. The number is a
 * number and is compared as one.
 *
 * The legacy ids (`cross_source.*`, `xsrc.*`) have no family-number shape. They sort after the
 * governed rules and alphabetically among themselves — deliberate rather than incidental: they are a
 * different generation of check, and interleaving them with AS/CR/ID would suggest they belong to
 * the same sequence.
 */
export function compareRuleIds(left: string, right: string): number {
  const parse = (id: string) => {
    const match = /^([A-Za-z]+)-(\d+)$/.exec(id);
    return match ? { family: match[1] as string, number: Number(match[2]) } : null;
  };
  const a = parse(left);
  const b = parse(right);
  if (a && b) {
    return a.family === b.family ? a.number - b.number : a.family.localeCompare(b.family);
  }
  if (a) return -1; // a governed rule before a legacy id
  if (b) return 1;
  return left.localeCompare(right);
}

export function groupByRule(findings: RuleFinding[]): RuleFinding[][] {
  const groups = new Map<string, RuleFinding[]>();
  const order: string[] = [];
  for (const finding of findings) {
    const key = finding.rule_id;
    const existing = groups.get(key);
    if (existing) {
      existing.push(finding);
    } else {
      groups.set(key, [finding]);
      order.push(key);
    }
  }
  // LP-613 — ORDERED BY RULE ID, not by whatever order the API returned. Every section on both tabs
  // renders through this one function, so sorting here is what makes "Must fix", "Couldn't check",
  // "In the file" and "Needs review" all read the same way.
  order.sort(compareRuleIds);
  return order.map((key) => groups.get(key) as RuleFinding[]);
}

/** Split a Tab-1 (attention) bucket into its three outcome groups, in priority order (open first). */
export function attentionGroups(
  findings: RuleFinding[],
): { outcome: EvaluationOutcome; findings: RuleFinding[] }[] {
  // Known outcomes first (open → couldnt_check → needs_review), then any UNEXPECTED outcome that landed
  // in this bucket via the tabForOutcome fallback — appended as its own group so it is shown, not dropped.
  const known = new Set<EvaluationOutcome>(ATTENTION_ORDER);
  const extras = [
    ...new Set(findings.map((f) => f.evaluation_outcome).filter((o) => !known.has(o))),
  ];
  return [...ATTENTION_ORDER, ...extras]
    .map((outcome) => ({
      outcome,
      findings: findings.filter((f) => f.evaluation_outcome === outcome),
    }))
    .filter((group) => group.findings.length > 0);
}

// The subject LABEL (LP-377-B) is resolved by the READ PATH per subject TYPE (a filename / amount /
// borrower / "Loan-level") and arrives on `finding.subject_label`. The former frontend `ruleSubjectChip`
// (which guessed a chip from the load-bearing tags and could only ever show an amount, never a document's
// name) is retired — one mechanism, in the one place with DB access, so a row names its subject honestly.

/**
 * LP-541 — split a bucket into findings whose DOCUMENT IS MISSING and findings whose document is here
 * but does not answer the question.
 *
 * These are different jobs. "Request the credit report" is an outbound ask that leaves the processor's
 * desk; "the binder does not state a dwelling loss-settlement basis" is something to go and read. Mixed
 * together they triage identically, which is how a bucket of fifteen becomes fifteen things to read
 * rather than two things to do.
 *
 * `missing_documents` is empty both for "nothing is missing" and for a retired rule that cannot be
 * classified. Both land in `present` — which asks a processor to look, rather than telling them nothing
 * is missing when we do not know.
 */
export function splitByMissingDocument(findings: RuleFinding[]): {
  missing: RuleFinding[];
  present: RuleFinding[];
} {
  return {
    missing: findings.filter((f) => f.missing_documents.length > 0),
    present: findings.filter((f) => f.missing_documents.length === 0),
  };
}

/** The distinct documents a set of findings is waiting on, in first-seen order — the sub-header's list. */
export function awaitedDocuments(findings: RuleFinding[]): string[] {
  const seen = new Set<string>();
  for (const finding of findings) {
    for (const name of finding.missing_documents) seen.add(name);
  }
  return [...seen];
}

/**
 * LP-550 — the processor-facing name for a rule's category.
 *
 * The engine's categories come from the vocabulary spreadsheet and are engineering/domain taxonomy,
 * not display copy. One of them is "Fraud" — the family FR-1..FR-6 sits in — and it must not reach a
 * processor's screen. A recurring debit that is not on the 1003 is almost always a paperwork omission;
 * labelling it FRAUD accuses the borrower of a crime on the strength of a check that, by its own
 * activation bar, "surfaces rather than asserts" and cannot even see the disclosed debts.
 *
 * The internal category is unchanged — it is the domain expert's artifact, and grouping, filtering and
 * the specs all still key on it. Only the word shown changes.
 */
const RULE_CATEGORY_LABELS: Record<string, string> = {
  fraud: "Anomaly",
};

export function ruleCategoryLabel(category: string): string {
  return RULE_CATEGORY_LABELS[category.toLowerCase()] ?? humanize(category);
}

/** LP-588 — how a RESOLUTION STATUS reads to a processor.
 *
 * The wire value is `overridden`; the button that produces it says "Not an issue" (LP-584). Every
 * display site was humanizing the wire value instead, so clicking "Not an issue" produced a toast
 * reading "Finding overridden" and a row labelled "Overridden" — one action with two names in the
 * same list, which is the exact confusion the rename existed to remove. The rename stopped at the
 * buttons; this is the other half.
 *
 * Keyed here rather than at each site so the next rename cannot stop halfway again.
 */
const RESOLUTION_LABELS: Record<string, string> = {
  overridden: "Not an issue",
  accepted_risk: "Risk accepted",
  applied: "Applied",
  ratified: "Signed off",
  open: "Open",
};

export function resolutionLabel(status: string): string {
  return RESOLUTION_LABELS[status] ?? status.replace(/_/g, " ");
}

/** LP-590 — the run's phases in a processor's words.
 *
 * A run takes about six and a half minutes and showed a bare spinner for all of it, which is
 * indistinguishable from a hung worker. Deliberately a PHASE and a position, never a percentage:
 * stage A scales with the file's transaction count, so the phases are not evenly sized and a
 * progress bar would visibly stall — a bar that lies is worse than no bar.
 */
const PHASE_LABELS: Record<string, string> = {
  build: "Reading the file",
  stage_a: "Reading transactions",
  stage_b: "Connecting facts across documents",
  rules: "Applying rules",
  cross_source: "Cross-source review",
};

export function phaseLabel(phase: string): string {
  return PHASE_LABELS[phase] ?? "Working";
}

/** LP-591 — remaining time, in a processor's words, or null when there is nothing honest to say.
 *
 * Two behaviours matter more than the number itself.
 *
 * It ROUNDS TO THE MINUTE. The estimate is a median with about half a minute of spread, so a
 * to-the-second countdown would claim a precision it does not have and would visibly stall.
 *
 * And it says "taking longer than usual" once elapsed passes the estimate, rather than clamping at
 * "any second now" forever. That overrun is real information: a six-minute run with no signal is
 * indistinguishable from a hung worker, and this is the line that tells them apart.
 */
export function remainingLabel(
  estimatedTotalSeconds: number | null | undefined,
  elapsedSeconds: number | null | undefined,
): string | null {
  if (estimatedTotalSeconds == null || elapsedSeconds == null) return null;
  const remaining = estimatedTotalSeconds - elapsedSeconds;
  if (remaining <= 0) return "taking longer than usual";
  if (remaining < 60) return "less than a minute left";
  return `about ${Math.round(remaining / 60)} min left`;
}
