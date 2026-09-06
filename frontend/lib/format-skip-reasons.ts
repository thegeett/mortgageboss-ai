/**
 * Server skip reasons → the words a processor reads (LP-637 review).
 *
 * WHY A MAP RATHER THAN `humanize`. Running the raw keys through `humanize` made the toast text a
 * function of server-side CONSTANT NAMES: renaming `_SKIP_HUMAN_TYPE`'s value would silently
 * rewrite user-facing copy, with nothing in either language connecting the two. It also gave the
 * one reason that is not a skip the same voice as the rest.
 *
 * `enqueue_failed` IS NOT A SKIP. Every other reason here is a decision — the server looked at the
 * document and chose to leave it alone. That one means the work was accepted, the document was put
 * back, and nothing will happen. Rendering it alongside "already processing" told a processor a
 * broker outage was a routine filter; a whole-file failure came back as "Nothing to re-read", which
 * reads as "your file is fine".
 */
export const ENQUEUE_FAILED = "enqueue_failed";

const SKIP_REASON_TEXT: Record<string, string> = {
  superseded_version: "an older version",
  already_processing: "already being processed",
  already_queued: "already queued",
  type_set_by_a_person: "typed by a person",
  already_classified: "already identified",
  too_large_to_read: "too large to read",
  [ENQUEUE_FAILED]: "could not be queued",
};

/**
 * "2 already being processed, 1 typed by a person".
 *
 * An unrecognised reason falls back to the raw key rather than being dropped: a server that grows a
 * new one should read oddly for one release, not silently under-report what happened.
 */
export function describeSkips(skipped: Record<string, number>): string {
  return Object.entries(skipped)
    .map(([reason, count]) => `${count} ${SKIP_REASON_TEXT[reason] ?? reason.replace(/_/g, " ")}`)
    .join(", ");
}

/** Split the outright failures from the deliberate skips — they need different voices. */
export function partitionSkips(skipped: Record<string, number>): {
  failed: number;
  decided: Record<string, number>;
} {
  const { [ENQUEUE_FAILED]: failed = 0, ...decided } = skipped;
  return { failed, decided };
}
