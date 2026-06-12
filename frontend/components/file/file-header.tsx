import { StatusBadge } from "@/components/status-badge";
import { Skeleton } from "@/components/ui/skeleton";
import { programLabel, purposeLabel } from "@/lib/loan-files/labels";
import type { LoanFileDetail } from "@/lib/types/loan-file";
import { format, formatDistanceToNow } from "date-fns";
import { ArrowLeft } from "lucide-react";
import Link from "next/link";

function fmtDate(iso: string): string {
  try {
    return format(new Date(iso), "MMM d, yyyy");
  } catch {
    return "—";
  }
}

function fmtRelative(iso: string): string {
  try {
    return formatDistanceToNow(new Date(iso), { addSuffix: true });
  } catch {
    return "—";
  }
}

/** The persistent file header: borrower name, display_id, status, and key dates.
 * Shows a skeleton while the file loads; the same component fills in once loaded. */
export function FileHeader({ file }: { file: LoanFileDetail | undefined }) {
  return (
    <div className="space-y-3">
      <Link
        href="/dashboard"
        className="inline-flex items-center gap-1.5 rounded text-sm font-medium text-gray-500 transition-colors hover:text-gray-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
      >
        <ArrowLeft className="h-4 w-4" />
        Back to dashboard
      </Link>

      {file === undefined ? (
        <div className="space-y-2" aria-busy>
          <output className="sr-only">Loading the file</output>
          <Skeleton className="h-8 w-64" />
          <Skeleton className="h-4 w-80" />
        </div>
      ) : (
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h1 className="text-2xl font-bold tracking-tight text-gray-900">
              {file.primary_borrower_name ?? "Unnamed file"}
            </h1>
            <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-gray-500">
              <span className="font-mono font-medium text-gray-600">{file.display_id}</span>
              {file.loan_program && (
                <>
                  <span aria-hidden>·</span>
                  <span>{programLabel(file.loan_program)}</span>
                </>
              )}
              {file.loan_purpose && (
                <>
                  <span aria-hidden>·</span>
                  <span>{purposeLabel(file.loan_purpose)}</span>
                </>
              )}
              {file.lender_name && (
                <>
                  <span aria-hidden>·</span>
                  <span>{file.lender_name}</span>
                </>
              )}
            </div>
            <p className="mt-2 text-xs text-gray-400">
              Created {fmtDate(file.created_at)} · Updated {fmtRelative(file.updated_at)}
            </p>
          </div>
          <StatusBadge status={file.status} />
        </div>
      )}
    </div>
  );
}
