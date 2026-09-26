/**
 * Showing the lender's wording without showing the underwriter's note twice.
 *
 * ⚠️ THE NOTE IS KEPT IN `verbatim_text` ON PURPOSE AND MUST STILL NOT RENDER THERE. Spec rule 1 and
 * ADR-405 store the lender's string exactly as written — `test_round1_the_verbatim_text_keeps_its_notes`
 * pins that — and the reader ALSO carries the note out as structure so the review screen can show it
 * as a dated chip. Design rule 5 then says a note is "never merged into the lender's wording".
 *
 * Both are right, and together they mean the cut belongs to DISPLAY rather than to storage: the row
 * keeps the note, the screen shows it once. Before this, S1-04, S1-05 and S1-11 all rendered
 * "…history is required. **8/28 Not in Upload" in the serif block AND the chip beside it.
 */

/**
 * The note span the UWM reader recognises, mirrored from `_NOTE` in `readers/uwm.py`.
 *
 * ⚠️ THE SAME SPAN AS `note_stripped`, AND DELIBERATELY NOT THE SAME NORMALISATION. That function is
 * `" ".join(_NOTE.sub(" ", text).lower().split())` because it feeds a fingerprint, and its own
 * docstring warns that two normalisations which could disagree would mean "a row deduplicated within
 * a sheet and then duplicated across rounds — the failure both are meant to prevent".
 *
 * So this shares the PATTERN and drops the rest: lower-casing and collapsing would rewrite the
 * lender's own casing and spacing on screen, which is the thing ADR-405 exists to prevent. Display
 * needs the span removed; it does not need a hash-stable string.
 *
 * `**8/28 Not in Upload` — two asterisks, a date, the note, then either a closing `**` or the end of
 * the text. `***NOTE***` has three asterisks and no date, so it is NOT a note span and stays in the
 * wording, which is why `0132` correctly shows no chip.
 */
const NOTE_SPAN = /\*\*\s*\d{1,2}\/\d{1,2}\s+.*?(?:\*\*|$)/g;

/**
 * The lender's wording with any underwriter note spans removed, for display only.
 *
 * The casing of what remains is untouched — that is the part ADR-405 cares about. Whitespace RUNS are
 * collapsed to one space, and not only around the cut: a note removed mid-sentence otherwise leaves a
 * visible gap. That collapse is safe rather than merely tolerable, because every caller renders this
 * as HTML text, where a run of whitespace already draws as one space — so it changes the string
 * without changing the pixels. Do not reuse this where the string is measured, hashed or written back.
 */
export function wordingWithoutNotes(text: string): string {
  return text.replace(NOTE_SPAN, " ").replace(/\s+/g, " ").trim();
}

/**
 * The wording to SHOW for one row — spans removed, but only when the reader carried notes out of it.
 *
 * ⚠️ THE GATE IS THE POINT, NOT A SHORTCUT. Strip unconditionally and the day this mirror of `_NOTE`
 * matches a span the Python reader did not, the matched text leaves the screen with no chip standing
 * in for it: the lender's words dropped silently, which is the one thing spec rule 2 forbids. Gated on
 * the count, a divergence shows the span inside the wording — visible, and wrong in the direction a
 * processor can see and report.
 *
 * So `noteCount > 0` means the reader found spans here and each renders as a chip beside the row,
 * which makes the removal a de-duplication. `noteCount === 0` means there is nothing beside the row to
 * have moved the text into, so every character stays.
 */
export function displayWording(text: string, noteCount: number): string {
  return noteCount > 0 ? wordingWithoutNotes(text) : text;
}
