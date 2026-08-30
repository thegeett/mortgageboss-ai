"use client";

import { StatusToken } from "@/components/status-token";
import { Skeleton } from "@/components/ui/skeleton";
import { useDocumentDetail } from "@/lib/api/documents";
import { extractionFields } from "@/lib/loan-files/documents";
import { DOCUMENT_STATUS, resolveStatus } from "@/lib/status";
import { cn } from "@/lib/utils";

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
export function ReviewerFields({
  documentId,
  selected,
  hovered,
  onSelect,
  onHover,
  hasBox,
  citationWrong,
  relocated,
}: {
  documentId: string | null;
  selected?: string | null;
  hovered?: string | null;
  onSelect?: (fieldKey: string) => void;
  onHover?: (fieldKey: string | null) => void;
  /** Whether this field's value could be located on the page at all. */
  hasBox?: (fieldKey: string) => boolean;
  /** The extraction cited a page the document does not have. */
  citationWrong?: (fieldKey: string) => boolean;
  /** The text was found on a page other than the one cited. */
  relocated?: (fieldKey: string) => boolean;
}) {
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
            <li
              key={field.key}
              className={cn(
                "field-row rounded-sm border-b border-border px-1 pb-2 last:border-b-0",
                field.key === selected && "bg-primary/10",
                field.key === hovered && field.key !== selected && "bg-muted",
              )}
            >
              {/* FOCUS A FIELD -> THE VIEWER GOES TO ITS BOX. The ticket calls
                  this the direction that actually saves time, so the whole row
                  is the control rather than a small affordance inside it. */}
              <button
                type="button"
                className="text-left text-xs text-muted-foreground"
                onClick={() => onSelect?.(field.key)}
                onFocus={() => onHover?.(field.key)}
                onBlur={() => onHover?.(null)}
                onMouseEnter={() => onHover?.(field.key)}
                onMouseLeave={() => onHover?.(null)}
              >
                {field.label}
              </button>
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

                <CitationNote
                  cited={Boolean(field.source?.snippet)}
                  citationWrong={citationWrong?.(field.key) ?? false}
                  relocated={relocated?.(field.key) ?? false}
                  located={hasBox ? hasBox(field.key) : true}
                />
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

/**
 * What the page can and cannot show for one field.
 *
 * Its own component because these three sentences are the honest part of the
 * feature and each of them is a claim about the extraction, not about the UI. A
 * citation naming a page the document does not have is shown as exactly that —
 * silently rendering a better page would turn a provenance trail into a guess.
 */
export function CitationNote({
  cited,
  citationWrong,
  relocated,
  located,
}: {
  /** The extraction quoted text for this field. Without one there is no claim to check. */
  cited: boolean;
  /** The cited page number is beyond the document's length. */
  citationWrong: boolean;
  /** The quoted text was found on a page other than the one cited. */
  relocated: boolean;
  /** The quoted text was located somewhere in the document. */
  located: boolean;
}) {
  // A field the extraction never filled has nothing to locate, and telling the
  // processor it could not be found reads as a lookup failure rather than an
  // empty field.
  if (!cited) return null;

  if (citationWrong) {
    return (
      <span className="mt-0.5 block text-xs text-warning">
        The extraction cited a page this document does not have
        {relocated ? " — the text is shown where it actually appears." : "."}
      </span>
    );
  }
  if (relocated) {
    return (
      <span className="mt-0.5 block text-xs text-warning">
        Found on a different page than the one cited.
      </span>
    );
  }
  // No box is ORDINARY — roughly a quarter of real fields. Saying so beats a
  // field that simply never highlights, leaving the processor wondering whether
  // the click registered.
  if (!located) {
    return (
      <span className="mt-0.5 block text-xs text-muted-foreground">
        Not locatable on the page — read the quoted text above.
      </span>
    );
  }
  return null;
}
