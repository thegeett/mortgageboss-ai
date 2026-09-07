import { StatusToken } from "@/components/status-token";
import { DOCUMENT_STATUS, resolveStatus } from "@/lib/status";
import type { DocumentStatus } from "@/lib/types/document";

/**
 * A document's live status pill: the glyph spins while the pipeline works, then
 * settles. One vocabulary with every other status in the app (LP-UI-005) — the
 * spinner, the colour and the word all come from `DOCUMENT_STATUS`.
 */
export function DocumentStatusBadge({ status }: { status: DocumentStatus }) {
  return <StatusToken meta={resolveStatus(DOCUMENT_STATUS, status)} variant="chip" />;
}
