"use client";

import { DeleteFileDialog } from "@/components/file/delete-file-dialog";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { LoanFileSummary } from "@/lib/types/loan-file";
import { cn } from "@/lib/utils";
import { formatDistanceToNow } from "date-fns";
import { FolderPlus, MoreHorizontal, SearchX, Trash2, TriangleAlert } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

const COLUMNS = ["File ID", "Borrower", "Property", "Status", "Lender", "Last activity"] as const;

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

  const move = useCallback((to: number) => {
    shouldFocus.current = true;
    setActive(to);
  }, []);

  const onKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLTableRowElement>, index: number) => {
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
  const onCellKeyDown = useCallback(
    (event: React.KeyboardEvent, index: number) => {
      if (event.key !== "ArrowLeft" && event.key !== "Escape") return;
      event.preventDefault();
      event.stopPropagation();
      move(index);
    },
    [move],
  );

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

export function FileTable({
  files,
  isPending,
  isError,
  isFiltered,
  onSelect,
  onNewFile,
}: {
  files: LoanFileSummary[];
  isPending: boolean;
  isError: boolean;
  isFiltered: boolean;
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
          Something went wrong fetching your files. Check your connection and try again.
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
        <SearchX className="h-8 w-8 text-muted-foreground" />
        <h3 className="mt-3 text-sm font-semibold text-foreground">No matching files</h3>
        <p className="mt-1 max-w-sm text-sm text-muted-foreground">
          No loan files match your current filters. Try clearing the search or a different filter.
        </p>
      </StatePanel>
    ) : (
      <StatePanel>
        <span className="flex h-12 w-12 items-center justify-center rounded-full bg-primary/10 text-primary">
          <FolderPlus className="h-6 w-6" />
        </span>
        <h3 className="mt-4 text-sm font-semibold text-foreground">No loan files yet</h3>
        <p className="mt-1 max-w-sm text-sm text-muted-foreground">
          Create your first loan file to start assembling documents and tracking requirements.
        </p>
        <Button type="button" onClick={onNewFile} className="mt-5 gap-2">
          <FolderPlus className="h-4 w-4" />
          Create your first file
        </Button>
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
              <TableCell aria-colindex={1} className="font-medium text-foreground">
                {file.display_id}
              </TableCell>
              <TableCell aria-colindex={2} className="text-foreground-2">
                {file.primary_borrower_name ?? "—"}
              </TableCell>
              <TableCell aria-colindex={3} className="max-w-[16rem] truncate text-foreground-2">
                {file.property_address ?? "—"}
              </TableCell>
              <TableCell aria-colindex={4}>
                <StatusBadge status={file.status} />
              </TableCell>
              <TableCell aria-colindex={5} className="text-foreground-2">
                {file.lender_name ?? "—"}
              </TableCell>
              <TableCell aria-colindex={6} className="whitespace-nowrap text-muted-foreground">
                {lastActivity(file.updated_at)}
              </TableCell>
              <TableCell
                aria-colindex={7}
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
