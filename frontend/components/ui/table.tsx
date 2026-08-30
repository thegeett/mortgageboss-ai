"use client";

import * as React from "react";

import { cn } from "@/lib/utils";

/**
 * LEDGER — the dense table.                                          LP-UI-007
 * ===========================================================================
 * Height comes from `--row-h` and horizontal padding from `--row-px`, so
 * LP-UI-010's density switch moves every table at once and nothing here needs
 * to know about it. At the compact default that is a 28px row: a processor
 * scanning forty files sees twenty-four of them instead of fifteen.
 *
 * `stickyFirstColumn` pins column one under horizontal scroll. Its shadow is
 * painted only once `scrollLeft > 0` — at rest the column is just a column, and
 * a permanent shadow would advertise a scroll that may not exist.
 *
 * A note on the wrapper, because it is not obvious and it decides whether the
 * sticky header works at all. `position: sticky` resolves against the nearest
 * SCROLLPORT, and any `overflow: auto` ancestor is one. shadcn wraps every table
 * in `overflow-auto`, so the header was sticking to a box that grows with its
 * content and therefore never scrolls — it could not move. CSS gives no way out
 * of this: setting `overflow-x: auto` forces `overflow-y` to compute to `auto`
 * too, so a horizontally-scrolling wrapper is always a vertical scrollport.
 *
 * So the wrapper only becomes a scrollport when the caller asks for one, by
 * passing `stickyFirstColumn` or a `containerClassName` that bounds its height.
 * Otherwise it stays `overflow-visible` and the header sticks to whatever the
 * page actually scrolls — `main` in today's shell.
 */

const ScrolledXContext = React.createContext(false);

const Table = React.forwardRef<
  HTMLTableElement,
  React.HTMLAttributes<HTMLTableElement> & {
    /** Pin the first column under horizontal scroll. */
    stickyFirstColumn?: boolean;
    /** Classes for the scroll container itself (e.g. a max height). */
    containerClassName?: string;
  }
>(({ className, stickyFirstColumn = false, containerClassName, ...props }, ref) => {
  const [scrolledX, setScrolledX] = React.useState(false);
  const ownsScroll = stickyFirstColumn || containerClassName !== undefined;

  const onScroll = React.useCallback((event: React.UIEvent<HTMLDivElement>) => {
    setScrolledX(event.currentTarget.scrollLeft > 0);
  }, []);

  return (
    <ScrolledXContext.Provider value={scrolledX}>
      <div
        className={cn(
          "relative w-full",
          ownsScroll ? "overflow-auto" : "overflow-visible",
          containerClassName,
        )}
        onScroll={stickyFirstColumn ? onScroll : undefined}
        data-scrolled-x={scrolledX ? "true" : undefined}
      >
        <table
          ref={ref}
          className={cn(
            "w-full caption-bottom border-separate border-spacing-0 text-sm",
            // The first cell of every row pins left. `border-separate` above is
            // what makes a sticky cell keep its own background instead of
            // showing the scrolled content through a collapsed border box.
            stickyFirstColumn && "[&_tr>*:first-child]:sticky [&_tr>*:first-child]:left-0",
            stickyFirstColumn && "[&_tr>*:first-child]:z-20 [&_tr>*:first-child]:bg-card",
            className,
          )}
          {...props}
        />
      </div>
    </ScrolledXContext.Provider>
  );
});
Table.displayName = "Table";

const TableHeader = React.forwardRef<
  HTMLTableSectionElement,
  React.HTMLAttributes<HTMLTableSectionElement>
>(({ className, ...props }, ref) => (
  <thead
    ref={ref}
    className={cn(
      // Sticky to the scroll container, or to the page when the page is what
      // scrolls. z-30 keeps it above a sticky first column (z-20).
      "sticky top-0 z-30 bg-background [&_tr]:border-0",
      className,
    )}
    {...props}
  />
));
TableHeader.displayName = "TableHeader";

const TableBody = React.forwardRef<
  HTMLTableSectionElement,
  React.HTMLAttributes<HTMLTableSectionElement>
>(({ className, ...props }, ref) => (
  <tbody ref={ref} className={cn("[&>tr:last-child>*]:border-b-0", className)} {...props} />
));
TableBody.displayName = "TableBody";

const TableFooter = React.forwardRef<
  HTMLTableSectionElement,
  React.HTMLAttributes<HTMLTableSectionElement>
>(({ className, ...props }, ref) => (
  <tfoot
    ref={ref}
    className={cn("bg-muted/50 font-medium [&>tr>*]:border-t [&>tr>*]:border-border", className)}
    {...props}
  />
));
TableFooter.displayName = "TableFooter";

const TableRow = React.forwardRef<HTMLTableRowElement, React.HTMLAttributes<HTMLTableRowElement>>(
  ({ className, ...props }, ref) => (
    <tr
      ref={ref}
      data-row
      className={cn(
        // The hairline is on the CELLS, not the row: `border-separate` (needed
        // for sticky cells) drops row borders entirely.
        "transition-colors [&>*]:border-b [&>*]:border-border",
        "hover:bg-muted/50 data-[state=selected]:bg-muted",
        className,
      )}
      {...props}
    />
  ),
);
TableRow.displayName = "TableRow";

/** Shared geometry. `h-row` is the density variable; `px-cell` its padding. */
const CELL = "h-row px-cell py-0 align-middle [&:has([role=checkbox])]:pr-0";

const TableHead = React.forwardRef<
  HTMLTableCellElement,
  React.ThHTMLAttributes<HTMLTableCellElement>
>(({ className, ...props }, ref) => (
  <th
    ref={ref}
    className={cn(
      CELL,
      "text-left text-label uppercase text-muted-foreground",
      // The header's own rule. On `border-separate` this is the only thing
      // separating it from row one while it floats over the scrolled body.
      "border-b border-border bg-background",
      className,
    )}
    {...props}
  />
));
TableHead.displayName = "TableHead";

const TableCell = React.forwardRef<
  HTMLTableCellElement,
  React.TdHTMLAttributes<HTMLTableCellElement>
>(({ className, ...props }, ref) => {
  const scrolledX = React.useContext(ScrolledXContext);
  return (
    <td
      ref={ref}
      data-scrolled-x={scrolledX ? "true" : undefined}
      className={cn(
        CELL,
        // Only the pinned first cell reads this, and only once scrolled.
        "data-[scrolled-x=true]:first:shadow-[8px_0_8px_-8px_hsl(var(--foreground)/0.12)]",
        className,
      )}
      {...props}
    />
  );
});
TableCell.displayName = "TableCell";

const TableCaption = React.forwardRef<
  HTMLTableCaptionElement,
  React.HTMLAttributes<HTMLTableCaptionElement>
>(({ className, ...props }, ref) => (
  <caption ref={ref} className={cn("mt-3 text-sm text-muted-foreground", className)} {...props} />
));
TableCaption.displayName = "TableCaption";

export { Table, TableHeader, TableBody, TableFooter, TableHead, TableRow, TableCell, TableCaption };
