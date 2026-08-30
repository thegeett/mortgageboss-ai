import { FileHeaderActions } from "@/components/file/file-header-actions";
import { FileContextDrawer } from "@/components/layout/file-context-rail";
import { StatusToken } from "@/components/status-token";
import { Skeleton } from "@/components/ui/skeleton";
import { formatMoney } from "@/lib/format";
import { programLabel, purposeLabel } from "@/lib/loan-files/labels";
import { LOAN_FILE_STATUS, resolveStatus } from "@/lib/status";
import type { LoanFileDetail } from "@/lib/types/loan-file";

/**
 * The file's identity strip (LP-UI-016).
 *
 * One line of identity — who, which file, what kind of loan, whose lender, and
 * where it stands — with the two numbers a processor checks first set right:
 * the loan amount and the property it is secured on.
 *
 * Two things left this component. "Back to dashboard" became the topbar
 * breadcrumb, because where you are is a property of the screen rather than of
 * the file. And the tab strip moved into the shell's context column, so the
 * header no longer competes with a second navigation directly beneath it —
 * LP-UI-008 shipped that column, and this is the ticket that stops the
 * duplication.
 */

/**
 * The strip's own height, shared by the loaded and loading states.
 *
 * 54px is the loaded strip's natural height — the 20px title line plus 6px and
 * the 22px chip row. Measured, not guessed: at 3.25rem the skeleton came out
 * 52px against a loaded 54px, and a 2px jump on every file open is exactly the
 * shift this ticket's criterion exists to prevent.
 */
const STRIP = "flex min-h-[3.375rem] flex-wrap items-start justify-between gap-x-6 gap-y-2";

export function FileHeader({ file }: { file: LoanFileDetail | undefined }) {
  if (file === undefined) {
    return (
      // Same height as the loaded strip, so nothing below it moves when the
      // file arrives. The bars sit inside the strip's own box rather than
      // approximating it.
      <div className={STRIP} aria-busy>
        <output className="sr-only">Loading the file</output>
        <div className="min-w-0 space-y-2">
          <Skeleton className="h-6 w-56" />
          <Skeleton className="h-4 w-72" />
        </div>
        <div className="space-y-2 text-right">
          <Skeleton className="ml-auto h-6 w-32" />
          <Skeleton className="ml-auto h-4 w-48" />
        </div>
      </div>
    );
  }

  return (
    <div className={STRIP}>
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <h1 className="truncate text-xl font-semibold tracking-tight text-foreground">
            {file.primary_borrower_name ?? "Unnamed file"}
          </h1>
          <StatusToken meta={resolveStatus(LOAN_FILE_STATUS, file.status)} />
        </div>

        <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
          <Chip mono>{file.display_id}</Chip>
          {file.loan_program ? <Chip>{programLabel(file.loan_program)}</Chip> : null}
          {file.loan_purpose ? <Chip>{purposeLabel(file.loan_purpose)}</Chip> : null}
          {file.lender_name ? <Chip>{file.lender_name}</Chip> : null}
        </div>
      </div>

      <div className="flex shrink-0 items-start gap-3">
        <div className="text-right">
          <p className="tabular text-xl font-semibold tracking-tight text-foreground">
            {file.loan_amount ? formatMoney(file.loan_amount) : "—"}
          </p>
          <p className="mt-0.5 max-w-[22rem] truncate text-sm text-muted-foreground">
            {file.property_address ?? "No property address"}
          </p>
        </div>
        {/* Below `xl` the context rail is hidden, and this is the only way to
            the file's status, ratios and activity (LP-UI-037). It lives beside
            the file's other actions rather than in the topbar, because it is
            about THIS file. */}
        <FileContextDrawer fileId={file.display_id} />
        <FileHeaderActions file={file} />
      </div>
    </div>
  );
}

/** A quiet fact about the file. Not a status — those go through StatusToken. */
function Chip({ children, mono = false }: { children: React.ReactNode; mono?: boolean }) {
  return (
    <span
      className={
        mono
          ? "rounded border border-border bg-muted px-1.5 py-0.5 font-mono text-xs text-foreground-2"
          : "rounded border border-border bg-muted px-1.5 py-0.5 text-xs text-foreground-2"
      }
    >
      {children}
    </span>
  );
}
