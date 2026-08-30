"use client";

import { StatusToken, railClass } from "@/components/status-token";
import { ErrorState } from "@/components/ui/error-state";
import { SkeletonRows } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { humanize } from "@/lib/format";
import {
  formatFileSize,
  groupDocumentsByCategory,
  isTerminalStatus,
  packageReadyBadge,
  stalenessBadge,
  versionLabel,
} from "@/lib/loan-files/documents";
import { DOCUMENT_STATUS, resolveStatus } from "@/lib/status";
import type { DocumentResponse } from "@/lib/types/document";
import { cn } from "@/lib/utils";
import { PackageCheck } from "lucide-react";

/**
 * The file's documents, grouped by category, as table rows (LP-UI-019).
 *
 * They were cards. A card gives every document the same weight and the same
 * height whether it is a verified W-2 or a pay stub with four fields to check,
 * and eighteen of them is a page you scroll rather than a list you scan. As
 * rows, the period and the status line up in columns and the outliers are the
 * ones that break the column.
 *
 * IN-FLIGHT DOCUMENTS ARE NOT HERE. They sit in the ProcessingStrip above, so a
 * classifying document — which has no type, no period and no size yet — does not
 * hold a row that changes every few seconds and shifts everything under it.
 *
 * Two signals moved to the context rail rather than repeating on every row:
 * which documents are out of date, and which share a type. Both were per-row
 * cues you had to notice one at a time; in the rail each is one answer for the
 * whole file. Staleness still shows in the row's status, because that is where
 * a reader looks to find out whether a document is usable.
 */

function DocumentRow({
  document,
  onSelect,
}: {
  document: DocumentResponse;
  onSelect: (document: DocumentResponse) => void;
}) {
  const stale = stalenessBadge(document);
  const meta = resolveStatus(DOCUMENT_STATUS, document.status);
  const vlabel = versionLabel(document);

  return (
    <TableRow
      // A row is a button: click, Enter and Space all open the drawer. LP-UI-007
      // shipped a row whose keyboard path did not match its mouse path and made
      // an action unreachable without a pointer; this keeps the two the same.
      tabIndex={0}
      onClick={() => onSelect(document)}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onSelect(document);
        }
      }}
      className="cursor-pointer"
    >
      <TableCell className={cn("py-1.5 align-top", railClass(meta.tone))}>
        <span className="flex items-center gap-1.5">
          {/* The derived standard name (LP-72) is the scannable primary label. */}
          <span className="truncate font-medium text-foreground">
            {document.standard_name || document.original_filename}
          </span>
          {vlabel ? (
            <span className="shrink-0 rounded-full border border-border bg-muted px-1.5 text-[10px] font-medium text-muted-foreground">
              {vlabel}
            </span>
          ) : null}
          {packageReadyBadge(document) ? (
            <PackageCheck
              className="h-3.5 w-3.5 shrink-0 text-success"
              aria-label="Package-ready"
            />
          ) : null}
        </span>
        {/* Tier 2 (recognized) documents carry a short gist (LP-65). The mockup's
            table has no line for it; dropping a shipped signal to match a drawing
            is not a reason, so it stays as a quiet second line. */}
        {document.summary ? (
          <span className="mt-0.5 block truncate text-xs text-muted-foreground">
            {document.summary}
          </span>
        ) : null}
      </TableCell>

      {/* The consolidated period (LP-105) — what tells two pay stubs apart. */}
      <TableCell className="py-1.5 align-top text-foreground-2">
        {document.period ? `${document.period.label}: ${document.period.value}` : "—"}
      </TableCell>

      <TableCell className="py-1.5 align-top text-foreground-2">
        {document.document_type ? humanize(document.document_type) : "Unknown"}
      </TableCell>

      <TableCell className="py-1.5 align-top">
        <StatusToken meta={meta} />
        {/* Staleness is about whether the document can still be used, which is
            the question this column answers. The rail says how many; this says
            which, on the row a reader is already looking at. */}
        {stale ? <span className="mt-0.5 block text-xs text-warning">{stale.label}</span> : null}
      </TableCell>

      <TableCell className="py-1.5 align-top tabular text-muted-foreground">
        {formatFileSize(document.file_size_bytes)}
      </TableCell>
    </TableRow>
  );
}

function ListSkeleton() {
  return (
    <div aria-busy>
      <output className="sr-only">Loading documents</output>
      <SkeletonRows count={3} itemClassName="h-[58px]" />
    </div>
  );
}

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
      <div className="rounded-lg border border-dashed border-border bg-card px-6 py-10 text-center">
        <p className="text-sm font-medium text-foreground">No documents yet</p>
        <p className="mt-1 text-sm text-muted-foreground">
          Drag files onto the area above to upload.
        </p>
      </div>
    );
  }

  // CURRENT and SETTLED only. Superseded versions are reached through the
  // drawer's version history (LP-71); in-flight documents are in the strip.
  const settled = documents.filter((doc) => doc.is_current && isTerminalStatus(doc.status));

  if (settled.length === 0) {
    return (
      <p className="rounded-md border border-border px-4 py-6 text-center text-sm text-muted-foreground">
        Every document on this file is still processing.
      </p>
    );
  }

  const groups = groupDocumentsByCategory(settled);

  return (
    <div className="space-y-6">
      {groups.map((group) => (
        <section key={group.key} aria-labelledby={`docgroup-${group.key}`}>
          <div className="mb-1 flex items-center gap-2">
            <h3 id={`docgroup-${group.key}`} className="text-label uppercase text-muted-foreground">
              {group.label}
            </h3>
            <span className="rounded-full bg-muted px-1.5 text-[11px] font-medium text-muted-foreground">
              {group.documents.length}
            </span>
          </div>
          {/* `table-fixed` so the percentage widths above are HONOURED. Without it
              the layout is auto, and a `truncate` cell — which sets nowrap — widens
              its column to fit instead of ellipsing, pushing the table off screen.
              Scoped here rather than on the shared Table: fixed layout needs every
              width declared, and the pipeline grid does not declare all ten. */}
          <Table className="table-fixed">
            <TableHeader>
              <TableRow>
                <TableHead className="w-[40%]">Document</TableHead>
                <TableHead className="w-[18%]">Period</TableHead>
                <TableHead className="w-[14%]">Type</TableHead>
                <TableHead className="w-[19%]">Status</TableHead>
                <TableHead className="w-[9%]">Size</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {group.documents.map((doc) => (
                <DocumentRow key={doc.id} document={doc} onSelect={onSelect} />
              ))}
            </TableBody>
          </Table>
        </section>
      ))}
    </div>
  );
}
