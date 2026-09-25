"use client";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";
import { useUploadConditionSheet } from "@/lib/api/conditions";
import { useTimeline } from "@/lib/api/timeline";
import { normalizeError } from "@/lib/errors/api-error";
import { notifyError, notifyStarted } from "@/lib/toast";
import { cn } from "@/lib/utils";
import { Check, ClipboardList, Copy, PencilLine, Upload } from "lucide-react";
import { useCallback, useState } from "react";
import { type FileRejection, useDropzone } from "react-dropzone";

/**
 * A COPY of the server's ceiling (`settings.condition_sheet_max_bytes`), and the duplication is
 * stated rather than papered over.
 *
 * ⚠️ AN EARLIER COMMENT HERE SAID "Kept in sync by the sentence", which asserts a mechanism that
 * cannot work: a sentence cannot know how an environment was configured. The server value is a
 * Pydantic Settings field, so it is env-overridable and not fixed at build time.
 *
 * ⚠️ THE DIRECTION MATTERS AND ONLY ONE OF THEM IS SAFE. While this number is LOWER than the
 * server's, an over-limit file is refused here and nothing is lost — visible, not silent. If an
 * environment LOWERS the server's ceiling below this, the direction inverts: the client accepts an
 * 18 MB file, the processor waits through the upload, and the server answers 413 at the end. That is
 * reachable by configuration with no code change, and invisible to every test on both sides.
 *
 * The real fix is for the server to state its ceiling so there is one source; that is API surface
 * this ticket did not take. Until then this is a known duplicate, not a synchronised one.
 */
const MAX_SHEET_BYTES = 20 * 1024 * 1024;

/**
 * Refuse a file before a round exists, in the screen’s own words.
 *
 * ⚠️ TWO OF THESE SENTENCES ARE THE DESIGN’S, VERBATIM, AND ONE IS OURS. S1-03 specifies what a
 * pre-round refusal says — "That file isn’t a PDF. Upload the lender’s PDF, or paste the
 * conditions." and "This PDF is larger than 20 MB." The empty-file sentence is NOT in the design;
 * it is here because the server refuses zero bytes with a 422 and a processor deserves to know
 * instantly rather than after a round trip. Saying which is which matters: a later reader checking
 * this against the PNG will not find the third one, and should not conclude the screen drifted.
 *
 * ⚠️ THE ONLY COPY, AND IT WAS BRIEFLY NOT. The conditions tab page grew its OWN `refuseSheet`
 * rather than importing this one, and the two disagreed three ways inside a single commit — the
 * page let an empty MIME type through, skipped `.toLowerCase()`, and used a different sentence
 * ("Condition sheets must be PDFs.") that no test pinned and no design specifies. Worse, the
 * comment above it claimed "the same sentences when it is missed". Raised in review; the page now
 * imports this.
 *
 * The server is still authoritative. This is fast feedback, never the rule.
 */
export function refuseSheet(file: File): string | null {
  if (file.type.toLowerCase() !== "application/pdf") {
    return "That file isn’t a PDF. Upload the lender’s PDF, or paste the conditions.";
  }
  // Before the ceiling: a zero-byte file is not "too large", and telling a processor it is would
  // send them looking for a smaller copy of a file that has no contents at all.
  if (file.size === 0) return "That file is empty. Check it opens, then upload it again.";
  if (file.size > MAX_SHEET_BYTES) return "This PDF is larger than 20 MB.";
  return null;
}

function WayIn({
  title,
  recommended = false,
  children,
}: {
  title: string;
  recommended?: boolean;
  children: React.ReactNode;
}) {
  return (
    // `Card` rather than a div: the container radius is then correct by construction rather than by
    // inspection, which is what `components/ui/radius.test.ts` exists to keep true.
    <Card className={cn("flex flex-col", recommended && "border-primary")}>
      <CardContent className="flex flex-1 flex-col gap-2 p-3">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold text-foreground">{title}</h3>
          {recommended ? (
            <Badge variant="secondary" className="font-normal text-muted-foreground">
              Recommended
            </Badge>
          ) : null}
        </div>
        {children}
      </CardContent>
    </Card>
  );
}

/** The file's inbox address, with a Copy button that says so when the clipboard refuses. */
function InboxAddress({ fileId }: { fileId: string }) {
  const timeline = useTimeline(fileId, "all");
  const [copied, setCopied] = useState(false);
  const address = timeline.data?.inbox_address;

  async function copy(value: string) {
    // ⚠️ A REJECTED CLIPBOARD MUST NOT MAKE THE BUTTON DO NOTHING (LP-855's lesson, one surface
    // over). `writeText` rejects outright when the permission is denied, and an unhandled rejection
    // leaves a button that appears broken. The address stays on screen either way, so the recovery
    // is to say so and let them select it.
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      notifyError({
        title: "Couldn’t copy the address",
        whatToDo: "Select it and copy it by hand — it is shown in full above.",
      });
    }
  }

  if (!address) {
    // Not an error state: the address is fetched, and a missing one means it has not arrived yet.
    return <p className="text-xs text-muted-foreground">Loading this file’s address…</p>;
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <code className="min-w-0 truncate rounded-md border border-border bg-muted px-2 py-1 font-mono text-xs text-foreground-2">
        {address}
      </code>
      <Button variant="outline" size="sm" onClick={() => void copy(address)}>
        {copied ? (
          <Check className="h-3.5 w-3.5" aria-hidden />
        ) : (
          <Copy className="h-3.5 w-3.5" aria-hidden />
        )}
        {copied ? "Copied" : "Copy"}
      </Button>
    </div>
  );
}

