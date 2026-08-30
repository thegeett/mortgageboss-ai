/**
 * Needs-list presentation helpers (LP-70) — the visual language of the
 * self-maintaining checklist.
 *
 * Two orthogonal lifecycles drive the display: `status` (the arrival spine) is
 * made visual + ACTION-ORIENTED via `lib/status.ts` and grouped by
 * {@link groupNeeds} so "what needs action" sits apart from "in review" / "done" /
 * "set aside". `disposition` drives whether a need still awaits the processor's
 * confirmation (a PROPOSED need — the AI's suggestion). `origin` is shown as a
 * small source tag so an AI proposal is legible as such.
 */
import type {
  DocumentCategory,
  NeedSourceAttribution,
  NeedsItemOrigin,
  NeedsItemPriority,
  NeedsItemPublic,
  NeedsItemStatus,
} from "@/lib/types/needs-item";

/** The four action-oriented groups, in display order (chase first). */
export type NeedsGroupKey = "needs_action" | "in_review" | "complete" | "set_aside";

/**
 * Status → the action-oriented group it rolls up into.
 *
 * LP-UI-005 moved the LABEL and the COLOURS to `lib/status.ts` (NEEDS_STATUS),
 * so this map carries only what is genuinely a needs-list concern: which bucket
 * a state belongs in. The LP-108 note that used to sit on `received` is on the
 * status there.
 */
export const NEEDS_GROUP: Record<NeedsItemStatus, NeedsGroupKey> = {
  pending: "needs_action",
  requested: "needs_action",
  rejected: "needs_action",
  received: "in_review",
  verified: "complete",
  waived: "set_aside",
};

export interface GroupMeta {
  label: string;
  /** A one-line description of what's in the group (used as a quiet caption). */
  hint: string;
}

export const GROUP_ORDER: NeedsGroupKey[] = ["needs_action", "in_review", "complete", "set_aside"];

export const GROUP_META: Record<NeedsGroupKey, GroupMeta> = {
  needs_action: { label: "Needs action", hint: "Outstanding — collect or chase these" },
  in_review: { label: "In review", hint: "Arrived, verifying" },
  complete: { label: "Complete", hint: "Satisfied" },
  set_aside: { label: "Set aside", hint: "Waived" },
};

const SOURCE_LABELS: Record<NeedsItemOrigin, string> = {
  ai_reasoning: "AI",
  suggestion: "Suggested",
  floor: "Baseline",
  manual: "Added",
  finding: "Finding",
  condition: "Condition",
  template: "Template",
};

/** The short provenance tag for a need (e.g. an `AI` proposal vs a `Baseline` need). */
export function sourceLabel(origin: NeedsItemOrigin): string {
  return SOURCE_LABELS[origin];
}

/** HONEST ATTRIBUTION (LP-110) — how a need's SOURCE is presented per origin, making clear how
 * much to trust it: a deterministic rule (certain) reads differently from the AI's reading
 * (verify), same discipline as the finding provenance pills. */
export interface SourceAttributionMeta {
  /** The lead-in before each fact ("Required because", "AI identified", "Triggered by"). */
  lead: string;
  /** Short pill text conveying the trust level. */
  pill: string;
  /** Pill Tailwind classes (primary = deterministic/certain; info = AI/finding). */
  pillClass: string;
  /** True when the source is the AI's (fallible) reading — drives the "verify" note. */
  aiIdentified: boolean;
}

export const SOURCE_ATTRIBUTION_META: Record<NeedSourceAttribution, SourceAttributionMeta> = {
  deterministic: {
    lead: "Required because",
    pill: "deterministic rule",
    pillClass: "bg-primary/10 text-primary",
    aiIdentified: false,
  },
  ai_identified: {
    lead: "AI identified",
    pill: "AI-identified",
    pillClass: "bg-info/10 text-info",
    aiIdentified: true,
  },
  finding: {
    lead: "Triggered by",
    pill: "finding",
    pillClass: "bg-info/10 text-info",
    aiIdentified: false,
  },
  manual: {
    lead: "Added by you",
    pill: "manual",
    pillClass: "bg-muted text-muted-foreground",
    aiIdentified: false,
  },
};

/** A PROPOSED need still awaits the processor's confirm/dismiss (the AI's suggestion). */
export function isProposed(need: NeedsItemPublic): boolean {
  return need.disposition === "proposed";
}

const CATEGORY_LABELS: Record<DocumentCategory, string> = {
  assets: "Assets",
  borrower_info: "Borrower info",
  credit: "Credit",
  disclosures: "Disclosures",
  income_employment: "Income & employment",
  property: "Property",
  misc: "Misc",
  custom: "Custom",
};

export function categoryLabel(category: DocumentCategory | null): string {
  return category ? CATEGORY_LABELS[category] : "Uncategorized";
}

export interface NeedsGroup {
  key: NeedsGroupKey;
  meta: GroupMeta;
  items: NeedsItemPublic[];
}

/** Split needs into the action-oriented groups, preserving the server order, and
 * drop empty groups. The result is what the dashboard renders, top to bottom. */
export function groupNeeds(needs: NeedsItemPublic[]): NeedsGroup[] {
  const buckets: Record<NeedsGroupKey, NeedsItemPublic[]> = {
    needs_action: [],
    in_review: [],
    complete: [],
    set_aside: [],
  };
  for (const need of needs) {
    buckets[NEEDS_GROUP[need.status]].push(need);
  }
  return GROUP_ORDER.map((key) => ({ key, meta: GROUP_META[key], items: buckets[key] })).filter(
    (group) => group.items.length > 0,
  );
}

/** Items still needing action — the chase pile (the headline count). */
export function outstandingNeedsCount(needs: NeedsItemPublic[]): number {
  return needs.filter((need) => NEEDS_GROUP[need.status] === "needs_action").length;
}

/** How many AI/suggested needs still await the processor's confirmation. */
export function proposedNeedsCount(needs: NeedsItemPublic[]): number {
  return needs.filter(isProposed).length;
}
