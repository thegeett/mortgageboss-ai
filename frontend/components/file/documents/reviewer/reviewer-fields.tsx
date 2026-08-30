"use client";

import { StatusToken } from "@/components/status-token";
import { Skeleton } from "@/components/ui/skeleton";
import { useDocumentDetail } from "@/lib/api/documents";
import { extractionFields } from "@/lib/loan-files/documents";
import { DOCUMENT_STATUS, resolveStatus } from "@/lib/status";

/**
 * The extracted fields, beside the page they came from (LP-UI-030).
 *
 * Rows reflow to the PANE's width via a container query (`.field-pane` in
 * globals.css), not the window's — a processor drags this from 320px to 720px
 * without the window changing, so a media query would lay out for a viewport the
 * pane no longer fills.
 *
 * Each field shows the text the extraction actually read. That is the whole
 * value of this panel when there is no page image to point at, which measurement
 * says is the case for roughly a quarter of fields.
 */
export function ReviewerFields({ documentId }: { documentId: string | null }) {
  const { data, isPending, isError } = useDocumentDetail(documentId);

  if (!documentId) {
    return <Note>No document selected.</Note>;
  }
  if (isPending) {
    return (
      <div className="space-y-2 p-3" aria-busy>
        <output className="sr-only">Loading the extracted fields</output>
        <Skeleton className="h-5 w-2/3" />
        <Skeleton className="h-5 w-1/2" />
        <Skeleton className="h-5 w-3/4" />
      </div>
    );
  }
  if (isError || !data) {
    return <Note>Couldn&rsquo;t load this document&rsquo;s fields.</Note>;
  }

  const fields = extractionFields(data.current_extraction?.extracted_data ?? {});

  return (
    <div className="field-pane p-3">
      <header className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 pb-2">
        <h3 className="text-label uppercase text-muted-foreground">Extracted fields</h3>
        <StatusToken meta={resolveStatus(DOCUMENT_STATUS, data.status)} className="text-xs" />
      </header>

      {fields.length === 0 ? (
        <Note>
          Nothing has been extracted from this document yet. That is not the same as a document with
          no values — an extraction may still be running, or this type may be recorded rather than
          read.
        </Note>
      ) : (
        <ul className="space-y-2">
          {fields.map((field) => (
            <li key={field.key} className="field-row border-b border-border pb-2 last:border-b-0">
              <span className="text-xs text-muted-foreground">{field.label}</span>
              <span className="min-w-0">
                <span className="block break-words text-sm font-medium text-foreground">
                  {field.value ?? "—"}
                </span>
                {/* The text the value was read from. On a document with no page
                    image this is the only provenance a processor has, so it is
                    shown rather than hidden behind a hover. */}
                {field.source?.snippet ? (
                  <span className="mt-0.5 block break-words text-xs text-muted-foreground">
                    &ldquo;{field.source.snippet}&rdquo;
                    {field.source.page ? ` · p.${field.source.page}` : ""}
                  </span>
                ) : null}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Note({ children }: { children: React.ReactNode }) {
  return <p className="max-w-prose p-3 text-sm text-muted-foreground">{children}</p>;
}
