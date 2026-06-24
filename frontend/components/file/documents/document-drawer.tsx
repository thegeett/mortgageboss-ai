"use client";

import { Button } from "@/components/ui/button";
import { InlineErrorState } from "@/components/ui/error-state";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { SkeletonText } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import {
  downloadDocument,
  useDeleteDocument,
  useDevTextLayer,
  useDocumentDetail,
  useDocumentVersions,
  useOverrideDocumentType,
  useReplaceDocument,
  useResolveStaleness,
} from "@/lib/api/documents";
import { getErrorMessage } from "@/lib/errors/api-error";
import { humanize } from "@/lib/format";
import {
  OVERRIDE_TYPE_OPTIONS,
  formatConfidence,
  formatFileSize,
  typeReExtracts,
  validateUploadFile,
  versionLabel,
} from "@/lib/loan-files/documents";
import type { DocumentResponse } from "@/lib/types/document";
import { cn } from "@/lib/utils";
import { format } from "date-fns";
import {
  Check,
  Download,
  FlaskConical,
  History,
  PencilLine,
  RefreshCw,
  SlashSquare,
  Trash2,
  TriangleAlert,
} from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { DocumentStatusBadge } from "./document-status";
import { ExtractionView } from "./extraction-view";

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

/**
 * Manual document-type override (LP-44) — the human-correction half of the loop.
 * When the AI is unsure (`needs_review`) or simply wrong, the processor sets the
 * authoritative type here; saving PATCHes the document and the server re-runs
 * extraction for the corrected type (relabel-only for types we don't extract).
 */
