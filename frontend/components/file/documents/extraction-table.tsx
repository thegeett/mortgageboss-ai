"use client";

import type { ColumnSpec } from "@/lib/loan-files/documents";
import { ChevronRight } from "lucide-react";

import { EMPTY_VALUE } from "@/lib/loan-files/documents";
import { cn } from "@/lib/utils";

/**
 * A list- or record-valued extracted field, as rows (LP-702).
 *
 * ONE renderer for every list in the corpus. The bank statement's transactions
 * had a private table and the other 77 list keys had nothing, so a pay stub's
 * `earnings_lines` and an HOA statement's `payment_ledger` rendered as
 * `[object Object]`. Giving the general case a renderer is the fix; keeping a
 * second one for transactions would be the bug with better manners.
 *
 * Values are shown AS EXTRACTED — no currency formatting, no re-parsing. This
 * panel's whole claim is "here is what the model read", and a figure the
 * component reformatted is a figure a processor cannot compare against the
 * document.
 */
export function ExtractionTable({
  label,
  summary,
  columns,
  rows,
  className,
}: {
  /**
   * The field's name, when nothing beside the table already says it.
   *
   * The reviewer's row carries its own label — the button that selects the
   * field — so it passes none and the count alone opens the disclosure. The
   * drawer has no such label and passes one.
   */
  label?: string;
  /** The count line — "14 rows" — the disclosure's own summary. */
  summary: string;
  /** Column headers; empty when the rows are plain values with nothing to align. */
  columns: readonly ColumnSpec[];
  rows: readonly (readonly string[])[];
  className?: string;
}) {
  const numeric = numericColumns(columns.length, rows);
  return (
    <details
      // OPEN when it is short enough to read at a glance, closed when it is not.
      // A four-row ledger costs a click to see and nothing to show; a
      // hundred-row one would bury every field under it.
      open={rows.length <= COMPACT_ROWS}
      className={cn(
        "group rounded-lg border border-border [&[open]>summary_svg]:rotate-90",
        className,
      )}
    >
      <summary className="flex cursor-pointer list-none items-center gap-1.5 px-3 py-2 text-sm font-medium text-foreground-2 marker:content-none">
        <ChevronRight
          className="h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform"
          aria-hidden
        />
        {label ? <span className="min-w-0 truncate">{label}</span> : null}
        <span
          className={cn(
            "shrink-0 rounded-full bg-muted px-1.5 text-[11px] font-medium text-muted-foreground",
            label && "ml-auto",
          )}
        >
          {summary}
        </span>
      </summary>

      {columns.length === 0 ? (
        // Plain values — a list of strings has no columns to align, and a
        // one-column table would be a table pretending to be a list.
        <ul className="divide-y divide-border border-t border-border">
          {rows.map((row, i) => (
            <li
              key={`${row[0] ?? ""}-${i}`}
              className="break-words px-3 py-1.5 text-sm text-foreground"
            >
              {row[0] || EMPTY_VALUE}
            </li>
          ))}
        </ul>
      ) : (
        // Scrolls in BOTH directions inside its own box. A credit report's
        // tradelines carry a dozen columns, and letting the page scroll
        // sideways instead would move every other field off screen with it.
        <div className="max-h-72 overflow-auto border-t border-border">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-muted text-[11px] uppercase tracking-wide text-muted-foreground">
              <tr>
                {columns.map((column, i) => (
                  <th
                    // Keyed on the ROW KEY, not the label: the label is humanized and
                    // therefore not injective (`{amount, Amount}` both read "Amount"),
                    // which repeated a React key inside one row.
                    key={column.key}
                    scope="col"
                    className={cn(
                      "whitespace-nowrap px-2 py-1.5 font-medium",
                      numeric[i] ? "text-right" : "text-left",
                    )}
                  >
                    {column.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {rows.map((row, r) => (
                // The row's own cells are its identity here — these rows have no
                // id, and an index-only key reorders wrongly when rows change.
                <tr key={`${row.join("|")}-${r}`} className="hover:bg-muted/60">
                  {columns.map((column, c) => {
                    const cell = row[c] ?? EMPTY_VALUE;
                    return (
                      <td
                        key={columns[c]?.key ?? c}
                        // Long snippets truncate with the full text on hover;
                        // everything else is short enough to show whole.
                        title={cell.length > TRUNCATE_OVER ? cell : undefined}
                        className={cn(
                          "max-w-[16rem] truncate px-2 py-1.5",
                          numeric[c]
                            ? "whitespace-nowrap text-right text-foreground"
                            : "text-foreground-2",
                        )}
                      >
                        {cell}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </details>
  );
}

/** Rows at or below this are shown expanded; longer lists open on demand. */
const COMPACT_ROWS = 6;

/** Cell length past which the full text moves to a `title`. */
const TRUNCATE_OVER = 32;

/**
 * Which columns hold numbers, so they can be right-aligned to compare down.
 *
 * Every non-empty cell has to look numeric. One free-text cell in an "Amount"
 * column means the column is not a column of numbers, and right-aligning it
 * would put a sentence's last word under a figure's last digit.
 */
function numericColumns(count: number, rows: readonly (readonly string[])[]): boolean[] {
  return Array.from({ length: count }, (_, c) => {
    let seen = 0;
    for (const row of rows) {
      const cell = row[c];
      if (!cell || cell === EMPTY_VALUE) continue;
      if (!NUMERIC.test(cell)) return false;
      seen += 1;
    }
    return seen > 0;
  });
}

/** A money-or-number cell as extracted: `1,234.56`, `$1,234.56`, `(45.00)`, `3.5%`, `-12`. */
const NUMERIC = /^[($]?\s*-?[\d,]+(\.\d+)?\s*\)?%?$/;
