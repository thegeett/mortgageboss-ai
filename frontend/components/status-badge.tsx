import { STATUS_META } from "@/lib/loan-files/status";
import type { LoanFileStatus } from "@/lib/types/loan-file";
import { cn } from "@/lib/utils";

/**
 * A calm, color-meaningful loan-file status pill. Colours and labels come from
 * the single `STATUS_META` map (LP-31), so every surface — dashboard table, file
 * header (LP-33), … — shows a status the same way.
 */
export function StatusBadge({ status }: { status: LoanFileStatus }) {
  const meta = STATUS_META[status];
  return (
    <span
      className={cn(
        "inline-flex items-center whitespace-nowrap rounded-full border px-2 py-0.5 text-xs font-medium",
        meta.className,
      )}
    >
      {meta.label}
    </span>
  );
}
