import { formatMoney } from "@/lib/format";
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
import type { EvaluationOutcome, RuleFinding, RuleFindingTag } from "@/lib/types/verification";

export type GovernedTabId = "attention" | "satisfied" | "no_longer_applies" | "not_applicable";
export type TabId = GovernedTabId | "legacy";

/** The five §8 outcomes → their governed tab. `not_applicable` never appears (not persisted). */
const OUTCOME_TAB: Record<EvaluationOutcome, GovernedTabId> = {
  open: "attention",
  couldnt_check: "attention",
  needs_review: "attention",
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
    blurb: "A judgment awaiting human ratification — not a violation.",
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

// --------------------------------------------------------------------------- //
// The subject label — a human-recognisable identity for a row. NEVER the raw content-id hash (LP-376:
// "a row nobody can identify is a row nobody can action"). Derived from the load-bearing tags where a
// recognisable value exists; the `message` prose carries the full identity as the row's subline.
// --------------------------------------------------------------------------- //
function tagValue(finding: RuleFinding, tagId: string): string | null {
  const tag = finding.load_bearing_tags.find((t: RuleFindingTag) => t.tag_id === tagId);
  if (tag == null || tag.value == null) return null;
  const value = String(tag.value).trim();
  return value.length > 0 && value !== "unknown" ? value : null;
}

/** A compact "M/D" from an ISO date (parsed by parts to avoid a timezone shift on a date-only string);
 *  the raw value verbatim if it isn't ISO — the chip is an identity hint, never a computed field. */
function shortDate(value: string): string {
  const iso = value.match(/^(\d{4})-(\d{2})-(\d{2})/);
  return iso != null ? `${Number(iso[2])}/${Number(iso[3])}` : value;
}

/**
 * A COMPACT subject chip a processor recognises, or null (then the row relies on its message). Per family:
 *  - AS-1 (per-deposit): the deposit's amount + date from txn.amount / txn.date → "$20,000 · 3/27".
 *  - ID-* per-borrower: a name tag if present.
 *  - loan-level (subject_key "loan"): "Loan".
 *  - per-document: the address / a stated value if present.
 * Never returns the raw content-id (a hash is not an identity).
 */
export function ruleSubjectChip(finding: RuleFinding): string | null {
  const amount = tagValue(finding, "txn.amount");
  const date = tagValue(finding, "txn.date");
  if (amount != null) {
    const money = formatMoney(amount);
    return date != null ? `${money} · ${shortDate(date)}` : money;
  }
  const name = tagValue(finding, "id.name_normalized");
  if (name != null) return name;
  const address = tagValue(finding, "id.address_normalized");
  if (address != null) return address;
  if (finding.subject_key === "loan") return "Loan-level";
  return null;
}