function TypeOverride({ summary, fileId }: { summary: DocumentResponse; fileId: string }) {
  const override = useOverrideDocumentType(fileId, summary.id);
  const [selected, setSelected] = useState(summary.document_type ?? "");
  const needsReview = summary.status === "needs_review";

  // Keep the current type selectable even when it isn't one of the standard options.
  const options = useMemo(() => {
    const current = summary.document_type;
    if (current && !OVERRIDE_TYPE_OPTIONS.some((o) => o.value === current)) {
      return [{ value: current, label: humanize(current) }, ...OVERRIDE_TYPE_OPTIONS];
    }
    return OVERRIDE_TYPE_OPTIONS;
  }, [summary.document_type]);

  const changed = selected !== "" && selected !== summary.document_type;

  function handleSave() {
    override.mutate(selected, {
      onSuccess: () =>
        toast.success(`Type set to ${humanize(selected)}`, {
          description: typeReExtracts(selected)
            ? "Re-extracting in the background…"
            : "Relabeled — this type isn’t extracted.",
        }),
      onError: (error) =>
        toast.error("Couldn’t update the type", { description: getErrorMessage(error) }),
    });
  }

  return (
    <section className="mt-6">
      <h3 className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-gray-400">
        <PencilLine className="h-3.5 w-3.5" />
        Correct type
      </h3>
      {needsReview && (
        <p className="mt-2 rounded-lg border border-warning/30 bg-warning/10 px-3 py-2 text-xs text-warning">
          The AI wasn’t confident about this classification — confirm or correct the type below.
        </p>
      )}
      <div className="mt-3 flex items-center gap-2">
        <select
          value={selected}
          onChange={(e) => setSelected(e.target.value)}
          disabled={override.isPending}
          className="h-9 flex-1 rounded-md border border-gray-200 bg-white px-2.5 text-sm text-gray-900 focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary disabled:opacity-60"
        >
          {options.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        <Button
          type="button"
          size="sm"
          onClick={handleSave}
          disabled={!changed || override.isPending}
          className="gap-1.5"
        >
          {override.isPending && <Spinner className="h-3.5 w-3.5" />}
          Apply
        </Button>
      </div>
      <p className="mt-1.5 text-[11px] text-gray-400">
        {typeReExtracts(selected)
          ? "Saving re-runs extraction for this type."
          : "This type is recorded only — no data is extracted."}
      </p>
    </section>
  );
}

/**
 * Explicit replace (Model C, LP-71) — the processor deliberately supersedes THIS
 * document with a new upload (old → historical, new → current, both kept). A hidden
 * file input + a button; reused in the staleness warning and the footer.
 */
function ReplaceButton({
  summary,
  fileId,
  label = "Replace",
  variant = "outline",
  className,
}: {
  summary: DocumentResponse;
  fileId: string;
  label?: string;
  variant?: "outline" | "ghost";
  className?: string;
}) {
  const replace = useReplaceDocument(fileId, summary.id);
  const inputRef = useRef<HTMLInputElement>(null);

  function onFile(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    const error = validateUploadFile(file);
    if (error) {
      toast.error("Can’t replace", { description: error.reason });
      return;
    }
    replace.mutate(file, {
      onSuccess: () =>
        toast.success("Replacing document", {
          description: "The new version is processing; the old one is kept as history.",
        }),
      onError: (err) => toast.error("Couldn’t replace", { description: getErrorMessage(err) }),
    });
  }

  return (
    <>
      <input
        ref={inputRef}
        type="file"
        accept=".pdf,.jpg,.jpeg,.png"
        className="hidden"
        onChange={onFile}
      />
      <Button
        type="button"
        variant={variant}
        size="sm"
        disabled={replace.isPending}
        onClick={() => inputRef.current?.click()}
        className={cn("gap-1.5", className)}
      >
        {replace.isPending ? (
          <Spinner className="h-3.5 w-3.5" />
        ) : (
          <RefreshCw className="h-3.5 w-3.5" />
        )}
        {label}
      </Button>
    </>
  );
}

/**
 * Staleness warning (LP-71) — calm, helpful, NOT blocking. A flagged-stale current
 * document shows its reason + the resolve options (Replace / Waive / Accept). A
 * resolved one shows a quiet note. The processor decides; auto-resolution is V2.
 */
function StalenessWarning({ summary, fileId }: { summary: DocumentResponse; fileId: string }) {
  const resolve = useResolveStaleness(fileId, summary.id);
  const staleness = summary.staleness;

  if (staleness.resolution) {
    return (
      <p className="mt-4 text-xs text-gray-500">
        Staleness {staleness.resolution === "waived" ? "waived" : "accepted"} — using this document
        as-is.
      </p>
    );
  }
  if (!staleness.is_stale) return null;

  function act(action: "waive" | "accept") {
    resolve.mutate(
      { action },
      {
        onSuccess: () =>
          toast.success(action === "waive" ? "Staleness waived" : "Document accepted"),
        onError: (err) => toast.error("Couldn’t resolve", { description: getErrorMessage(err) }),
      },
    );
  }

  return (
    <section className="mt-4 rounded-lg border border-warning/30 bg-warning/5 px-3.5 py-3">
      <div className="flex items-center gap-1.5 text-sm font-medium text-warning">
        <TriangleAlert className="h-4 w-4 shrink-0" aria-hidden />
        {staleness.kind === "expired" ? "This document has expired" : "This document may be stale"}
      </div>
      {staleness.reason && <p className="mt-1 text-xs text-gray-600">{staleness.reason}</p>}
      <div className="mt-2.5 flex flex-wrap items-center gap-2">
        <ReplaceButton summary={summary} fileId={fileId} label="Replace" />
        <Button
          type="button"
          variant="ghost"
          size="sm"
          disabled={resolve.isPending}
          onClick={() => act("waive")}
          className="gap-1.5 text-gray-600"
        >
          <SlashSquare className="h-3.5 w-3.5" /> Waive
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          disabled={resolve.isPending}
          onClick={() => act("accept")}
          className="gap-1.5 text-gray-600"
        >
          <Check className="h-3.5 w-3.5" /> Accept as-is
        </Button>
      </div>
    </section>
  );
}

/**
 * Version history (LP-71) — when a document has versions, shows "v2 of N" and the
 * chain (which is current, the prior versions), each downloadable (audit).
 */
function VersionHistory({ summary, fileId }: { summary: DocumentResponse; fileId: string }) {
  const enabled = summary.version_count > 1;
  const { data, isPending } = useDocumentVersions(summary.id, enabled);
  if (!enabled) return null;

  return (
    <section className="mt-6">
      <h3 className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-gray-400">
        <History className="h-3.5 w-3.5" />
        Version history
        <span className="font-normal normal-case text-gray-400">· {versionLabel(summary)}</span>
      </h3>
      {isPending ? (
        <SkeletonText lines={2} widths={["w-full", "w-2/3"]} className="mt-3" />
      ) : (
        <ul className="mt-3 space-y-1.5">
          {(data ?? []).map((version) => (
            <li
              key={version.id}
              className="flex items-center justify-between gap-2 rounded-md border border-gray-100 px-2.5 py-1.5 text-xs"
            >
              <span className="flex min-w-0 items-center gap-1.5">
                <span className="font-medium text-gray-700">v{version.version}</span>
                {version.is_current ? (
                  <span className="rounded-full border border-success/20 bg-success/10 px-1.5 text-[10px] font-medium text-success">
                    Current
                  </span>
                ) : (
                  <span className="rounded-full border border-gray-200 bg-gray-50 px-1.5 text-[10px] font-medium text-gray-400">
                    Historical
                  </span>
                )}
                <span className="truncate text-gray-500">{version.original_filename}</span>
              </span>
              <button
                type="button"
                onClick={() => void downloadDocument(version.id, version.original_filename)}
                className="shrink-0 text-gray-400 hover:text-gray-600"
                aria-label={`Download v${version.version}`}
              >
                <Download className="h-3.5 w-3.5" />
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
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
  const { data: detail, isPending, isError, refetch } = useDocumentDetail(summary.id);
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
      onError: (error) =>
        toast.error("Couldn’t remove the document", { description: getErrorMessage(error) }),
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

        {/* Staleness warning (LP-71) — calm, with resolve options. */}
        <StalenessWarning summary={summary} fileId={fileId} />

        {/* Tier 2 (recognized) docs carry a short summary gist (LP-65) — a
            human-reference "what is this?", not structured extraction. */}
        {summary.summary && (
          <section className="mt-6">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-400">Summary</h3>
            <p className="mt-2 text-sm text-gray-700">{summary.summary}</p>
          </section>
        )}

        {/* Manual type override (LP-44) */}
        <TypeOverride summary={summary} fileId={fileId} />

        {/* Extraction */}
        <section className="mt-6" aria-busy={isPending}>
          <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-400">
            Extracted data
          </h3>
          {isPending ? (
            <>
              <output className="sr-only">Loading extracted data</output>
              <SkeletonText
                lines={4}
                widths={["w-full", "w-5/6", "w-3/4", "w-2/3"]}
                className="mt-3"
              />
            </>
          ) : isError ? (
            <InlineErrorState
              className="mt-1"
              message="Couldn’t load the extraction."
              onRetry={() => void refetch()}
            />
          ) : extraction ? (
            <div className="mt-3">
              <ExtractionView data={extraction.extracted_data} />
              {extraction.model_used && (
                <p className="mt-2 text-[11px] text-gray-400">
                  Extracted by {extraction.model_used} · v{extraction.version}
                </p>
              )}
            </div>
          ) : (
            <p className="mt-3 rounded-lg border border-dashed border-gray-200 px-3 py-4 text-sm text-gray-400">
              No extraction — this document is classified only.
            </p>
          )}
        </section>

        {/* Version history (LP-71) — shown when the document has versions. */}
        <VersionHistory summary={summary} fileId={fileId} />

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
                <Spinner className="h-3.5 w-3.5" />
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
          {del.isPending ? <Spinner className="h-4 w-4" /> : <Trash2 className="h-4 w-4" />}
          {del.isPending ? "Removing…" : "Remove"}
        </Button>
        <div className="flex items-center gap-2">
          <ReplaceButton summary={summary} fileId={fileId} />
          <Button
            type="button"
            size="sm"
            onClick={handleDownload}
            disabled={downloading}
            className="gap-1.5"
          >
            {downloading ? <Spinner className="h-4 w-4" /> : <Download className="h-4 w-4" />}
            Download
          </Button>
        </div>
      </div>
    </>
  );
}
