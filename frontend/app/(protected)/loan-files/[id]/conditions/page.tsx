"use client";

import { AddConditionDialog } from "@/components/file/conditions/add-condition-dialog";
import { ConditionsDashboard } from "@/components/file/conditions/conditions-dashboard";
import { refuseSheet } from "@/components/file/conditions/conditions-empty";
import { PasteConditionsDialog } from "@/components/file/conditions/paste-conditions-dialog";
import {
  useConditionRounds,
  useDiscardRound,
  useReparseRound,
  useUploadConditionSheet,
} from "@/lib/api/conditions";
import { getErrorMessage } from "@/lib/errors/api-error";
import { notifyError, notifyStarted, notifySuccess } from "@/lib/toast";
import { useParams } from "next/navigation";
import { useRef, useState } from "react";

/**
 * Conditions tab (LP-909 §3, §4) — replacing the LP-33 placeholder.
 *
 * ⚠️ THIS PAGE IS WHAT MAKES THE DASHBOARD REACHABLE AT ALL. Until it existed `ConditionsDashboard`
 * had no caller: the route rendered `TabPlaceholder`, so every screen beneath it was built, tested,
 * and shown to nobody. `lib/unwired-components.test.ts` exists for exactly that failure and could
 * not see this one, because it regex-matches component names against raw file text and the name
 * appeared in prose comments — the blind spot is recorded in LP-909 rather than papered over.
 *
 * ⚠️ NO `Suspense` BOUNDARY, UNLIKE THE DOCUMENTS TAB. That one needs it because it reads
 * `useSearchParams`; nothing here does. Adding one anyway would be a boundary whose fallback can
 * never render.
 *
 * ⚠️ EVERY BUTTON ON THIS TAB NOW DOES WHAT ITS LABEL SAYS, AND TWO OF THEM DID NOT (LP-909 review).
 * The first version answered *Paste conditions* and *Add one by hand* with a "not built yet" toast,
 * which was at least honest, and answered *Upload a different PDF* with `notifyError` — an ERROR
 * for doing exactly what the button offered. That was the third control in this stage whose handler
 * refused its own label, after `RoundFailed`'s Try again and `RoundReading`'s stranded paragraph.
 * Its copy was also simply wrong: "a file holds one round at a time" — a file holds many, and it is
 * this SCREEN that shows one. The fix was three lines of behaviour rather than better wording.
 */
export default function ConditionsPage() {
  const { id } = useParams<{ id: string }>();
  const rounds = useConditionRounds(id);
  const reparse = useReparseRound(id);
  const discard = useDiscardRound(id);
  const upload = useUploadConditionSheet(id);

  const [pasteOpen, setPasteOpen] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  // ⚠️ A HIDDEN INPUT RATHER THAN A SECOND DROPZONE. `ConditionsEmpty` owns the drop target for a
  // file with no rounds; this is the "upload another" path from a round that is already on screen,
  // where there is nowhere to drop. One input, opened on demand, keeps the upload contract in one
  // hook instead of two components that can disagree about the ceiling.
  const fileInput = useRef<HTMLInputElement>(null);

  function uploadSheet(file: File) {
    const problem = refuseSheet(file);
    if (problem) {
      notifyError({ title: "That file can’t be used", whatToDo: problem });
      return;
    }
    upload.mutate(
      { file, completeness: "full" },
      {
        onSuccess: () =>
          notifyStarted({
            title: "Reading the condition sheet",
            consequence: "It becomes the newest round. Nothing is saved until you import.",
          }),
        onError: (error) =>
          notifyError({
            title: "That sheet could not be uploaded",
            whatToDo: getErrorMessage(error),
          }),
      },
    );
  }

  return (
    <>
      <input
        ref={fileInput}
        type="file"
        accept="application/pdf"
        className="hidden"
        onChange={(event) => {
          const file = event.target.files?.[0];
          // Cleared so choosing the SAME file twice fires `change` again — otherwise a second
          // attempt after a failure looks like a dead button.
          event.target.value = "";
          if (file) uploadSheet(file);
        }}
      />

      <ConditionsDashboard
        fileId={id}
        onPaste={() => setPasteOpen(true)}
        onAddByHand={() => setAddOpen(true)}
        onUploadAnother={() => fileInput.current?.click()}
        onDiscard={(roundId) =>
          discard.mutate(roundId, {
            onSuccess: () =>
              notifySuccess({
                title: "Round discarded",
                consequence:
                  "It stays on the file’s history, marked discarded. Nothing was deleted.",
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
                consequence:
                  "The stored PDF goes back to the reader. This page updates on its own.",
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

      <PasteConditionsDialog fileId={id} open={pasteOpen} onOpenChange={setPasteOpen} />
      <AddConditionDialog
        fileId={id}
        rounds={rounds.data}
        open={addOpen}
        onOpenChange={setAddOpen}
      />
    </>
  );
}
