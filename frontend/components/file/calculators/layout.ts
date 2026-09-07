/**
 * The expanded calculator's two-column layout, defined once (LP-UI-045 review).
 *
 * DTI, LTV and the generic calculator card are three files rendering the same
 * shape: the math on the left, the result beside it and staying put as the math
 * scrolls. The strings were written out in all three, only one of which had a
 * test — so two of the three could drift to a different column width or lose
 * their stickiness and nothing would compare them.
 *
 * Literal strings, not assembled: Tailwind scans source text, and a class built
 * from a variable is never emitted.
 */

/** Math on the left, a 19rem result column on the right, stacked below `lg`. */
export const CALCULATOR_GRID = "grid gap-4 lg:grid-cols-[minmax(0,1fr)_19rem]";

/** The result column: it stays in view while the math scrolls past it. */
export const CALCULATOR_RESULT_COLUMN = "space-y-3 lg:sticky lg:top-3 lg:self-start";
