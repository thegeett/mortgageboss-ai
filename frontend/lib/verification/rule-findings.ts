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
import type { EvaluationOutcome, RuleFinding } from "@/lib/types/verification";

export type GovernedTabId = "attention" | "satisfied" | "no_longer_applies" | "not_applicable";
export type TabId = GovernedTabId | "legacy";

/** The five §8 outcomes → their governed tab. `not_applicable` never appears (not persisted). */
const OUTCOME_TAB: Record<EvaluationOutcome, GovernedTabId> = {
  open: "attention",
  couldnt_check: "attention",
  needs_review: "attention",
  pending_automation: "attention", // LP-391 — a manual-review flag lives where the work is (Tab 1)
  satisfied: "satisfied",
  no_longer_applies: "no_longer_applies",
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

export type OutcomeTone = "danger" | "warning" | "info" | "success" | "muted";

export interface OutcomeMeta {
  /** The short label a processor triages on. */
  label: string;
  /** One line: what THIS outcome means (so `couldnt_check` reads as a gap, not a violation). */
  blurb: string;
  tone: OutcomeTone;
}

/** Shown for an outcome outside this union (a backend enum that grew) — surfaced, never crashed on. */
const FALLBACK_META: OutcomeMeta = {
  label: "Unknown outcome",
  blurb:
    "An outcome this view doesn't recognise yet — surfaced here so it is never silently dropped.",
  tone: "warning",
};

/** OUTCOME_META lookup that never returns undefined: an outcome outside the union → a safe fallback, so
 *  one unexpected value degrades a single row instead of crashing the whole tabs render. */
export function outcomeMeta(outcome: EvaluationOutcome): OutcomeMeta {
  return OUTCOME_META[outcome] ?? FALLBACK_META;
}

export const OUTCOME_META: Record<EvaluationOutcome, OutcomeMeta> = {
  open: {
    label: "Violation",
    blurb: "A rule fired — a real finding that needs action.",
    tone: "danger",
  },
  couldnt_check: {
    label: "Couldn't check",
    blurb:
      "The rule applies and the thing might exist, but a required input is missing — a gap, not a pass.",
    tone: "warning",
  },
  needs_review: {
    label: "Needs review",
    // LP-581 — plain English: "ratification" is the engine's word (ADR-336), not a processor's.
    blurb: "A judgment awaiting your sign-off — not a violation.",
    tone: "info",
  },
  pending_automation: {
    label: "Manual review",
    blurb:
      "This file has something in scope, but the automated check isn't active yet — a human must review it. The system has NOT judged it (not a pass/fail).",
    tone: "info",
  },
  satisfied: {
    label: "Satisfied",
    blurb: "The rule ran and passed — with evidence.",
    tone: "success",
  },
  no_longer_applies: {
    label: "No longer applies",
    blurb: "The subject left the file since a prior run.",
    tone: "muted",
  },
};

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
