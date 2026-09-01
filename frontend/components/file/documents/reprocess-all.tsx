"use client";

import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { useReprocessDocuments } from "@/lib/api/documents";
import { getErrorMessage } from "@/lib/errors/api-error";
import { describeSkips, partitionSkips } from "@/lib/format-skip-reasons";
import { RefreshCw } from "lucide-react";
import { toast } from "sonner";

/**
 * Re-read the documents on this file that nothing could identify (LP-637).
 *
 * WHY THIS EXISTS AS A FILE-LEVEL ACTION. Classification runs once, at upload, so every document
 * processed before a classifier improvement keeps the answer it was given. LF-ZE9N had ten of them
 * — 23% of the file — each failing all 22 rules that need a typed field, generating 220 of its 256
 * "couldn't check" findings. Ten clicks is the wrong shape for one cause, and every future
 * classifier fix leaves its own cohort behind in the same way.
 *
 * THE SERVER DECIDES WHICH DOCUMENTS QUALIFY, and this component deliberately does not guess.
 * Re-implementing `_would_benefit` here to show a count in advance would put two definitions of
 * "worth re-reading" in the codebase, and the one on screen would be the one that drifts. The
 * result reports what actually happened instead.
 */
export function ReprocessAll({
  fileId,
  documentCount,
  isLoading = false,
}: { fileId: string; documentCount: number; isLoading?: boolean }) {
  const reprocess = useReprocessDocuments(fileId);

  function run() {
    reprocess.mutate(undefined, {
      onSuccess: (result) => {
        // SKIPS ARE SURFACED, not swallowed. A bulk action that quietly does less than it was
        // asked leaves a processor watching for ten documents to change when seven were sent —
        // indistinguishable from a slow queue.
        //
        // A FAILURE IS NOT A SKIP, and separating them is the whole reason this is not one line
        // (LP-637 review). `enqueue_failed` means the broker refused and the server put the
        // document back; every other reason means the server looked and decided. Folded together,
        // a total outage came back as an INFO toast reading "Nothing to re-read" — which a
        // processor reads as "your file is fine" — with the failure buried in a list of routine
        // filters.
        const { failed, decided } = partitionSkips(result.skipped);
        const skipped = describeSkips(decided);

        if (failed > 0) {
          toast.error(`Couldn’t queue ${failed} ${failed === 1 ? "document" : "documents"}`, {
            description:
              result.queued > 0
                ? `${result.queued} started; the rest were left unchanged. Try again shortly.`
                : "Nothing was started and nothing was changed. Try again shortly.",
          });
          return;
        }
        if (result.queued === 0) {
          toast.info("Nothing to re-read", {
            description: skipped
              ? `Every document was skipped: ${skipped}.`
              : "No documents on this file need re-reading.",
          });
          return;
        }
        toast.success(
          `Re-reading ${result.queued} ${result.queued === 1 ? "document" : "documents"}`,
          {
            description: skipped
              ? `Classifying in the background. Skipped: ${skipped}.`
              : "Classifying and extracting in the background…",
          },
        );
      },
      onError: (error) =>
        toast.error("Couldn’t reprocess these documents", {
          description: getErrorMessage(error),
        }),
    });
  }

  // Rendered disabled while the list loads rather than hidden. `documentCount` is 0 until the
  // query resolves, so returning null meant the button appeared afterwards and shifted the page
  // under a processor who was already reaching for it.
  if (!isLoading && documentCount === 0) return null;

  return (
    <div className="flex items-center justify-end">
      <Button
        type="button"
        variant="outline"
        size="sm"
        // Disabled while pending for the same reason the per-document button is: the server's
        // in-flight check cannot stop a double-click, because a document's status only moves once a
        // worker picks the task up. At batch scale that would double-enqueue the whole file.
        disabled={reprocess.isPending || isLoading}
        onClick={run}
        className="gap-1.5"
      >
        {reprocess.isPending ? (
          <Spinner className="h-3.5 w-3.5" />
        ) : (
          <RefreshCw className="h-3.5 w-3.5" />
        )}
        Re-read unidentified documents
      </Button>
    </div>
  );
}
