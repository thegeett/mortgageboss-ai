"use client";

import {
  ATTENTION_STRIPE,
  AttentionCell,
  NeedsProgress,
} from "@/components/dashboard/attention-cell";
import { DeleteFileDialog } from "@/components/file/delete-file-dialog";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatMoney } from "@/lib/format";
import type { LoanFileSummary } from "@/lib/types/loan-file";
import { cn } from "@/lib/utils";
import { formatDistanceToNow } from "date-fns";
import { FolderPlus, MoreHorizontal, SearchX, Trash2, TriangleAlert } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

const COLUMNS = [
  "File",
  "Borrower",
  "Property",
  "Amount",
  "Stage",
  "Attention",
  "Needs",
  "Lender",
  "Touched",
] as const;

/**
 * Roving tabindex over the rows (LP-UI-007).
 *
 * Every row used to carry `tabIndex={0}`, and each row's action button another,
 * so a forty-file table was ~80 tab stops standing between the header and the
 * page's real controls. The ARIA grid pattern says a grid is ONE tab stop and
 * the arrow keys move within it — which is also how a processor expects a list
 * of files to behave.
 */
function useRovingRows(count: number, onActivate: (index: number) => void) {
  const [active, setActive] = useState(0);
  const rowRefs = useRef<(HTMLTableRowElement | null)[]>([]);
  // Only steal focus when the move came from the keyboard. Re-focusing on a
  // data refetch would yank the caret out of the search box mid-type.
  const shouldFocus = useRef(false);

  // Filtering can shrink the list under the cursor; clamp rather than leave the
  // roving index pointing at a row that no longer exists.
  useEffect(() => {
    setActive((i) => (count === 0 ? 0 : Math.min(i, count - 1)));
  }, [count]);

  useEffect(() => {
    if (!shouldFocus.current) return;
    shouldFocus.current = false;
    rowRefs.current[active]?.focus();
  }, [active]);

  const move = useCallback(
    (to: number) => {
      // Arm the focus steal ONLY when the index actually changes. React bails out
      // of a same-value setState, so on ArrowUp at row 0 or ArrowDown/End at the
      // last row — all reachable by holding a key — the `[active]` effect never
      // ran to clear the flag. It stayed armed until the next unrelated `active`
      // change, i.e. the `[count]` clamp on a refetch or a filter, which then
      // pulled focus onto a row: exactly the yank the comment above forbids.
      if (to === active) return;
      shouldFocus.current = true;
      setActive(to);
    },
    [active],
  );

  const onKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLTableRowElement>, index: number) => {
      // Bound on the <tr>, so every keydown from inside a cell bubbles here.
      // Without this check the row-actions button answered Enter by navigating to
      // the loan file instead of opening its menu — and since that button is
      // `tabIndex={-1}`, ArrowRight is the ONLY way to reach it, which made
      // "Delete file" unreachable by keyboard entirely. Arrow/Home/End likewise
      // moved the roving stop out from under the focused button.
      if (event.target !== event.currentTarget) return;
      switch (event.key) {
        case "ArrowDown":
          event.preventDefault();
          move(Math.min(index + 1, count - 1));
          break;
        case "ArrowUp":
          event.preventDefault();
          move(Math.max(index - 1, 0));
          break;
        case "Home":
          event.preventDefault();
          move(0);
          break;
        case "End":
          event.preventDefault();
          move(count - 1);
          break;
        case "ArrowRight": {
          // The row menu is tabIndex=-1 so it costs no tab stop; the grid
          // pattern reaches a widget inside a cell with the arrow keys instead.
          event.preventDefault();
          const button = rowRefs.current[index]?.querySelector<HTMLButtonElement>("button");
          button?.focus();
          break;
        }
        case "Enter":
        case " ":
          event.preventDefault();
          onActivate(index);
          break;
        default:
          break;
      }
    },
    [count, move, onActivate],
  );

  /** ArrowLeft or Escape inside a cell widget returns focus to its row. */
  const onCellKeyDown = useCallback((event: React.KeyboardEvent, index: number) => {
    if (event.key !== "ArrowLeft" && event.key !== "Escape") return;
    event.preventDefault();
    event.stopPropagation();
    // Focuses the row DIRECTLY rather than going through `move`. The row is
    // almost always already the active one — you arrowed right from it — so a
    // state-change-driven focus would be a no-op precisely when it is needed.
    setActive(index);
    rowRefs.current[index]?.focus();
  }, []);

  return { active, rowRefs, onKeyDown, onCellKeyDown, setActive };
}

function lastActivity(iso: string): string {
  try {
    return formatDistanceToNow(new Date(iso), { addSuffix: true });
  } catch {
    return "—";
  }
}

