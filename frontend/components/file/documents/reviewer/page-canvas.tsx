"use client";

import {
  FIT,
  canZoomIn,
  canZoomOut,
  zoomIn,
  zoomLabel,
  zoomOut,
  zoomWidth,
} from "@/components/file/documents/reviewer/zoom";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { usePageImage } from "@/lib/api/page-image";
import { ChevronLeft, ChevronRight, Minus, Plus } from "lucide-react";
import { useState } from "react";

/**
 * One page of the document, rendered (LP-UI-030).
 *
 * The image comes from the server, rendered by the same PyMuPDF that will derive
 * a field's highlight rectangle in LP-UI-031 — one renderer, one coordinate
 * space. Two engines would be two spaces, and a box a few points off is worse
 * than no box, because it points confidently at the wrong words.
 *
 * THE NO-PAGE STATE IS NOT AN EDGE CASE. Measured over stored documents: 12 of
 * 105 PDFs are scans, and a model-cited page is out of range on ~4% of extracted
 * fields. So "there is no page image for this" is a designed state that a real
 * processor will meet, and it says which of those two it is rather than showing
 * a broken frame.
 */
export function PageCanvas({
  documentId,
  page,
  pageCount,
  onPageChange,
  zoom,
  onZoomChange,
  overlay,
}: {
  documentId: string | null;
  page: number;
  /** `null` when unknown — the control then only guards the lower bound. */
  pageCount: number | null;
  onPageChange: (page: number) => void;
  /** 1 is fit-to-column. See `zoom.ts` for why this is CSS and not a re-render. */
  zoom: number;
  onZoomChange: (zoom: number) => void;
  /** The highlight boxes, positioned against the image (LP-UI-031). */
  overlay?: React.ReactNode;
}) {
  const { data, isPending, isError } = usePageImage(documentId, page);
  // An image that fails to DECODE is a different failure from one that fails to
  // fetch, and only the fetch had a state. A dead object url, a truncated render
  // — either drew the browser's broken-image icon, which tells a processor
  // nothing. This turns any of them into the same honest sentence.
  //
  // The state holds WHICH image failed rather than a boolean, so a new page is
  // unaffected by the previous page's failure without an effect to reset it. A
  // reset effect would be a second source of truth that can lag a render.
  const [failed, setFailed] = useState<string | null>(null);
  const identity = `${documentId}:${page}`;
  const imageBroken = failed === identity;

  if (!documentId) {
    return <Empty>Choose a document on the left to read it here.</Empty>;
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center justify-center gap-2 border-b border-border bg-background px-3 py-1.5">
        <Button
          size="icon"
          variant="ghost"
          className="h-7 w-7"
          aria-label="Previous page"
          disabled={page <= 1}
          onClick={() => onPageChange(page - 1)}
        >
          <ChevronLeft className="h-4 w-4" />
        </Button>
        <span className="tabular text-xs text-muted-foreground">
          Page {page}
          {pageCount ? ` of ${pageCount}` : ""}
        </span>
        <Button
          size="icon"
          variant="ghost"
          className="h-7 w-7"
          aria-label="Next page"
          disabled={pageCount !== null && page >= pageCount}
          onClick={() => onPageChange(page + 1)}
        >
          <ChevronRight className="h-4 w-4" />
        </Button>

        {/* The zoom, to the right of the pager and separated from it: they move
            different things, and a processor reaching for one must not find the
            other. */}
        <span aria-hidden className="mx-1 h-4 w-px bg-border" />
        <Button
          size="icon"
          variant="ghost"
          className="h-7 w-7"
          aria-label="Zoom out"
          disabled={!canZoomOut(zoom)}
          onClick={() => onZoomChange(zoomOut(zoom))}
        >
          <Minus className="h-4 w-4" />
        </Button>
        {/* The readout is the reset. A separate "fit" button would be a third
            control for a job this one can do, and its label already says what
            pressing it undoes. */}
        <Button
          variant="ghost"
          size="sm"
          className="h-7 min-w-[3.25rem] px-1.5 tabular text-xs text-muted-foreground"
          aria-label={`Zoom is ${zoomLabel(zoom)}. Reset to fit the column.`}
          disabled={zoom === FIT}
          onClick={() => onZoomChange(FIT)}
        >
          {zoomLabel(zoom)}
        </Button>
        <Button
          size="icon"
          variant="ghost"
          className="h-7 w-7"
          aria-label="Zoom in"
          disabled={!canZoomIn(zoom)}
          onClick={() => onZoomChange(zoomIn(zoom))}
        >
          <Plus className="h-4 w-4" />
        </Button>
      </div>

      <div className="min-h-0 flex-1 overflow-auto p-3">
        {isPending ? (
          <div aria-busy>
            <output className="sr-only">Loading page {page}</output>
            <Skeleton className="mx-auto h-[60vh] w-full max-w-[46rem]" />
          </div>
        ) : isError || !data || imageBroken ? (
          <Empty>
            No page image for this document. It may be a scan with no text layer, a file that is not
            a PDF, or a page the document does not have — the extracted fields are still on the
            right, with the text each value was read from.
          </Empty>
        ) : (
          // `alt` is deliberately not the page's content: it is an image of a
          // borrower's document, and describing it would mean transcribing PII
          // into the accessibility tree. The fields panel is the readable form.
          // `relative` so the overlay's normalised percentages resolve against
          // the IMAGE's box rather than the scroll container's — the boxes are
          // 0..1 of the page, and any other positioning parent puts them
          // somewhere confidently wrong.
          // `mx-auto` centres it while it fits and lets it overflow into the
          // parent's scroller once zoomed past the pane.
          <div className="relative mx-auto" style={{ width: zoomWidth(zoom) }}>
            <img
              src={data.url}
              onError={() => setFailed(identity)}
              alt={`Page ${page} of the document`}
              width={data.widthPoints * data.zoom}
              height={data.heightPoints * data.zoom}
              className="h-auto w-full rounded border border-border bg-background shadow-sm"
            />
            {overlay}
          </div>
        )}
      </div>
    </div>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-full items-center justify-center p-6">
      <p className="max-w-prose text-center text-sm text-muted-foreground">{children}</p>
    </div>
  );
}
