import { DOCUMENT_STATUS_META } from "@/lib/loan-files/documents";
import type { DocumentStatus } from "@/lib/types/document";
import { cn } from "@/lib/utils";
import { AlertTriangle, CheckCircle2, Loader2, XCircle } from "lucide-react";

const STATUS_ICON: Record<DocumentStatus, typeof Loader2> = {
  pending: Loader2,
  classifying: Loader2,
  classified: Loader2,
  extracting: Loader2,
  completed: CheckCircle2,
  needs_review: AlertTriangle,
  failed: XCircle,
};

/**
 * A document's live status pill: a spinning loader while the pipeline works
 * (pending/classifying/extracting), then a settled state — green Completed,
 * amber Needs review (honest AI-uncertainty signal), red Failed. Colours come
 * from the single `DOCUMENT_STATUS_META` map (design tokens).
 */
export function DocumentStatusBadge({ status }: { status: DocumentStatus }) {
  const meta = DOCUMENT_STATUS_META[status];
  const Icon = STATUS_ICON[status];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2 py-0.5 text-xs font-medium",
        meta.className,
      )}
    >
      <Icon className={cn("h-3 w-3", meta.inProgress && "animate-spin")} aria-hidden />
      {meta.label}
    </span>
  );
}
