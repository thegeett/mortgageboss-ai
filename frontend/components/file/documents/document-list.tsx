"use client";

import { StatusToken, railClass } from "@/components/status-token";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { Skeleton } from "@/components/ui/skeleton";
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
import { Info, PackageCheck } from "lucide-react";

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

/** Exported for `list-skeleton.test.tsx`, which compares its cell count to the skeleton's. */
export function DocumentRow({
  document,
  onOpen,
  onOpenDetails,
}: {
  document: DocumentResponse;
  /** Open the document itself — the page beside its extracted fields. */
  onOpen: (document: DocumentResponse) => void;
  /** Open the details drawer: type, versions, staleness, replace, delete. */
  onOpenDetails: (document: DocumentResponse) => void;
}) {
  const stale = stalenessBadge(document);
  const meta = resolveStatus(DOCUMENT_STATUS, document.status);
  const vlabel = versionLabel(document);

  return (
    <TableRow
      // A row is a button: click, Enter and Space all OPEN THE DOCUMENT. It used
      // to open the details drawer, which answered a different question — a
      // processor clicking a pay stub wants to see the pay stub, and the mockup's
      // Documents screen has no drawer on it at all. The drawer's own answers
      // (type, versions, staleness, replace, delete) are a click away on the
      // trailing button, so nothing became unreachable.
      //
      // LP-UI-007 shipped a row whose keyboard path did not match its mouse path
      // and made an action unreachable without a pointer; this keeps the two the
      // same.
      tabIndex={0}
      onClick={() => onOpen(document)}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onOpen(document);
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

      {/* The drawer's entry point. A row opens the DOCUMENT; this opens what is
          known ABOUT it — type, versions, freshness, replace, delete. Its own
          control because they are different questions, and because a row that
          did both had to pick one. */}
      <TableCell className="w-10 py-1.5 align-top">
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          aria-label={`Details for ${document.standard_name || document.original_filename}`}
          onClick={(event) => {
            // The row is a button too; without this the drawer opens and the
            // reviewer navigates underneath it.
            event.stopPropagation();
            onOpenDetails(document);
          }}
        >
          <Info className="h-3.5 w-3.5" />
        </Button>
      </TableCell>
    </TableRow>
  );
}

/**
 * The loading state, built from the SAME table primitives as the real rows.
 *
 * It used to be a stack of `h-[58px]` bars, and by the time anyone measured it
 * the rows were 53px — a 5px jump per row on every documents tab. A hardcoded
 * height is a copy of a number that lives somewhere else, and it rots silently
 * because nothing renders both and compares.
 *
 * Cells inherit their height from the row primitive, so the skeleton cannot
 * drift from the row again: change the density and both move together. This is
 * what `file-table`'s `LoadingRows` does, and that one measures 0px of shift.
 */
/**
 * The table's columns, declared once.
 *
 * The loading skeleton and the real table both render this. Writing the header
 * twice — which is what this replaces — lets a new column reach the rows and not
 * the skeleton, and the two then disagree about how many cells a row has, which
 * shows up as a column that jumps sideways when the data lands.
 */
export const DOCUMENT_COLUMNS: ReadonlyArray<{ label: string; width: string; skeleton: string }> = [
  { label: "Document", width: "w-[40%]", skeleton: "w-3/4" },
  { label: "Period", width: "w-[18%]", skeleton: "w-2/3" },
  { label: "Type", width: "w-[14%]", skeleton: "w-1/2" },
  { label: "Status", width: "w-[19%]", skeleton: "w-2/3" },
  { label: "Size", width: "w-[9%]", skeleton: "w-1/3" },
];

/** Exported so a test can render it beside a real row and compare cell counts. */
export function DocumentTableHeader() {
  return (
    <TableHeader>
      <TableRow>
        {DOCUMENT_COLUMNS.map((column) => (
          <TableHead key={column.label} className={column.width}>
            {column.label}
          </TableHead>
        ))}
        <TableHead className="w-10">
          <span className="sr-only">Details</span>
        </TableHead>
      </TableRow>
    </TableHeader>
  );
}

export function ListSkeleton() {
  return (
    <div aria-busy>
      <output className="sr-only">Loading documents</output>
      {/* THE GROUP HEADING, which the loaded list ALWAYS renders and this did
          not. Every real render puts a category label and a count pill above the
          table; a skeleton without one hands the table back lower than it started,
          on every documents tab. Same discipline as the cells: the `h3` and the
          pill keep their own classes so the line box comes from the type scale
          rather than from a height somebody typed here. */}
      <div className="mb-1 flex items-center gap-2">
        <h3 className="text-label uppercase text-muted-foreground">
          <Skeleton className="inline-block h-[0.75em] w-24 align-middle" />
        </h3>
        <span className="rounded-full bg-muted px-1.5 text-[11px] font-medium text-muted-foreground">
          <Skeleton className="inline-block h-[0.75em] w-2 align-middle" />
        </span>
      </div>
      <Table className="table-fixed">
        <DocumentTableHeader />
        <TableBody>
          {Array.from({ length: 3 }, (_, row) => row).map((row) => (
            <TableRow key={row}>
              {/* The first cell carries TWO lines on a real row — the standard
                  name and, for a recognised document, its gist — and two lines
                  are what make the row 53px rather than 28px. The skeleton
                  reproduces the shape, not just the primitive, because the
                  primitive alone measured a 25px jump. */}
              <TableCell className="py-1.5 align-top">
                {/* h-5 / h-4 are the LINE HEIGHTS of `text-sm` and `text-xs`,
                    not guesses: the bars stand in for those two lines, so they
                    take their sizes. */}
                <Skeleton className="h-5 w-3/4" />
                <Skeleton className="mt-0.5 h-4 w-1/2" />
              </TableCell>
              {DOCUMENT_COLUMNS.slice(1).map((column) => (
                <TableCell key={column.label} className="py-1.5 align-top">
                  <Skeleton className={cn("h-5", column.skeleton)} />
                </TableCell>
              ))}
              {/* The details control's column, so the skeleton and the real row
                  agree on cell count and nothing shifts sideways on arrival. */}
              <TableCell className="w-10 py-1.5 align-top">
                <Skeleton className="h-5 w-5" />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

export function DocumentList({
  documents,
  isPending,
  isError,
  onRetry,
  onOpen,
  onOpenDetails,
}: {
  documents: DocumentResponse[] | undefined;
  isPending: boolean;
  isError: boolean;
  onRetry?: () => void;
  /** Open the document — the page beside its extracted fields. */
  onOpen: (document: DocumentResponse) => void;
  /** Open the details drawer for one document. */
  onOpenDetails: (document: DocumentResponse) => void;
}) {
  if (isPending) return <ListSkeleton />;
  if (isError) {
    return (
      <ErrorState
        title="Couldn’t load your documents"
        // Names what failed and what still holds. "Something went wrong" said
        // neither, and the ticket bans the phrase for that reason.
        message="The list didn’t come back. Nothing has been changed — the documents are still on the file."
        onRetry={onRetry}
      />
    );
  }
  if (!documents || documents.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-border bg-card">
        <EmptyState kind="nothing-yet" title="No documents yet">
          Drop a pay stub, a bank statement or a W-2 onto the area above. Each one is read and its
          figures land on this file.
        </EmptyState>
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
            <DocumentTableHeader />
            <TableBody>
              {group.documents.map((doc) => (
                <DocumentRow
                  key={doc.id}
                  document={doc}
                  onOpen={onOpen}
                  onOpenDetails={onOpenDetails}
                />
              ))}
            </TableBody>
          </Table>
        </section>
      ))}
    </div>
  );
}