function HeaderRow() {
  return (
    <TableHeader>
      {/* Row 1 of the grid. `aria-colindex` is what lets a screen reader say
          "column 3 of 7" from any cell, header or body. */}
      <TableRow className="hover:bg-transparent" aria-rowindex={1}>
        {COLUMNS.map((col, i) => (
          <TableHead key={col} aria-colindex={i + 1} scope="col">
            {col}
          </TableHead>
        ))}
        <TableHead className="w-10" aria-colindex={COLUMNS.length + 1} scope="col">
          <span className="sr-only">Actions</span>
        </TableHead>
      </TableRow>
    </TableHeader>
  );
}

// Per-column widths roughly matching real content (ID short, address long) so
// columns don't resize when rows arrive.
const COLUMN_SKELETON_WIDTHS = ["w-16", "w-32", "w-40", "w-16", "w-24", "w-20"] as const;

function LoadingRows() {
  return (
    <TableBody>
      {Array.from({ length: 6 }, (_, i) => i).map((row) => (
        <TableRow key={row} aria-rowindex={row + 2}>
          {COLUMNS.map((col, i) => (
            <TableCell key={col} aria-colindex={i + 1}>
              {/* The CELL is --row-h; the bar inside it is deliberately shorter,
                  so a skeleton row and a real row are the same height and the
                  table does not jump when data arrives. */}
              <Skeleton className={cn("h-3", COLUMN_SKELETON_WIDTHS[i])} />
            </TableCell>
          ))}
          <TableCell aria-colindex={COLUMNS.length + 1}>
            <Skeleton className="h-3 w-3" />
          </TableCell>
        </TableRow>
      ))}
    </TableBody>
  );
}

/** A centered state panel (empty / error) spanning the table width. */
function StatePanel({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-16 text-center">
      {children}
    </div>
  );
}

/**
 * The filtered-empty sentence, naming what a processor can undo.
 *
 * Degrades honestly: with no summary it says the general thing rather than
 * inventing a filter name, and it only promises a count when it has one — "see
 * all four" is a claim, and a wrong one sends a processor looking for files that
 * are not there.
 */
export function describeFilter(summary?: {
  search: string;
  statusLabel: string | null;
  unfilteredTotal: number | null;
}): string {
  if (!summary) return "Nothing matches the filters on this list. Clear them to see every file.";
  const { search, statusLabel, unfilteredTotal } = summary;
  const query = search.trim();
  const where = statusLabel ? `Nothing in ${statusLabel}` : "Nothing on this list";
  const matching = query ? ` matches “${query}”` : "";
  const back =
    unfilteredTotal === null
      ? " Clear the filters to see every file."
      : ` Clear the filters to see ${unfilteredTotal === 1 ? "the one file" : `all ${unfilteredTotal}`}.`;
  return `${where}${matching}.${back}`;
}

