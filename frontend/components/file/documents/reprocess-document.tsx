"use client";

import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { useReprocessDocument } from "@/lib/api/documents";
import { getErrorMessage } from "@/lib/errors/api-error";
import { isTerminalStatus } from "@/lib/loan-files/documents";
import type { DocumentResponse } from "@/lib/types/document";
import { isAxiosError } from "axios";
import { RefreshCw } from "lucide-react";
import { toast } from "sonner";

/**
 * Read this document again from scratch — classification included (LP-637).
 *
 * The sibling of "Correct type" and the answer to a different question. Correcting the type is for
 * when a processor KNOWS what a document is; this is for when nobody does, or when the classifier
 * has since improved. Classification runs once at upload, so every document processed before a
 * classifier fix keeps the answer it was given — LF-ZE9N had ten of them generating 220 findings.
 */
export function ReprocessDocumentButton({
  summary,
  fileId,
}: { summary: DocumentResponse; fileId: string }) {
  const reprocess = useReprocessDocument(fileId, summary.id);

  function run(force: boolean) {
    reprocess.mutate(force, {
      onSuccess: () =>
        toast.success("Reading this document again", {
          description: "Classifying and extracting in the background…",
        }),
      onError: (error) =>
        toast.error("Couldn’t reprocess this document", {
          description: getErrorMessage(error),
          // A REFUSAL A PROCESSOR CAN ACT ON (LP-637 feature 3 review). The server refuses a
          // document whose type looks human-set, and until now nothing in the UI could ask again
          // with `force` — the drawer's own "Correct type" control sets that very signal, so
          // correcting a type made this button permanently useless for that document, while the
          // error explained a way past it that did not exist.
          //
          // Offered on ANY 409 rather than on a client-side guess at which one: re-implementing
          // the server's rule here is the two-definitions trap this feature was careful to avoid.
          // When forcing cannot help — a superseded version, a live pipeline — the second attempt
          // returns the same clear reason, so the action never makes a claim that turns out false.
          ...(force || !isAxiosError(error) || error.response?.status !== 409
            ? {}
            : { action: { label: "Re-read anyway", onClick: () => run(true) } }),
        }),
    });
  }

  return (
    <div className="mt-3">
      <Button
        type="button"
        variant="outline"
        size="sm"
        // DISABLED WHILE PENDING *AND* WHILE THE PIPELINE IS RUNNING, and both halves are
        // load-bearing rather than polish. `isPending` covers only the request; it drops the
        // moment the POST returns, so the button came back to life while the document was queued.
        // A processor who sees no visible change presses again, the server accepts it (PENDING is
        // deliberately not an in-flight status), and the duplicate simply runs after the first —
        // the atomic claim excludes concurrent runs, not sequential ones. This reads the REFRESHED
        // status, which the drawer now receives.
        disabled={reprocess.isPending || !isTerminalStatus(summary.status)}
        onClick={() => run(false)}
        className="w-full gap-1.5"
      >
        {reprocess.isPending ? (
          <Spinner className="h-3.5 w-3.5" />
        ) : (
          <RefreshCw className="h-3.5 w-3.5" />
        )}
        Re-read this document
      </Button>
      <p className="mt-1.5 text-[11px] text-gray-400">
        {isTerminalStatus(summary.status)
          ? "Runs classification again, so the type may change. Use this when the type is wrong or unknown — not when you already know what it is."
          : "This document is being read now. You can re-read it again once it finishes."}
      </p>
    </div>
  );
}
