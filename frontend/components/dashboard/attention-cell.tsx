import { StatusToken } from "@/components/status-token";
import type { StatusMeta, Tone } from "@/lib/status";
import type { AttentionTone, FileAttention } from "@/lib/types/loan-file";
import { cn } from "@/lib/utils";

/**
 * The Attention column (LP-UI-013) — what is actually wrong with this file.
 *
 * A status alone cannot answer it: "In processing" is equally true of a file
 * waiting on nothing and one whose pay stub failed to read six days ago. The
 * string is derived on the server (`app/services/attention.py`) because it reads
 * four domains, and deriving it here would mean those queries per row.
 *
 * The tone vocabulary is the app's, not a fifth one invented for this screen —
 * `AttentionTone` is a subset of `Tone`, so it renders through `StatusToken`
 * and therefore carries colour, glyph shape and word like every other status.
 */

/** The backend's four tones are a subset of the shared six. */
function toMeta(attention: FileAttention): StatusMeta {
  return { tone: attention.tone as Tone, label: attention.label };
}

export function AttentionCell({ attention }: { attention: FileAttention | null | undefined }) {
  if (!attention) {
    // A version-skewed backend that does not send the field. Say nothing rather
    // than claim the file is calm.
    return <span className="text-muted-foreground">—</span>;
  }
  return <StatusToken meta={toMeta(attention)} className="text-xs" />;
}

/**
 * Row-stripe classes for a tone — the channel that survives a colour-blind read.
 *
 * Written out in full, never assembled. Tailwind scans source text for complete
 * class names, so a computed one (`border-l-${tone}`) is not emitted at all and
 * the stripe silently renders as the default border. That is the same shape as
 * LP-UI-002's undefined `danger`: the class is present, resolves to nothing, and
 * nothing fails.
 */
export const ATTENTION_STRIPE: Record<AttentionTone, string> = {
  blocking: "border-l-2 border-l-destructive",
  attention: "border-l-2 border-l-warning",
  verified: "border-l-2 border-l-success",
  neutral: "border-l-2 border-l-border-strong",
};

/**
 * Needs progress. A bar and the fraction beside it: the bar for the glance, the
 * numbers because "most of the way" is not something you can act on.
 */
export function NeedsProgress({ attention }: { attention: FileAttention | null | undefined }) {
  if (!attention || attention.needs_total === 0) {
    return <span className="tabular text-xs text-muted-foreground">—</span>;
  }
  const { needs_satisfied: done, needs_total: total } = attention;
  const complete = done === total;
  return (
    <span className="flex items-center justify-end gap-2">
      <span aria-hidden className="h-1 w-12 shrink-0 overflow-hidden rounded-full bg-border">
        <span
          className={cn("block h-full rounded-full", complete ? "bg-success" : "bg-primary")}
          style={{ width: `${Math.round((done / total) * 100)}%` }}
        />
      </span>
      <span className="tabular whitespace-nowrap text-xs text-muted-foreground">
        {done} / {total}
      </span>
    </span>
  );
}
