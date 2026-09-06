/**
 * The order the keyboard loop walks fields in (LP-UI-033).
 *
 * `Tab` goes to the next field NEEDING ATTENTION, not the next field. On a pay
 * stub that is the difference between three stops and thirteen, and the ticket's
 * metric is flagged fields per minute.
 *
 * `↓` DOES NOT, since LP-701. It used to, and a processor read the skipping as
 * the arrows selecting at random — correctly, because a confident field draws no
 * mark (LP-UI-032), so nothing on screen explained a jump. The arrows step one
 * row now (`stepField`, below); Tab keeps the jump, on a key the shortcut sheet
 * says it for.
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
  return (
    fields
      // SCALARS ONLY. The loop's three verbs — accept, correct, reject — all name
      // one value, and a pay stub's `earnings_lines` has fourteen rows and no
      // single value to name (LP-702). Stopping on one would open a text editor
      // over a table and record a verdict on whichever cell the processor read.
      .filter((field) => field.kind === "scalar")
      .map((field) => {
        const entry = scrutiny[field.key];
        return {
          key: field.key,
          // `tierInputFor` rather than a second copy of the mapping: the queue and the
          // mark beside the row have to agree, and they did not when each built its
          // own inputs.
          tier: tierFor(tierInputFor(field.confidence, entry)),
          verdict: entry?.verdict ?? null,
        };
      })
  );
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
  /**
   * The order the rows are DRAWN in, which is longer than the queue: LP-702 keeps
   * list-valued fields off the queue, and LP-701 made the arrows walk every drawn
   * row. So the selection can now sit on a row the queue has never heard of, and
   * resolving the position against the queue alone answered "not started".
   *
   * Concretely, on `[a, b, c, earnings_lines, d]`: four presses of ↓ select
   * `earnings_lines`, and Tab went BACK to `a` while Shift+Tab went FORWARD to
   * `d` — both directions inverted. Neither branch was wrong on its own; the two
   * tickets composed into it, and before LP-701 the arrows could not reach the
   * state at all.
   *
   * Defaults to the queue's own keys, which is the pre-LP-701 behaviour exactly.
   */
  order: readonly string[] = queue.map((field) => field.key),
): string | null {
  const stops = new Set(queue.filter(needsAttention).map((field) => field.key));
  if (stops.size === 0) return null;

  const currentIndex = from === null ? -1 : order.indexOf(from);
  if (currentIndex === -1) {
    // Genuinely not started, or the selection names no row that is drawn. Take
    // the first stop in the direction of travel rather than guessing a position.
    const inOrder = order.filter((key) => stops.has(key));
    return (direction === 1 ? inOrder[0] : inOrder[inOrder.length - 1]) ?? null;
  }

  const total = order.length;
  for (let step = 1; step <= total; step++) {
    const index = (currentIndex + direction * step + total * total) % total;
    const candidate = order[index];
    if (candidate !== undefined && stops.has(candidate)) return candidate;
  }
  // Unreachable in practice: the loop above covers every index, so a non-empty
  // `stops` always matches something. Kept as the honest fallback.
  return null;
}

/**
 * The next row in list order, wrapping (LP-701).
 *
 * The plain motion, over EVERY field including the list-valued ones the
 * attention queue leaves out. `nextAttention` answers "where should I work
 * next"; this answers "what is below this row", and the two were the same
 * function until a processor noticed that ↓ skipped rows for reasons the screen
 * never showed.
 *
 * With nothing selected it takes the first row (or the last, going up) rather
 * than returning null: the first ↓ on a document has to land somewhere.
 */
export function stepField(
  keys: readonly string[],
  from: string | null,
  direction: 1 | -1 = 1,
): string | null {
  if (keys.length === 0) return null;
  const index = from === null ? -1 : keys.indexOf(from);
  if (index === -1) return (direction === 1 ? keys[0] : keys[keys.length - 1]) ?? null;
  return keys[(index + direction + keys.length) % keys.length] ?? null;
}

/** Whether anything on this document still wants a decision. */
export function isFullyReviewed(queue: readonly QueueField[]): boolean {
  return queue.length > 0 && queue.every((field) => !needsAttention(field));
}

/**
 * The selected field, when a verdict can actually be recorded against it.
 *
 * A NAMED RULE RATHER THAN AN INLINE CHECK, because the rule is the part that was
 * wrong and a rule inside a page component cannot be tested — the review page has
 * no test and would need the whole data layer to get one.
 *
 * LP-702 made list fields render as tables: out of the queue, no `ScrutinyMark`,
 * and `VerdictEditor` gated on `kind === "scalar"`. The keyboard was not told.
 * `Enter` wrote an "accepted" verdict against a fourteen-row table nobody could
 * review, and `E`/`R` set `editing` to a key whose editor never mounts — while
 * `shortcutsEnabled` had already switched the keyboard off, so nothing could clear
 * it and the whole loop died until a page reload.
 */
export function editableFieldKey(
  fields: readonly ExtractionField[],
  selected: string | null,
): string | null {
  if (!selected) return null;
  return fields.find((f) => f.key === selected)?.kind === "scalar" ? selected : null;
}
