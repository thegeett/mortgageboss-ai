import { cn } from "@/lib/utils";

/**
 * The ledger motif, stated once (LP-UI-012).
 *
 * Two columns — what the application says, and what the documents say — with a
 * mark in the margin wherever they disagree. It is the product's thesis in one
 * picture, and the only decorative element in the app.
 *
 * `aria-hidden`: the figure is illustrative, its numbers are invented, and the
 * sentence beneath it states the same idea in words. Reading six fake money
 * values aloud would be noise, not information.
 */

type Agreement = "agrees" | "differs" | "missing";

const RAIL: Record<Agreement, string> = {
  agrees: "bg-success",
  differs: "bg-destructive",
  missing: "bg-warning",
};

const FOUND_TEXT: Record<Agreement, string> = {
  agrees: "text-foreground-2",
  differs: "text-destructive",
  missing: "text-warning",
};

/** Invented, and deliberately plausible: the shapes a processor actually meets. */
const ROWS: { stated: string; found: string; agreement: Agreement }[] = [
  { stated: "$11,416.67", found: "$11,416.67", agreement: "agrees" },
  { stated: "$1,250.00", found: "$980.42", agreement: "missing" },
  { stated: "$720,000", found: "$720,000", agreement: "agrees" },
  { stated: "$48,200.00", found: "$31,845.19", agreement: "differs" },
  { stated: "Cascade Robotics", found: "Cascade Robotics", agreement: "agrees" },
  { stated: "—", found: "Not found", agreement: "missing" },
];

export function LedgerFigure({ className }: { className?: string }) {
  return (
    <div aria-hidden className={cn("w-full max-w-md", className)}>
      <div className="grid grid-cols-[1fr_auto_1fr] items-stretch">
        <p className="border-b border-border pb-1.5 text-label uppercase text-muted-foreground">
          Stated
        </p>
        <span className="border-b border-border" />
        <p className="border-b border-border pb-1.5 pl-4 text-label uppercase text-muted-foreground">
          Found in documents
        </p>

        {ROWS.map((row) => (
          <div key={row.stated + row.found} className="contents">
            <p className="tabular border-b border-border py-2 pr-4 font-mono text-xs text-foreground-2">
              {row.stated}
            </p>
            {/* The mark in the margin — the whole point of the figure. */}
            <span className="flex items-center border-b border-border">
              <span className={cn("h-3.5 w-[3px] rounded-full", RAIL[row.agreement])} />
            </span>
            <p
              className={cn(
                "tabular border-b border-border py-2 pl-4 font-mono text-xs",
                FOUND_TEXT[row.agreement],
              )}
            >
              {row.found}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}
