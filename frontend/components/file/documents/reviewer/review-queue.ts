/**
 * The order the keyboard loop walks fields in (LP-UI-033).
 *
 * `Tab` / `↓` go to the next field NEEDING ATTENTION, not the next field. On a
 * pay stub that is the difference between three stops and thirteen, and the
 * ticket's metric is flagged fields per minute.
 *
 * WHAT COUNTS AS NEEDING ATTENTION: anything not already decided, whose tier is
 * not `confident`. A field the processor has accepted, corrected or rejected is
 * done — walking back onto it is how a loop stops feeling like progress.
 */

import { type FieldTier, tierFor, tierInputFor } from "@/lib/confidence";
import type { ExtractionField } from "@/lib/loan-files/documents";
import type { FieldScrutiny } from "@/lib/types/document";

export interface QueueField {
  key: string;
  tier: FieldTier;
  /** The processor's verdict, if they have given one. */
  verdict: string | null;
}

export function buildQueue(
  fields: readonly ExtractionField[],
  scrutiny: Record<string, FieldScrutiny>,
): QueueField[] {
  return fields.map((field) => {
    const entry = scrutiny[field.key];
    return {
      key: field.key,
      // `tierInputFor` rather than a second copy of the mapping: the queue and the
      // mark beside the row have to agree, and they did not when each built its
      // own inputs.
      tier: tierFor(tierInputFor(field.confidence, entry)),
      verdict: entry?.verdict ?? null,
    };
  });
}

/** Whether the loop should stop on this field. */
export function needsAttention(field: QueueField): boolean {
  if (field.verdict) return false; // decided — accepted, corrected or rejected
  return field.tier !== "confident";
}

/**
 * The next field to stop on, wrapping once.
 *
 * WRAPS, and that is a decision rather than a convenience: a processor who starts
 * halfway down a document and tabs to the end would otherwise be told there is
 * nothing left while three flagged fields sit above them.
 *
 * When the only field wanting attention is the one you are on, this returns THAT
 * FIELD rather than null — the loop stays put. `null` would be read as "nothing
 * left", and a field still wanting a decision is the opposite of that. Completion
 * has its own answer in `isFullyReviewed`, and conflating the two is how a
 * document gets marked reviewed with a flagged field still on it.
 */
export function nextAttention(
  queue: readonly QueueField[],
  from: string | null,
  direction: 1 | -1 = 1,
): string | null {
  const stops = queue.filter(needsAttention);
  if (stops.length === 0) return null;

  const currentIndex = from === null ? -1 : queue.findIndex((f) => f.key === from);
  if (currentIndex === -1) {
    // Not started, or the current field is gone. Take the first stop in the
    // direction of travel rather than guessing a position.
    return (direction === 1 ? stops[0] : stops[stops.length - 1])?.key ?? null;
  }

  const total = queue.length;
  for (let step = 1; step <= total; step++) {
    const index = (currentIndex + direction * step + total * total) % total;
    const candidate = queue[index];
    if (candidate && needsAttention(candidate)) return candidate.key;
  }
  // Unreachable in practice: the loop above covers every index, so a non-empty
  // `stops` always matches something. Kept as the honest fallback.
  return null;
}

/** Whether anything on this document still wants a decision. */
export function isFullyReviewed(queue: readonly QueueField[]): boolean {
  return queue.length > 0 && queue.every((field) => !needsAttention(field));
}
