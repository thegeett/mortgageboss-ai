"use client";

import { StatusToken } from "@/components/status-token";
import { isTerminalStatus } from "@/lib/loan-files/documents";
import { DOCUMENT_STATUS, resolveStatus } from "@/lib/status";
import type { DocumentResponse } from "@/lib/types/document";

/**
 * Documents still moving through the pipeline, held ABOVE the list (LP-UI-019).
 *
 * The reason they are not in the table: a document that is classifying has no
 * type, no period and no size worth reading, so it occupied a row that could say
 * almost nothing — and every few seconds it changed, moving the nine settled
 * documents underneath it. Watching three uploads land should not disturb the
 * file you were reading.
 *
 * A document leaves this strip and joins the table when it settles. That adds a
 * row; it does not reorder the ones already there, which is the property this
 * split exists to protect.
 *
 * Renders nothing when nothing is processing — an empty "Processing — 0" box is
 * a permanent reminder of a thing that is not happening.
 */
export function ProcessingStrip({ documents }: { documents: DocumentResponse[] }) {
  const inFlight = documents.filter((doc) => !isTerminalStatus(doc.status));
  if (inFlight.length === 0) return null;

  return (
    <section
      aria-labelledby="processing-heading"
      className="overflow-hidden rounded-md border border-border"
    >
      <h3
        id="processing-heading"
        className="border-b border-border bg-muted px-3 py-1.5 text-label uppercase text-muted-foreground"
      >
        Processing — {inFlight.length} of {documents.length}
      </h3>
      <ul>
        {inFlight.map((doc) => (
          <li
            key={doc.id}
            className="flex items-center gap-3 border-b border-border px-3 py-1.5 last:border-b-0"
          >
            <span className="min-w-0 flex-1 truncate text-sm text-foreground-2">
              {doc.standard_name || doc.original_filename}
            </span>
            <StatusToken meta={resolveStatus(DOCUMENT_STATUS, doc.status)} className="shrink-0" />
          </li>
        ))}
      </ul>
    </section>
  );
}
