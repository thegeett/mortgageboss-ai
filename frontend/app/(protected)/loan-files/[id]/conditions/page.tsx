"use client";

import { ConditionsDashboard } from "@/components/file/conditions/conditions-dashboard";
import { useDiscardRound, useReparseRound } from "@/lib/api/conditions";
import { getErrorMessage } from "@/lib/errors/api-error";
import { notifyError, notifyStarted, notifySuccess } from "@/lib/toast";
import { useParams } from "next/navigation";

/**
 * Conditions tab (LP-909 §3) — replacing the LP-33 placeholder.
 *
 * ⚠️ THIS PAGE IS WHAT MAKES THE DASHBOARD REACHABLE AT ALL. Until now `ConditionsDashboard` had no
 * caller: the route rendered `TabPlaceholder`, so every screen beneath it was built, tested, and
 * shown to nobody. `lib/unwired-components.test.ts` exists for exactly that failure and could not
 * see this one, because it regex-matches component names against raw file text and the name appeared
 * in prose comments — the blind spot is recorded in LP-909 rather than papered over.
 *
 * ⚠️ NO `Suspense` BOUNDARY, UNLIKE THE DOCUMENTS TAB. That one needs it because it reads
 * `useSearchParams`; nothing here does. Adding one anyway would be cargo-cult — a boundary whose
 * fallback can never render.
 *
 * ⚠️ TWO OF THE FOUR WAYS IN DO NOT EXIST YET, AND THIS PAGE SAYS SO OUT LOUD. S1-06's paste sheet
 * and S1-12's add-by-hand form are section 4. `ConditionsEmpty` offers all four, so the honest
 * choices were to hide two buttons or to have them explain themselves — and hiding them would make
 * the empty state disagree with the design pack while telling a processor nothing.
 *
 * A SILENT no-op was never an option. The upload path WORKS on this screen, so a button that did
 * nothing would read as "this tab is broken" rather than "this part is unfinished", which is the
 * same misreading `TabPlaceholder` exists to prevent. The toast names the section so the message is
 * a status rather than an apology.
 */
export default function ConditionsPage() {
  const { id } = useParams<{ id: string }>();
  const reparse = useReparseRound(id);
  const discard = useDiscardRound(id);

  const notBuiltYet = (what: string) =>
    notifyError({
      title: `${what} is not built yet`,
      whatToDo:
        "It arrives with the review screen in section 4. Uploading the lender’s PDF works now.",
    });

  return (
    <ConditionsDashboard
      fileId={id}
      onPaste={() => notBuiltYet("Pasting conditions")}
      onAddByHand={() => notBuiltYet("Adding a condition by hand")}
      // The dropzone lives inside the empty state, which is what a processor sees once the current
      // round is discarded — so "upload another" is the discard, not a second uploader.
      onUploadAnother={() =>
        notifyError({
          title: "Discard this round first",
          whatToDo:
            "A file holds one round at a time on this screen. Discard the current one and the upload box comes back.",
        })
      }
      onDiscard={(roundId) =>
        discard.mutate(roundId, {
          onSuccess: () =>
            notifySuccess({
              title: "Round discarded",
              consequence: "It stays on the file’s history, marked discarded. Nothing was deleted.",
            }),
          onError: (error) =>
            notifyError({
              title: "That round could not be discarded",
              whatToDo: getErrorMessage(error),
            }),
        })
      }
      onRetry={(roundId) =>
        reparse.mutate(roundId, {
          onSuccess: () =>
            notifyStarted({
              title: "Reading the sheet again",
              consequence: "The stored PDF goes back to the reader. This page updates on its own.",
            }),
          // ⚠️ THE SERVER'S OWN SENTENCE, NEVER A GENERIC FAILURE. A reparse is refused for five
          // different reasons — still being read, already imported, discarded, already a draft, or
          // pasted with no PDF stored — and each leads a processor somewhere different. Collapsing
          // them into "could not retry" is what makes a refusal a dead end (spec §9.8).
          onError: (error) =>
            notifyError({
              title: "That sheet could not be read again",
              whatToDo: getErrorMessage(error),
            }),
        })
      }
    />
  );
}
