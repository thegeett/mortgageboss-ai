/**
 * Sorting the pipeline by attention (LP-UI-013).
 *
 * The dashboard's default order is "what needs me first", not "most recently
 * touched" — a processor opens it to triage, and a file that blocks submission
 * should not be below one that was merely edited five minutes ago.
 *
 * Sorting happens on the CLIENT, over the page the server returned. That is a
 * real limitation and worth naming: with more files than fit on a page, the
 * blocking file on page 2 stays on page 2. Ordering by attention server-side
 * needs the derivation to be sortable in SQL, which it is not today — it is
 * assembled in Python from four sources. Recorded on the ticket.
 */
import type { AttentionTone, LoanFileSummary } from "@/lib/types/loan-file";

/** Most urgent first. A file with no attention payload sorts last, not first. */
const RANK: Record<AttentionTone, number> = {
  blocking: 0,
  attention: 1,
  neutral: 2,
  verified: 3,
};

const UNKNOWN_RANK = 4;

function rankOf(file: LoanFileSummary): number {
  const tone = file.attention?.tone;
  return tone ? RANK[tone] : UNKNOWN_RANK;
}

/**
 * Order by attention, then by most recently touched within a tone.
 *
 * Returns a new array — the query cache's array is not ours to reorder, and
 * mutating it would reorder the cached page for every other reader of it.
 */
export function byAttention(files: readonly LoanFileSummary[]): LoanFileSummary[] {
  return [...files].sort((a, b) => {
    const byTone = rankOf(a) - rankOf(b);
    if (byTone !== 0) return byTone;
    return b.updated_at.localeCompare(a.updated_at);
  });
}