/**
 * The Conditions tab with no rounds on the file yet (screen S1-01).
 *
 * ⚠️ NOT `EmptyState`, AND THAT IS DELIBERATE. That primitive renders `children` inside a `<p>`
 * capped at `max-w-xs` and documents `action` as "the one action that fills it". This screen is four
 * ways in, laid out 2x2, one of them holding a drop zone — a grid of interactive cards inside a
 * paragraph is invalid markup and fights a width written for a sentence. Bending a one-action
 * component into a four-action screen is the misuse its own docstring warns about.
 *
 * ⚠️ THE UPLOAD IS THE ONLY SELF-CONTAINED ACTION HERE. Paste and add-by-hand open dialogs that are
 * built in §4, so they are callbacks the parent supplies rather than buttons that do nothing —
 * a dead primary button is how a screen looks finished and is not.
 */
export function ConditionsEmpty({
  fileId,
  onPaste,
  onAddByHand,
}: {
  fileId: string;
  onPaste: () => void;
  onAddByHand: () => void;
}) {
  const upload = useUploadConditionSheet(fileId);

  const onDrop = useCallback(
    (accepted: File[], rejected: FileRejection[]) => {
      const file = accepted[0] ?? rejected[0]?.file;
      if (!file) return;

      const problem = refuseSheet(file);
      if (problem) {
        notifyError({ title: "That file can’t be used", whatToDo: problem });
        return;
      }

      upload.mutate(
        // FULL for a PDF: a processor uploading the lender's letter is giving us the whole list
        // unless they say otherwise. ADR-404 lets only a full round's absences mean anything later.
        { file, completeness: "full" },
        {
          onSuccess: () =>
            notifyStarted({
              title: "Reading the condition sheet",
              consequence:
                "Usually under 30 seconds. Nothing is saved to the file until you import.",
            }),
          onError: (error) =>
            notifyError({
              title: "The upload didn’t finish",
              whatToDo: normalizeError(error).message,
            }),
        },
      );
    },
    [upload],
  );

  const { getRootProps, getInputProps, isDragActive, open } = useDropzone({
    onDrop,
    accept: { "application/pdf": [".pdf"] },
    maxSize: MAX_SHEET_BYTES,
    multiple: false,
    // An explicit button, so the whole card is not a click target — the same reason
    // `DocumentDropzone` does it.
    noClick: true,
    disabled: upload.isPending,
  });

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        <h2 className="text-base font-semibold text-foreground">No conditions yet</h2>
        <p className="max-w-prose text-sm text-muted-foreground">
          When the lender approves the file with conditions, bring the sheet in here. Nothing is
          sent to anyone, and nothing is imported until you review it.
        </p>
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        <WayIn title="Upload the approval letter" recommended>
          <p className="text-sm text-muted-foreground">
            The lender’s PDF (UWM “Loan Approval Conditions”, Champions “Conditional Approval
            Certificate”). We read every condition plus the lender team, loan figures and
            document-expiry dates.
          </p>
          <div
            {...getRootProps()}
            className={cn(
              "mt-auto flex flex-wrap items-center justify-center gap-x-2 gap-y-1 rounded-lg border border-dashed px-3 py-3 text-center transition-colors",
              isDragActive ? "border-primary bg-primary/5" : "border-input bg-muted/60",
              upload.isPending && "pointer-events-none opacity-70",
            )}
          >
            <input {...getInputProps()} aria-label="Upload the lender's condition sheet" />
            {upload.isPending ? (
              <Spinner className="h-3.5 w-3.5" />
            ) : (
              <Upload className="h-3.5 w-3.5 text-muted-foreground" aria-hidden />
            )}
            <span className="text-sm text-foreground">
              {upload.isPending
                ? "Uploading…"
                : isDragActive
                  ? "Drop to upload"
                  : "Drop the PDF here or"}
            </span>
            <Button size="sm" onClick={open} disabled={upload.isPending}>
              Choose PDF
            </Button>
            <span className="w-full text-xs text-muted-foreground">PDF only · up to 20 MB</span>
          </div>
        </WayIn>

        <WayIn title="Paste conditions">
          <p className="text-sm text-muted-foreground">
            Copied from the lender portal or an email. Good when you only have some of them — you
            can attach the PDF later to fill in the rest.
          </p>
          <div className="mt-auto">
            <Button variant="outline" size="sm" onClick={onPaste}>
              <ClipboardList className="h-3.5 w-3.5" aria-hidden />
              Paste conditions
            </Button>
          </div>
        </WayIn>

        <WayIn title="Forward the lender’s email">
          <p className="text-sm text-muted-foreground">
            Forward it to this file’s address. The PDF lands in Communication, where you choose{" "}
            <span className="font-medium text-foreground-2">Use as condition sheet</span>.
          </p>
          <div className="mt-auto">
            <InboxAddress fileId={fileId} />
          </div>
        </WayIn>

        <WayIn title="Add one by hand">
          <p className="text-sm text-muted-foreground">
            For a condition you got by phone or from a portal note. Type the lender’s words exactly.
          </p>
          <div className="mt-auto">
            <Button variant="outline" size="sm" onClick={onAddByHand}>
              <PencilLine className="h-3.5 w-3.5" aria-hidden />
              Add a condition
            </Button>
          </div>
        </WayIn>
      </div>
    </div>
  );
}
