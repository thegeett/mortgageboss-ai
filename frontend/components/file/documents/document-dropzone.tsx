"use client";

import { useUploadDocuments } from "@/lib/api/documents";
import { normalizeError } from "@/lib/errors/api-error";
import { validateUploadFile } from "@/lib/loan-files/documents";
import { cn } from "@/lib/utils";
import { CloudUpload, Loader2 } from "lucide-react";
import { useCallback } from "react";
import { type FileRejection, useDropzone } from "react-dropzone";
import { toast } from "sonner";

/** Map a server upload failure to a friendly message (LP-36 server is authoritative). */
function serverErrorMessage(error: unknown): string {
  const normalized = normalizeError(error);
  // A couple of high-value specifics; otherwise trust the safe server message.
  if (normalized.status === 413) return "A file exceeds the 50 MB limit.";
  if (normalized.status === 415) return "A file type isn't supported (use PDF, JPG, or PNG).";
  if (normalized.kind === "network") return normalized.message;
  return normalized.message === "Something went wrong. Please try again."
    ? "Upload failed. Please try again."
    : normalized.message;
}

/**
 * Drag-and-drop (and click-to-browse) upload zone. Accepts PDF/JPG/PNG and
 * validates type + size client-side for fast feedback — the server (LP-36)
 * remains authoritative, and its errors are surfaced too. Supports multiple
 * files; on success the new PENDING documents appear in the list (the mutation
 * invalidates the query) and live polling shows their progress.
 */
export function DocumentDropzone({ fileId }: { fileId: string }) {
  const upload = useUploadDocuments(fileId);

  const onDrop = useCallback(
    (accepted: File[], rejected: FileRejection[]) => {
      // react-dropzone rejects by the accept map; add our size/type messages.
      for (const r of rejected) {
        toast.error(`${r.file.name} can't be uploaded`, {
          description: "Use a PDF, JPG, or PNG up to 50 MB.",
        });
      }
      const valid: File[] = [];
      for (const file of accepted) {
        const problem = validateUploadFile(file);
        if (problem) {
          toast.error(`${problem.file} can't be uploaded`, { description: problem.reason });
        } else {
          valid.push(file);
        }
      }
      if (valid.length === 0) return;

      upload.mutate(valid, {
        onSuccess: (created) => {
          const count = created.length;
          toast.success(`Uploaded ${count} document${count === 1 ? "" : "s"}`, {
            description: "Processing has started.",
          });
        },
        onError: (error) => {
          toast.error("Upload failed", { description: serverErrorMessage(error) });
        },
      });
    },
    [upload],
  );

  const { getRootProps, getInputProps, isDragActive, open } = useDropzone({
    onDrop,
    accept: {
      "application/pdf": [".pdf"],
      "image/jpeg": [".jpg", ".jpeg"],
      "image/png": [".png"],
    },
    maxSize: 50 * 1024 * 1024,
    noClick: true, // we wire an explicit button so the whole area isn't a click target
    disabled: upload.isPending,
  });

  return (
    <div
      {...getRootProps()}
      className={cn(
        "group relative flex flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-10 text-center transition-colors",
        isDragActive
          ? "border-primary bg-primary/5"
          : "border-gray-300 bg-gray-50/60 hover:border-gray-400",
        upload.isPending && "pointer-events-none opacity-70",
      )}
    >
      <input {...getInputProps()} aria-label="Upload documents" />
      <span
        className={cn(
          "flex h-11 w-11 items-center justify-center rounded-full transition-colors",
          isDragActive ? "bg-primary/15 text-primary" : "bg-white text-gray-400 shadow-sm",
        )}
      >
        {upload.isPending ? (
          <Loader2 className="h-5 w-5 animate-spin" aria-hidden />
        ) : (
          <CloudUpload className="h-5 w-5" aria-hidden />
        )}
      </span>
      <p className="mt-3 text-sm font-medium text-gray-900">
        {upload.isPending ? "Uploading…" : isDragActive ? "Drop to upload" : "Drag documents here"}
      </p>
      <p className="mt-1 text-xs text-gray-500">
        PDF, JPG, or PNG · up to 50 MB · multiple at once
      </p>
      <button
        type="button"
        onClick={open}
        disabled={upload.isPending}
        className="mt-4 inline-flex items-center rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:opacity-50"
      >
        Browse files
      </button>
    </div>
  );
}
