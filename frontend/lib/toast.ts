import { toast as sonner } from "sonner";

/**
 * How this app raises a toast (LP-UI-035).
 *
 * THE SECOND LINE IS REQUIRED, and that is the whole reason this wrapper exists.
 * Of 26 success toasts in the app, seventeen said only what had happened —
 * "Asset added", "Loan updated", "Document removed" — which a processor already
 * knows, because they just did it. The mockup's example is the standard:
 *
 *     Bonus income set to the 24-month average
 *     Back-end DTI moved from 44.7% to 43.8%.            [Undo]
 *
 * The title is the action; the second line is what CHANGED because of it. A
 * required prop is what stops the bare label coming back, the same way
 * `ErrorState`'s required title stopped the apology coming back in LP-UI-034.
 *
 * An error's second line is what to DO — the size limit, the missing field, the
 * next move. "The request failed" is not a second line.
 */

export interface UndoAction {
  /** Shown on the toast. "Undo" unless the reversal has a better name. */
  label?: string;
  onUndo: () => void;
}

export interface SuccessToast {
  /** What was done, in the words the button used. */
  title: string;
  /**
   * What changed because of it — a number that moved, a state that flipped, work
   * that is now running. Not a restatement of the title.
   */
  consequence: string;
  /** Offer this wherever the action can actually be reversed, and nowhere else. */
  undo?: UndoAction;
}

export interface ErrorToast {
  /** What failed, naming the thing: "ellis-appraisal.pdf couldn't be uploaded". */
  title: string;
  /** Why, and the next move. */
  whatToDo: string;
}

/** How long an undoable toast stays up. */
const UNDO_DURATION_MS = 10_000;

export function notifySuccess({ title, consequence, undo }: SuccessToast): void {
  sonner.success(title, {
    description: consequence,
    // An undo the processor cannot reach is not an undo. The default dismiss is
    // four seconds, which is less time than it takes to read the consequence and
    // decide it was wrong.
    ...(undo
      ? {
          duration: UNDO_DURATION_MS,
          action: { label: undo.label ?? "Undo", onClick: undo.onUndo },
        }
      : {}),
  });
}

export function notifyError({ title, whatToDo }: ErrorToast): void {
  sonner.error(title, { description: whatToDo });
}

/**
 * It worked, and something did not.
 *
 * Its own function because a partial success reported as a success is a small
 * lie: the file was created AND the property the processor typed was dropped.
 * The warning tone is the honest one — nothing failed outright, and something
 * still needs them.
 */
export function notifyPartial({ title, consequence }: Omit<SuccessToast, "undo">): void {
  sonner.warning(title, { description: consequence });
}

/**
 * Work has started and will finish later.
 *
 * Its own function because it is neither: nothing has changed yet, so a success
 * tone would be a claim, and nothing has failed. The second line says what to
 * expect and when.
 */
export function notifyStarted({ title, consequence }: Omit<SuccessToast, "undo">): void {
  sonner(title, { description: consequence });
}

/**
 * How Sonner is styled (LP-UI-035). Lives here rather than inline in `providers`
 * so it can be asserted on — the failure it encodes is invisible in a class list
 * and only shows in a computed style.
 *
 * TWO RAIL COLOURS ON ONE TOAST is the trap. Sonner applies its `default` slot in
 * ADDITION to the typed one, so an error toast carried both `border-l-primary`
 * and `border-l-destructive`, and which one won was decided by Tailwind's output
 * order rather than by anything written here. It emitted primary last, so every
 * error drew a petrol rail. The neutral rail is therefore scoped to
 * `data-type="default"`, which cannot collide with a typed one.
 *
 * No `richColors`: that is Sonner's own palette, a second colour vocabulary
 * beside the one LP-UI-005 unified. State lives on the rail and the glyph.
 */
export const TOASTER_CLASSNAMES = {
  toast:
    "!bg-card !text-foreground !border !border-border !border-l-2 !rounded-md !shadow-lg data-[type=default]:!border-l-primary",
  title: "!text-sm !font-medium !text-foreground",
  description: "!text-xs !text-muted-foreground",
  actionButton: "!bg-primary !text-primary-foreground !text-xs",
  closeButton: "!bg-card !border-border !text-muted-foreground",
  success: "!border-l-success",
  error: "!border-l-destructive",
  warning: "!border-l-warning",
  info: "!border-l-info",
} as const;