export function FileTable({
  files,
  isPending,
  isError,
  isFiltered,
  filterSummary,
  onClearFilters,
  onSelect,
  onNewFile,
}: {
  files: LoanFileSummary[];
  isPending: boolean;
  isError: boolean;
  isFiltered: boolean;
  /**
   * What is actually hiding the rows (LP-UI-034). "No files match your current
   * filters" tells a processor nothing they can undo; naming the filter, the
   * query and how many would come back tells them exactly what to click.
   */
  filterSummary?: { search: string; statusLabel: string | null; unfilteredTotal: number | null };
  onClearFilters?: () => void;
  onSelect: (file: LoanFileSummary) => void;
  onNewFile: () => void;
}) {
  // The file pending deletion drives the confirmation dialog; the mutation invalidates
  // the list query on success, so the deleted row simply drops out on the next render.
  const [pendingDelete, setPendingDelete] = useState<LoanFileSummary | null>(null);

  // Hooks run before the early returns below — a conditional hook is a crash,
  // and the loading/empty branches return before the grid renders.
  const activate = useCallback(
    (index: number) => {
      const file = files[index];
      if (file) onSelect(file);
    },
    [files, onSelect],
  );
  const { active, rowRefs, onKeyDown, onCellKeyDown, setActive } = useRovingRows(
    files.length,
    activate,
  );

  if (isError) {
    return (
      <StatePanel>
        <TriangleAlert className="h-8 w-8 text-destructive" />
        <h3 className="mt-3 text-sm font-semibold text-foreground">
          Couldn&apos;t load loan files
        </h3>
        <p className="mt-1 max-w-sm text-sm text-muted-foreground">
          The list didn&apos;t come back. Your files are unaffected — check your connection and try
          again.
        </p>
      </StatePanel>
    );
  }

  if (isPending) {
    return (
      <div aria-busy>
        <output className="sr-only">Loading loan files</output>
        <Table>
          <HeaderRow />
          <LoadingRows />
        </Table>
      </div>
    );
  }

  if (files.length === 0) {
    return isFiltered ? (
      <StatePanel>
        <EmptyState
          kind="filtered"
          title="No files match"
          action={
            onClearFilters ? (
              <Button type="button" variant="outline" size="sm" onClick={onClearFilters}>
                Clear the filters
              </Button>
            ) : null
          }
        >
          {describeFilter(filterSummary)}
        </EmptyState>
      </StatePanel>
    ) : (
      <StatePanel>
        <EmptyState
          kind="nothing-yet"
          title="No loan files yet"
          action={
            <Button type="button" onClick={onNewFile} className="gap-2">
              <FolderPlus className="h-4 w-4" />
              Create your first file
            </Button>
          }
        >
          A file holds the documents, the extracted data and the conditions for one loan. Create one
          and it starts assembling itself.
        </EmptyState>
      </StatePanel>
    );
  }

  return (
    <>
      {/* biome-ignore lint/a11y/useSemanticElements: an ARIA *grid* is not a
          static table. `role="grid"` is what tells assistive tech this is an
          interactive widget with one tab stop and arrow-key navigation, and it
          is what the WAI-ARIA APG data-grid pattern specifies on a <table>.
          Dropping it would leave the roving tabindex below with no semantics. */}
      <Table
        role="grid"
        aria-label="Loan files"
        aria-rowcount={files.length + 1}
        aria-colcount={COLUMNS.length + 1}
      >
        <HeaderRow />
        <TableBody>
          {files.map((file, index) => (
            <TableRow
              key={file.id}
              ref={(node) => {
                rowRefs.current[index] = node;
              }}
              aria-rowindex={index + 2}
              onClick={() => {
                setActive(index);
                onSelect(file);
              }}
              className="cursor-pointer"
              // One tab stop for the whole grid: exactly one row is reachable
              // by Tab, and the arrow keys move the stop between rows.
              tabIndex={index === active ? 0 : -1}
              onKeyDown={(event) => onKeyDown(event, index)}
            >
              <TableCell
                aria-colindex={1}
                // The stripe says the same thing as the Attention column, so the
                // row reads while scanning without stopping to read the words.
                className={cn(
                  "font-medium text-foreground",
                  file.attention
                    ? ATTENTION_STRIPE[file.attention.tone]
                    : "border-l-2 border-l-transparent",
                )}
              >
                {file.display_id}
              </TableCell>
              <TableCell aria-colindex={2} className="text-foreground-2">
                {file.primary_borrower_name ?? "—"}
              </TableCell>
              <TableCell aria-colindex={3} className="max-w-[16rem] truncate text-foreground-2">
                {file.property_address ?? "—"}
              </TableCell>
              <TableCell aria-colindex={4} className="tabular text-right text-foreground-2">
                {file.loan_amount ? formatMoney(file.loan_amount) : "—"}
              </TableCell>
              <TableCell aria-colindex={5}>
                <StatusBadge status={file.status} />
              </TableCell>
              <TableCell aria-colindex={6} className="max-w-[18rem] truncate">
                <AttentionCell attention={file.attention} />
              </TableCell>
              <TableCell aria-colindex={7} className="text-right">
                <NeedsProgress attention={file.attention} />
              </TableCell>
              <TableCell aria-colindex={8} className="text-foreground-2">
                {file.lender_name ?? "—"}
              </TableCell>
              <TableCell aria-colindex={9} className="whitespace-nowrap text-muted-foreground">
                {lastActivity(file.updated_at)}
              </TableCell>
              <TableCell
                aria-colindex={10}
                onKeyDown={(event) => onCellKeyDown(event, index)}
                className="text-right"
                // The row navigates on click; the menu must not. Stop propagation for
                // the trigger click AND any stray click the menu's close dispatches over
                // this cell, so opening/using the menu never triggers row navigation.
                onClick={(event) => event.stopPropagation()}
              >
                {/* modal={false}: a modal dropdown dispatches a click-through onto the
                    element beneath it when an item is selected — over the row, that would
                    navigate. Non-modal avoids the pointer-lock + the stray click. */}
                <DropdownMenu modal={false}>
                  <DropdownMenuTrigger asChild>
                    <Button
                      type="button"
                      size="icon-sm"
                      variant="ghost"
                      className="text-muted-foreground hover:text-foreground-2"
                      aria-label={`Actions for ${file.display_id}`}
                      tabIndex={-1}
                      onClick={(event) => event.stopPropagation()}
                    >
                      <MoreHorizontal className="h-4 w-4" />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end" className="w-40">
                    <DropdownMenuItem
                      className="text-destructive focus:text-destructive"
                      onSelect={() => setPendingDelete(file)}
                    >
                      <Trash2 className="mr-2 h-4 w-4" /> Delete file
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>

      <DeleteFileDialog
        file={pendingDelete}
        open={pendingDelete !== null}
        onOpenChange={(open) => {
          if (!open) setPendingDelete(null);
        }}
      />
    </>
  );
}
