"use client";

/**
 * The glue between LP-850's 409 and LP-851's dialog.
 *
 * A request is fired with no answer about the open draft. If the server refuses, the refusal is
 * held, the dialog renders it, and the SAME request is fired again carrying the processor's
 * `on_conflict` value. The caller writes its mutation once.
 *
 * WHY THE RETRY IS A CLOSURE RATHER THAN A STORED ACTION. Every door has a different payload — a
 * finding id, a list of finding ids, a list of document types — and a shape that could hold all
 * three would be a fourth definition of "a request" for the dialog to get wrong. The caller keeps
 * its own payload and hands back a function that re-sends it.
 */

import { OpenDraftDialog } from "@/components/file/communication/open-draft-dialog";
import type { ConflictChoice, DraftConflict } from "@/lib/api/draft-conflict";
import { draftConflictFrom } from "@/lib/api/draft-conflict";
import { type ReactNode, useState } from "react";

export interface DraftConflictHandling {
  /** The refusal being answered, or null. Exposed for a caller rendering its own dialog. */
  conflict: DraftConflict | null;
  /** Answer it. The held request is re-sent carrying the choice. */
  choose: (choice: ConflictChoice) => void;
  /** Dismiss it. Nothing is written — LP-850 planned the request before applying any of it. */
  cancel: () => void;
  /**
   * Hand an error here. Returns true if it was an open-draft refusal and the dialog has taken it;
   * false if it is an ordinary failure the caller must still report.
   *
   * NARROW ON PURPOSE — a helper that swallowed a real failure into a dialog nobody could answer
   * would be worse than no dialog at all.
   */
  capture: (error: unknown, retry: (choice: ConflictChoice) => void) => boolean;
  /** True while the answered request is in flight. */
  pending: boolean;
  /** Render this once, anywhere in the subtree. */
  dialog: ReactNode;
}

export function useDraftConflict(): DraftConflictHandling {
  const [conflict, setConflict] = useState<DraftConflict | null>(null);
  const [retry, setRetry] = useState<{ run: (choice: ConflictChoice) => void } | null>(null);
  const [pending, setPending] = useState(false);

  function capture(error: unknown, run: (choice: ConflictChoice) => void): boolean {
    const found = draftConflictFrom(error);
    if (found === null) return false;
    setConflict(found);
    // Wrapped in an object because `setState` calls a bare function argument as an updater.
    setRetry({ run });
    setPending(false);
    return true;
  }

  function close() {
    setConflict(null);
    setRetry(null);
    setPending(false);
  }

  function choose(choice: ConflictChoice) {
    const run = retry?.run;
    setConflict(null);
    setRetry(null);
    if (!run) return;
    setPending(true);
    run(choice);
  }

  return {
    capture,
    pending,
    conflict,
    choose,
    cancel: close,
    // THE CONVENIENCE, for the two doors with no dialog of their own. "Request all N" already has
    // one and folds the blocks into it instead — see `ConflictBlocks`.
    dialog: (
      <OpenDraftDialog
        conflict={conflict}
        pending={pending}
        // CANCEL WRITES NOTHING, and there is nothing here for it to undo: LP-850 plans the whole
        // request before applying any of it, so the 409 left the database exactly as it was.
        onCancel={close}
        onChoose={choose}
      />
    ),
  };
}
