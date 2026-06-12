"use client";

import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import {
  downloadDocument,
  useDeleteDocument,
  useDevTextLayer,
  useDocumentDetail,
} from "@/lib/api/documents";
import { humanize } from "@/lib/format";
import { extractionFields, formatConfidence, formatFileSize } from "@/lib/loan-files/documents";
import type { DocumentResponse } from "@/lib/types/document";
import { format } from "date-fns";
import { Download, FlaskConical, Loader2, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { DocumentStatusBadge } from "./document-status";

/** Non-production only — matches the LP-40 dev endpoint's gating. */
const IS_DEV = process.env.NODE_ENV !== "production";

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-3 py-1.5 text-sm">
      <span className="shrink-0 text-gray-500">{label}</span>
      <span className="max-w-[62%] truncate text-right font-medium text-gray-900">{value}</span>
    </div>
  );
}

function fmtDate(iso: string): string {
  try {
    return format(new Date(iso), "MMM d, yyyy · h:mm a");
  } catch {
    return "—";
  }
}

export function DocumentDrawer({
  document: summary,
  fileId,
  onClose,
}: {
  document: DocumentResponse | null;
  fileId: string;
  onClose: () => void;
}) {
  const open = summary !== null;
  return (
    <Sheet open={open} onOpenChange={(next) => !next && onClose()}>
      <SheetContent>
        {summary && <DrawerBody summary={summary} fileId={fileId} onClose={onClose} />}
      </SheetContent>
    </Sheet>
  );
}

function DrawerBody({
  summary,
  fileId,
  onClose,
}: {
  summary: DocumentResponse;
  fileId: string;
  onClose: () => void;
}) {
  const { data: detail, isPending, isError } = useDocumentDetail(summary.id);
  const del = useDeleteDocument(fileId);
  const devTextLayer = useDevTextLayer(summary.id);
  const [downloading, setDownloading] = useState(false);

  const confidence = formatConfidence(summary.classification_confidence);
  const extraction = detail?.current_extraction ?? null;

  async function handleDownload() {
    setDownloading(true);
    try {
      await downloadDocument(summary.id, summary.original_filename);
    } catch {
      toast.error("Download failed", { description: "Please try again." });
    } finally {
      setDownloading(false);
    }
  }

  function handleDelete() {
    if (!window.confirm(`Remove “${summary.original_filename}”? This can’t be undone here.`)) {
      return;
    }
    del.mutate(summary.id, {
      onSuccess: () => {
        toast.success("Document removed");
        onClose();
      },
      onError: () => toast.error("Couldn’t remove the document"),
    });
  }

  return (
    <>
      <SheetHeader>
        <SheetTitle className="truncate pr-8">{summary.original_filename}</SheetTitle>
        <SheetDescription className="flex items-center gap-2">
          <DocumentStatusBadge status={summary.status} />
          <span className="text-gray-400">·</span>
          <span>{summary.document_type ? humanize(summary.document_type) : "Unclassified"}</span>
        </SheetDescription>
      </SheetHeader>

      <div className="flex-1 overflow-y-auto px-6 py-4">
        {/* Metadata */}
        <section className="divide-y divide-gray-100">
          <Row label="Type" value={summary.document_type ? humanize(summary.document_type) : "—"} />
          <Row label="Category" value={summary.category ? humanize(summary.category) : "—"} />
          <Row label="Confidence" value={confidence ?? "—"} />
          <Row label="Size" value={formatFileSize(summary.file_size_bytes)} />
          <Row label="Uploaded" value={fmtDate(summary.created_at)} />
        </section>

        {/* Extraction */}
        <section className="mt-6">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-400">
            Extracted data
          </h3>
          {isPending ? (
            <div className="mt-3 space-y-2">
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-3/4" />
              <Skeleton className="h-4 w-2/3" />
            </div>
          ) : isError ? (
            <p className="mt-3 text-sm text-gray-400">Couldn’t load the extraction.</p>
          ) : extraction ? (
            <dl className="mt-3 divide-y divide-gray-100 rounded-lg border border-gray-100">
              {extractionFields(extraction.extracted_data).map((field) => (
                <div
                  key={field.key}
                  className="flex items-start justify-between gap-3 px-3 py-2 text-sm"
                >
                  <dt className="shrink-0 text-gray-500">{field.label}</dt>
                  <dd className="max-w-[62%] truncate text-right font-medium text-gray-900">
                    {field.value}
                  </dd>
                </div>
              ))}
              {extraction.model_used && (
                <p className="px-3 py-2 text-[11px] text-gray-400">
                  Extracted by {extraction.model_used} · v{extraction.version}
                </p>
              )}
            </dl>
          ) : (
            <p className="mt-3 rounded-lg border border-dashed border-gray-200 px-3 py-4 text-sm text-gray-400">
              No extraction — this document is classified only.
            </p>
          )}
        </section>

        {/* Dev-only text-layer comparison (non-production) */}
        {IS_DEV && (
          <section className="mt-6">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => devTextLayer.mutate()}
              disabled={devTextLayer.isPending}
              className="gap-1.5 text-xs"
            >
              {devTextLayer.isPending ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <FlaskConical className="h-3.5 w-3.5" />
              )}
              Extract text layer (dev)
            </Button>
            {devTextLayer.data && (
              <div className="mt-3 rounded-lg border border-gray-200 bg-gray-50">
                <p className="border-b border-gray-100 px-3 py-1.5 text-[11px] text-gray-500">
                  {devTextLayer.data.extraction_ok
                    ? `${devTextLayer.data.page_count} page(s) · ${devTextLayer.data.has_text ? "has text layer" : "no text layer (likely a scan)"}`
                    : (devTextLayer.data.error_reason ?? "extraction failed")}
                </p>
                <pre className="max-h-48 overflow-auto px-3 py-2 text-[11px] leading-relaxed text-gray-700 whitespace-pre-wrap">
                  {devTextLayer.data.text || "(empty)"}
                </pre>
              </div>
            )}
            {devTextLayer.isError && (
              <p className="mt-2 text-xs text-gray-400">Dev endpoint unavailable.</p>
            )}
          </section>
        )}
      </div>

      {/* Actions */}
      <div className="flex items-center justify-between gap-2 border-t border-gray-100 px-6 py-3">
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={handleDelete}
          disabled={del.isPending}
          className="gap-1.5 text-gray-500 hover:text-destructive"
        >
          <Trash2 className="h-4 w-4" />
          Remove
        </Button>
        <Button
          type="button"
          size="sm"
          onClick={handleDownload}
          disabled={downloading}
          className="gap-1.5"
        >
          {downloading ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Download className="h-4 w-4" />
          )}
          Download
        </Button>
      </div>
    </>
  );
}
