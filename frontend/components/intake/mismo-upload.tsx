"use client";

import { Spinner } from "@/components/ui/spinner";
import { useImportMismo } from "@/lib/api/mismo";
import { normalizeError } from "@/lib/errors/api-error";
import { notifyError, notifySuccess } from "@/lib/toast";
import { cn } from "@/lib/utils";
import { FileUp } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback } from "react";
import { type FileRejection, useDropzone } from "react-dropzone";

/** Friendly message for an import failure (LP-54 safe envelope via LP-46). */
function importErrorMessage(error: unknown): string {
  // The backend's safe messages are already friendly; only replace the generic
  // one. `isGeneric` rather than a string comparison — matching on the fallback's
  // wording stops working the moment the wording changes (LP-UI-034 changed it).
  const normalized = normalizeError(error);
  return normalized.isGeneric
    ? "This file couldn't be read as a MISMO file. Check the file and try again."
    : normalized.message;
}

/**
 * The PRIMARY create-file action (LP-55): drop the MISMO file the loan officer's
 * LOS produced and the populated file opens. Inline import (fast) → on success we
 * navigate straight to the created file (import-directly); parse warnings are
 * shown on that file (non-blocking). Accepts XML and HTML-wrapped; the *content*
 * is validated server-side, so we don't over-restrict here.
 */
export function MismoUpload() {
  const router = useRouter();
  const importMismo = useImportMismo();

  const onDrop = useCallback(
    (accepted: File[], rejected: FileRejection[]) => {
      if (rejected.length > 0) {
        notifyError({
          title: "That file type isn’t supported",
          whatToDo: "Upload the MISMO file (.xml or .html) from your loan origination system.",
        });
        return;
      }
      const file = accepted[0];
      if (!file) return;
      importMismo.mutate(file, {
        onSuccess: (result) => {
          const n = result.warnings.length;
          notifySuccess({
            title: "Loan file imported",
            consequence:
              n > 0
                ? `${n} field${n === 1 ? " needs" : "s need"} a look — ${n === 1 ? "it is" : "they are"} flagged on the file.`
                : "The application data is filled in and the file is ready to work.",
          });
          // Import-directly: open the populated file immediately.
          router.push(`/loan-files/${result.loan_file.display_id}`);
        },
        onError: (error) => {
          notifyError({ title: "The import didn’t finish", whatToDo: importErrorMessage(error) });
        },
      });
    },
    [importMismo, router],
  );

  const { getRootProps, getInputProps, isDragActive, open } = useDropzone({
    onDrop,
    accept: {
      "application/xml": [".xml"],
      "text/xml": [".xml"],
      "text/html": [".html", ".htm"],
    },
    maxSize: 10 * 1024 * 1024,
    multiple: false,
    noClick: true,
    disabled: importMismo.isPending,
  });

  const pending = importMismo.isPending;

  return (
    <div
      {...getRootProps()}
      aria-busy={pending}
      className={cn(
        "group relative flex flex-col items-center justify-center rounded-2xl border-2 border-dashed px-8 py-14 text-center transition-colors",
        isDragActive
          ? "border-primary bg-primary/10"
          : "border-primary/40 bg-primary/5 hover:border-primary hover:bg-primary/10",
        pending && "pointer-events-none opacity-80",
      )}
    >
      <input {...getInputProps()} aria-label="Upload a MISMO file" />
      <span
        className={cn(
          "flex h-16 w-16 items-center justify-center rounded-2xl transition-colors",
          isDragActive ? "bg-primary text-primary-foreground" : "bg-primary/15 text-primary",
        )}
      >
        {pending ? <Spinner className="h-7 w-7" /> : <FileUp className="h-7 w-7" aria-hidden />}
      </span>
      <h2 className="mt-5 text-lg font-semibold text-foreground">
        {pending ? "Importing…" : isDragActive ? "Drop to import" : "Upload a MISMO file"}
      </h2>
      <p className="mt-1.5 max-w-md text-sm text-muted-foreground">
        Drop the MISMO file from your loan origination system — the application data fills in
        automatically.
      </p>
      <button
        type="button"
        onClick={open}
        disabled={pending}
        className="mt-6 inline-flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:opacity-60"
      >
        {pending ? <Spinner /> : <FileUp className="h-4 w-4" />}
        {pending ? "Importing…" : "Choose MISMO file"}
      </button>
      <p className="mt-3 text-xs text-muted-foreground">XML or HTML · from your LOS</p>
    </div>
  );
}
