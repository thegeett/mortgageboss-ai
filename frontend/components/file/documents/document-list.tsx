"use client";

import { ErrorState } from "@/components/ui/error-state";
import { SkeletonRows } from "@/components/ui/skeleton";
import { humanize } from "@/lib/format";
import {
  formatFileSize,
  groupDocumentsByCategory,
  otherCurrentSameType,
  stalenessBadge,
  versionLabel,
} from "@/lib/loan-files/documents";
import type { DocumentResponse } from "@/lib/types/document";
import { cn } from "@/lib/utils";
import { formatDistanceToNow } from "date-fns";
import { Copy, FileText } from "lucide-react";
import { DocumentStatusBadge } from "./document-status";

function relativeTime(iso: string): string {
  try {
    return formatDistanceToNow(new Date(iso), { addSuffix: true });
  } catch {
    return "";
  }
}

function DocumentRow({
  document,
  allDocuments,
  onSelect,
}: {
  document: DocumentResponse;
  allDocuments: DocumentResponse[];
  onSelect: (document: DocumentResponse) => void;
}) {
  const stale = stalenessBadge(document);
  const vlabel = versionLabel(document);
  const others = otherCurrentSameType(document, allDocuments);

  return (
    <button
      type="button"
      onClick={() => onSelect(document)}
      className="flex w-full items-center gap-3 rounded-lg border border-gray-200/80 bg-white px-3.5 py-3 text-left shadow-sm transition-colors hover:border-gray-300 hover:bg-gray-50/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
    >
      <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-gray-100 text-gray-400">
        <FileText className="h-4 w-4" aria-hidden />
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-1.5">
          <span className="truncate text-sm font-medium text-gray-900">
            {document.original_filename}
          </span>
          {vlabel && (
            <span className="shrink-0 rounded-full border border-gray-200 bg-gray-50 px-1.5 py-0 text-[10px] font-medium text-gray-500">
              {vlabel}
            </span>
          )}
        </span>
        <span className="mt-0.5 block truncate text-xs text-gray-500">
          {document.document_type ? humanize(document.document_type) : "—"}
          <span className="text-gray-300"> · </span>
          {formatFileSize(document.file_size_bytes)}
          <span className="text-gray-300"> · </span>
          {relativeTime(document.created_at)}
        </span>
        {/* Tier 2 (recognized) docs carry a short summary gist (LP-65). */}
        {document.summary && (
          <span className="mt-0.5 block truncate text-xs text-gray-400">{document.summary}</span>
        )}
        {/* Calm, informational cues — staleness + gentle duplicate surfacing (LP-71). */}
        {(stale || others.length > 0) && (
          <span className="mt-1 flex flex-wrap items-center gap-1.5">
            {stale && (
              <span
                className={cn(
                  "inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium",
                  stale.className,
                )}
              >
                {stale.label}
              </span>
            )}
            {others.length > 0 && (
              <span className="inline-flex items-center gap-1 text-[11px] text-gray-400">
                <Copy className="h-3 w-3" aria-hidden />
                {others.length} other{" "}
                {document.document_type ? humanize(document.document_type) : "document"}
                {others.length === 1 ? "" : "s"}
              </span>
            )}
          </span>
        )}
      </span>
      <DocumentStatusBadge status={document.status} />
    </button>
  );
}

function ListSkeleton() {
  // Match the real DocumentRow height (h-[58px]) so content arrival doesn't shift.
  return (
    <div aria-busy>
      <output className="sr-only">Loading documents</output>
      <SkeletonRows count={3} itemClassName="h-[58px]" />
    </div>
  );
}

/**
 * The file's documents grouped by category (the eight categories in order, plus
 * a "Processing / uncategorized" group for not-yet-classified docs). Each row
 * shows the filename, classified type, size/date, and a live status badge.
 */
export function DocumentList({
  documents,
  isPending,
  isError,
  onRetry,
  onSelect,
}: {
  documents: DocumentResponse[] | undefined;
  isPending: boolean;
  isError: boolean;
  onRetry?: () => void;
  onSelect: (document: DocumentResponse) => void;
}) {
  if (isPending) return <ListSkeleton />;
  if (isError) {
    return (
      <ErrorState
        title="Couldn’t load your documents"
        message="Something went wrong loading this file’s documents."
        onRetry={onRetry}
      />
    );
  }
  if (!documents || documents.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-gray-200 bg-white px-6 py-10 text-center">
        <p className="text-sm font-medium text-gray-900">No documents yet</p>
        <p className="mt-1 text-sm text-gray-500">Drag files onto the area above to upload.</p>
      </div>
    );
  }

  // Show CURRENT versions only — historical (superseded) versions are reached via the
  // version history in the drawer (LP-71), so the list stays uncluttered.
  const current = documents.filter((d) => d.is_current);
  const groups = groupDocumentsByCategory(current);
  return (
    <div className="space-y-6">
      {groups.map((group) => (
        <section key={group.key}>
          <div className="mb-2 flex items-center gap-2">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500">
              {group.label}
            </h3>
            <span className="rounded-full bg-gray-100 px-1.5 text-[11px] font-medium text-gray-500">
              {group.documents.length}
            </span>
          </div>
          <div className="space-y-2">
            {group.documents.map((doc) => (
              <DocumentRow key={doc.id} document={doc} allDocuments={current} onSelect={onSelect} />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}
