"use client";

import { StatusToken, railClass } from "@/components/status-token";
import { InlineErrorState } from "@/components/ui/error-state";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useReconciliation } from "@/lib/api/reconciliation";
import { formatMoneyPrecise } from "@/lib/format";
import { FINDING_SEVERITY, RECONCILIATION_AGREEMENT, resolveStatus } from "@/lib/status";
import type { ReconciliationRow, RowFinding } from "@/lib/types/reconciliation";
import { cn } from "@/lib/utils";
import Link from "next/link";

/**
 * The reconciliation ledger (LP-UI-018).
 *
 * Stated against found, side by side. This product's whole job is that
 * comparison and until now it had never appeared on a screen AS a comparison —
 * the stated figures lived on one tab, the extracted ones on another, and the
 * processor did the join in their head.
 *
 * Every judgement on this screen is the server's (`services/reconciliation.py`,
 * ADR-391): which rows exist, whether two values agree, and why a row has no
 * source. This component decides only how to draw them. That division is not
 * fussiness — the findings list sits on the same file, and a ledger holding its
 * own opinion about whether two numbers agree would contradict it. LP-UI-013
 * shipped that exact bug one screen over.
 */

/** A money row's values arrive raw; `formatMoneyPrecise` is the app's only money formatter. */
function display(row: ReconciliationRow, value: string | null): string | null {
  if (value === null) return null;
  return row.unit === "money" ? formatMoneyPrecise(value) : value;
}

export function ReconciliationLedger({ fileId }: { fileId: string }) {
  const { data: rows, isPending, isError, refetch } = useReconciliation(fileId);

  const agreed = rows?.filter((row) => row.agreement === "match").length ?? 0;

  // Nothing has been read out of any document yet. Every row would be an amber
  // "not found", which is true but useless: it reports the absence of documents
  // five times over as if it were five separate problems with the application.
  const nothingFound =
    rows !== undefined && rows.length > 0 && rows.every((row) => row.source === null);

  return (
    <section aria-labelledby="reconciliation-heading">
      <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1 pb-2">
        <h2 id="reconciliation-heading" className="text-label uppercase text-muted-foreground">
          Reconciliation — stated against documents
        </h2>
        <span className="flex-1" />
        {rows !== undefined && !nothingFound ? (
          <p className="text-xs text-muted-foreground">
            {agreed} of {rows.length} agree
          </p>
        ) : null}
      </header>

      {isPending ? <LoadingRows /> : null}

      {isError ? (
        <InlineErrorState
          message="Couldn't load the reconciliation."
          onRetry={() => void refetch()}
        />
      ) : null}

      {rows !== undefined && rows.length === 0 ? (
        <Empty>There is nothing to reconcile on this file yet.</Empty>
      ) : null}

      {nothingFound ? (
        <Empty>
          No document has been read for this file yet, so there is nothing to compare the
          application against. Upload the borrower&rsquo;s documents to start the ledger.
        </Empty>
      ) : null}

      {/* `table-fixed` so the percentage widths below are HONOURED. Without it the
          layout is auto, and a `truncate` cell — which sets nowrap — widens its
          column to fit instead of ellipsing, pushing the table off screen. Scoped
          here rather than on the shared Table: fixed layout needs every width
          declared, and the pipeline grid does not declare all ten. */}
      {rows !== undefined && rows.length > 0 && !nothingFound ? (
        <Table className="table-fixed">
          <TableHeader>
            <TableRow>
              <TableHead className="w-[26%]">Field</TableHead>
              <TableHead className="w-[22%]">Stated (1003 / MISMO)</TableHead>
              <TableHead className="w-[22%]">Found in documents</TableHead>
              <TableHead className="w-[30%]">Source</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((row) => (
              <Row key={row.field_key} row={row} fileId={fileId} />
            ))}
          </TableBody>
        </Table>
      ) : null}
    </section>
  );
}

/**
 * The verdict a row reports (A20).
 *
 * Where the rule engine has ruled on this row's question, that finding is the
 * authority and this row's own comparison becomes the evidence beneath it. The
 * two can genuinely disagree — the income variance is overrideable per lender
 * (LP-80) and the read model does not resolve overlays — and a screen that
 * quietly preferred its own answer would be LP-UI-013 all over again, this time
 * inside the feature the redesign is named for.
 */
function verdict(row: ReconciliationRow) {
  return row.finding
    ? resolveStatus(FINDING_SEVERITY, row.finding.status)
    : resolveStatus(RECONCILIATION_AGREEMENT, row.agreement);
}

function Row({ row, fileId }: { row: ReconciliationRow; fileId: string }) {
  const meta = verdict(row);
  // What the LEDGER observed, which is not the same thing as the verdict. An
  // empty cell has to say that no value was found there; filling it with
  // "Warning" because a finding exists answers a question the reader did not
  // ask and drops the one they did.
  const observed = resolveStatus(RECONCILIATION_AGREEMENT, row.agreement);
  // The VALUE's emphasis follows the row's VERDICT, not the ledger's own
  // comparison — the same split the empty cell needed, in the channel next to
  // it. Where the engine has ruled, a row can be green on the rail and the glyph
  // while `agreement` still says `differs`; that is A20 working. Painting the
  // number amber anyway puts the overruled answer back in a channel the reader
  // takes for the verdict, and the row then says both things at once.
  const disagrees = row.finding ? meta.tone !== "verified" : row.agreement !== "match";
  const stated = display(row, row.stated_value);
  const found = display(row, row.found_value);
  const money = row.unit === "money" ? "font-mono text-[13px]" : undefined;

  return (
    <TableRow>
      {/* The rail carries the tone; the glyph carries the same thing as a SHAPE,
          and its accessible name carries it as a word. Three channels, so the
          row still reads with the colour removed. */}
      <TableCell className={cn("py-1.5 align-top", railClass(meta.tone))}>
        <span className="flex items-start gap-2">
          <StatusToken meta={meta} variant="dot" className="mt-0.5 shrink-0" />
          <span className="min-w-0">
            <span className="block text-foreground-2">{row.label}</span>
            {row.finding ? <EngineVerdict finding={row.finding} fileId={fileId} /> : null}
          </span>
        </span>
      </TableCell>

      <TableCell
        className={cn("py-1.5 align-top font-medium text-foreground", stated !== null && money)}
      >
        {stated ?? <StatusToken meta={observed} className="text-xs" />}
      </TableCell>

      {/* A matching value is deliberately quieter than the stated one it
          confirms: the eye should land on the rows that disagree. */}
      <TableCell
        className={cn(
          "py-1.5 align-top",
          // Mono is for FIGURES. A "Not found" token inheriting it renders the
          // word in monospace, which reads as data rather than as a state.
          found !== null && money,
          disagrees ? "text-warning" : "text-foreground-2",
        )}
      >
        {found ?? <StatusToken meta={observed} className="text-xs" />}
      </TableCell>

      <TableCell className="py-1.5 align-top">
        <Source row={row} fileId={fileId} />
      </TableCell>
    </TableRow>
  );
}

/**
 * Provenance for one row — a link to the document, or the reason there is none.
 *
 * The page number is SHOWN but is not part of the link, and the reason has
 * CHANGED. It used to be a real dependency: `?doc=` opened the details drawer,
 * which is metadata and extracted fields, and no page canvas existed for a URL
 * to open at page 2. LP-UI-030 built that canvas and LP-UI-041 pointed `?doc=`
 * at it, so the blocker named here is gone — what remains is that the reviewer
 * holds its page in component state rather than in the URL, so there is no
 * parameter to carry the number. That is a small piece of work, not a missing
 * capability, and it is worth doing precisely because the snippet below is
 * currently standing in for it. Until then the snippet is the evidence:
 * it is the text the extraction actually read, which is the thing a processor
 * would open the page to check.
 */
function Source({ row, fileId }: { row: ReconciliationRow; fileId: string }) {
  if (row.source === null) {
    return <p className="text-xs text-muted-foreground">{row.source_note}</p>;
  }
  const { document_id, filename, page, snippet } = row.source;
  return (
    <span className="block min-w-0">
      <Link
        href={`/loan-files/${fileId}/documents?doc=${document_id}`}
        className="block truncate font-mono text-xs text-muted-foreground hover:text-primary hover:underline"
      >
        {filename}
        {page !== null ? ` · p.${page}` : ""}
      </Link>
      {snippet ? (
        // `text-muted-foreground`, not `/80`. The faded variant measured 3.45:1
        // against the card in light mode — the opacity is what broke it, and the
        // token itself passes. There is no third level of quiet below muted that
        // is still readable; wanting one is a sign the row has too many levels.
        <span className="mt-0.5 block truncate text-xs text-muted-foreground" title={snippet}>
          &ldquo;{snippet}&rdquo;
        </span>
      ) : null}
    </span>
  );
}

/**
 * The engine's ruling on this row, linked to the screen that owns it.
 *
 * Deliberately the rule's own words rather than a restatement: the message is
 * what the Verification tab shows for the same finding, and two phrasings of one
 * ruling is how a processor ends up unsure whether they are looking at one
 * problem or two.
 */
function EngineVerdict({ finding, fileId }: { finding: RowFinding; fileId: string }) {
  return (
    <Link
      href={`/loan-files/${fileId}/verification`}
      className="mt-0.5 block text-xs text-muted-foreground hover:text-primary hover:underline"
    >
      {finding.message}
      {finding.count > 1 ? ` (+${finding.count - 1} more)` : ""}
    </Link>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return (
    <p className="max-w-prose border-t border-border py-3 text-sm text-muted-foreground">
      {children}
    </p>
  );
}

function LoadingRows() {
  return (
    <div className="space-y-2 py-1" aria-busy>
      <output className="sr-only">Loading the reconciliation</output>
      {[0, 1, 2, 3, 4].map((i) => (
        <Skeleton key={i} className="h-6 w-full" />
      ))}
    </div>
  );
}
