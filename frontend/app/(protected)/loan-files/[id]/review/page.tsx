"use client";

import { BoxOverlay } from "@/components/file/documents/reviewer/box-overlay";
import { PageCanvas } from "@/components/file/documents/reviewer/page-canvas";
import {
  buildQueue,
  isFullyReviewed,
  nextAttention,
} from "@/components/file/documents/reviewer/review-queue";
import { ReviewerFields } from "@/components/file/documents/reviewer/reviewer-fields";
import { type PaneSplit, ReviewerShell } from "@/components/file/documents/reviewer/reviewer-shell";
import { ShortcutSheet } from "@/components/file/documents/reviewer/shortcut-sheet";
import { useFieldSelection } from "@/components/file/documents/reviewer/use-field-selection";
import {
  shortcutsEnabled,
  useReviewKeys,
} from "@/components/file/documents/reviewer/use-review-keys";
import {
  FIT,
  zoomIn as stepIn,
  zoomOut as stepOut,
} from "@/components/file/documents/reviewer/zoom";
import { StatusToken } from "@/components/status-token";
import { useDocumentDetail, useLoanFileDocuments } from "@/lib/api/documents";
import { useFieldBoxes } from "@/lib/api/field-boxes";
import { useRecordFieldReview } from "@/lib/api/field-reviews";
import { usePageImage } from "@/lib/api/page-image";
import { usePreferences, useUpdatePreferences } from "@/lib/api/preferences";
import { currentDocuments, extractionFields } from "@/lib/loan-files/documents";
import { DOCUMENT_STATUS, resolveStatus } from "@/lib/status";
import { cn } from "@/lib/utils";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";

/**
 * The document reviewer (LP-UI-030) — list, page, fields.
 *
 * A separate route rather than a mode on the Documents tab: this is a different
 * job (reading one document closely) from the one that tab does (seeing what is
 * on the file), and it wants the whole width.
 *
 * The drawer stays exactly as it was. A processor who opens a document from the
 * Documents list still gets it, and it remains the fallback for anything with no
 * page image — which measurement says is common rather than rare.
 */
export default function ReviewPage() {
  return (
    <Suspense fallback={null}>
      <Reviewer />
    </Suspense>
  );
}

function Reviewer() {
  const { id } = useParams<{ id: string }>();
  const params = useSearchParams();
  const { data: documents } = useLoanFileDocuments(id);
  const { data: preferences } = usePreferences();
  const updatePreferences = useUpdatePreferences();

  const current = currentDocuments(documents ?? []);
  const [selected, setSelected] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const field = useFieldSelection();
  // Alt reveals every other candidate box at once. Held, not toggled: it is a
  // peek at what else the extraction found, not a mode to be left switched on.
  const showAll = useAltHeld();

  // `?doc=` opens straight into one document — the same parameter the Documents
  // tab uses for its drawer (LP-114), so a link keeps working whichever surface
  // it was written for.
  const requested = params.get("doc");
  const documentId = selected ?? requested ?? current[0]?.id ?? null;

  const split: PaneSplit | null = preferences?.reviewer_pane_split ?? null;

  const { data: pageImage } = usePageImage(documentId, page);
  const { data: boxes } = useFieldBoxes(documentId);
  const { data: detail } = useDocumentDetail(documentId);

  const byField = useMemo(() => {
    const map = new Map<string, { page: number }>();
    for (const box of boxes?.boxes ?? []) if (!map.has(box.field_key)) map.set(box.field_key, box);
    return map;
  }, [boxes]);

  const labels = useMemo(() => {
    const map = new Map<string, string>();
    for (const f of extractionFields(detail?.current_extraction?.extracted_data ?? {}))
      map.set(f.key, f.label);
    return map;
  }, [detail]);

  // FOCUS A FIELD -> THE PAGE FOLLOWS. The page number is the whole navigation
  // here: the overlay only draws boxes belonging to the page on screen, so
  // moving the page IS scrolling to the box.
  useEffect(() => {
    if (!field.selected) return;
    const box = byField.get(field.selected);
    if (box && box.page !== page) setPage(box.page);
  }, [field.selected, byField, page]);

  const fabricated = new Set(boxes?.fabricated_pages ?? []);
  const relocated = new Set(boxes?.relocated ?? []);

  // --- The keyboard loop (LP-UI-033) -------------------------------------- //

  const scrutiny = detail?.field_scrutiny ?? {};
  const queue = useMemo(
    () =>
      buildQueue(
        extractionFields(detail?.current_extraction?.extracted_data ?? {}),
        detail?.field_scrutiny ?? {},
      ),
    [detail],
  );

  const recordReview = useRecordFieldReview(documentId);
  const [helpOpen, setHelpOpen] = useState(false);
  const [showBoxes, setShowBoxes] = useState(true);
  // Zoom persists across pages and documents for the session: a processor who
  // zoomed in to read small print is still reading small print on the next page.
  const [zoom, setZoom] = useState<number>(FIT);
  const [editing, setEditing] = useState<string | null>(null);

  const documentIndex = current.findIndex((doc) => doc.id === documentId);
  const goToDocument = useCallback(
    (step: 1 | -1) => {
      if (documentIndex === -1 || current.length === 0) return;
      const next = current[(documentIndex + step + current.length) % current.length];
      if (!next) return;
      setSelected(next.id);
      setPage(1);
      field.select(null);
      setEditing(null);
    },
    [current, documentIndex, field],
  );

  const move = useCallback(
    (direction: 1 | -1) => field.select(nextAttention(queue, field.selected, direction)),
    [queue, field],
  );

  // ACCEPT WITHOUT A SELECTED FIELD DOES NOTHING. Enter is one keystroke from
  // every other action, and "accept whichever field is first" would silently
  // vouch for a value the processor never looked at.
  const accept = useCallback(() => {
    if (!field.selected) return;
    recordReview.mutate({ fieldKey: field.selected, verdict: "accepted" });
  }, [field.selected, recordReview]);

  useReviewKeys(
    {
      nextField: () => move(1),
      previousField: () => move(-1),
      accept,
      acceptAndAdvance: () => {
        accept();
        move(1);
      },
      edit: () => field.selected && setEditing(field.selected),
      // A rejection needs a reason, so `R` opens the editor on the reject tab
      // rather than recording a bare verdict the API would refuse anyway.
      reject: () => field.selected && setEditing(field.selected),
      toggleOverlay: () => setShowBoxes((on) => !on),
      zoomIn: () => setZoom(stepIn),
      zoomOut: () => setZoom(stepOut),
      zoomReset: () => setZoom(FIT),
      previousDocument: () => goToDocument(-1),
      nextDocument: () => goToDocument(1),
      markReviewed: () => isFullyReviewed(queue) && goToDocument(1),
      toggleHelp: () => setHelpOpen((open) => !open),
    },
    // The sheet and the verdict editor each own the keyboard while they are open;
    // leaving the global listener live behind either one acts on keys aimed at it.
    shortcutsEnabled({ helpOpen, editing }),
  );

  return (
    <div className="h-[calc(100vh-var(--topbar-h)-1px)]">
      <ReviewerShell
        split={split}
        onSplitChange={(next) => updatePreferences.mutate({ reviewer_pane_split: next })}
        list={
          <ul className="p-2">
            {current.length === 0 ? (
              <li className="p-2 text-sm text-muted-foreground">No documents on this file yet.</li>
            ) : null}
            {current.map((doc) => (
              <li key={doc.id}>
                <button
                  type="button"
                  onClick={() => {
                    setSelected(doc.id);
                    setPage(1);
                    field.select(null);
                  }}
                  aria-current={doc.id === documentId ? "true" : undefined}
                  className={cn(
                    "w-full rounded-md px-2 py-1.5 text-left text-sm transition-colors",
                    doc.id === documentId
                      ? "bg-primary/10 font-medium text-primary"
                      : "text-foreground-2 hover:bg-muted",
                  )}
                >
                  <span className="block truncate">
                    {doc.standard_name || doc.original_filename}
                  </span>
                  <StatusToken
                    meta={resolveStatus(DOCUMENT_STATUS, doc.status)}
                    variant="dot"
                    className="mt-0.5"
                  />
                </button>
              </li>
            ))}
            <li className="mt-2 border-t border-border pt-2">
              <Link
                href={`/loan-files/${id}/documents`}
                className="block px-2 text-xs text-muted-foreground hover:text-primary hover:underline"
              >
                Back to all documents
              </Link>
            </li>
          </ul>
        }
        canvas={
          <PageCanvas
            documentId={documentId}
            page={page}
            // From the page endpoint, which counts while it already has the
            // document open. Until page 1 arrives it is null and the control
            // guards only the lower bound.
            pageCount={pageImage?.pageCount ?? null}
            onPageChange={setPage}
            zoom={zoom}
            onZoomChange={setZoom}
            overlay={
              <BoxOverlay
                // Space hides every box. Passing an empty list rather than a
                // `hidden` flag keeps the overlay with one job: draw what it is
                // given.
                boxes={showBoxes ? (boxes?.boxes ?? []) : []}
                page={page}
                selected={field.selected}
                hovered={field.hovered}
                showAll={showAll}
                // CLICK A VALUE ON THE PAGE -> GO TO ITS FIELD. Never write it
                // into whichever field happened to be selected; see the hook.
                onSelect={(key) => field.clickBox(key)}
                onHover={field.hover}
                labelFor={(key) => labels.get(key) ?? key}
              />
            }
          />
        }
        fields={
          <ReviewerFields
            documentId={documentId}
            selected={field.selected}
            hovered={field.hovered}
            onSelect={field.select}
            onHover={field.hover}
            hasBox={(key) => byField.has(key)}
            citationWrong={(key) => fabricated.has(key)}
            relocated={(key) => relocated.has(key)}
            editing={editing}
            busy={recordReview.isPending}
            onCancelEdit={() => setEditing(null)}
            onCorrect={(fieldKey, value) => {
              recordReview.mutate({ fieldKey, verdict: "corrected", correctedValue: value });
              setEditing(null);
            }}
            onReject={(fieldKey, reason) => {
              recordReview.mutate({ fieldKey, verdict: "rejected", note: reason });
              setEditing(null);
            }}
          />
        }
      />
      <ShortcutSheet open={helpOpen} onClose={() => setHelpOpen(false)} />
    </div>
  );
}

/**
 * Whether Alt is held right now.
 *
 * `blur` matters as much as `keyup`: alt-tabbing away is the ordinary way to
 * leave this page, and the keyup then lands in another window, leaving every box
 * drawn until the next Alt press.
 */
function useAltHeld(): boolean {
  const [held, setHeld] = useState(false);
  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      if (e.altKey) setHeld(true);
    };
    const up = (e: KeyboardEvent) => {
      if (!e.altKey) setHeld(false);
    };
    const clear = () => setHeld(false);
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    window.addEventListener("blur", clear);
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
      window.removeEventListener("blur", clear);
    };
  }, []);
  return held;
}
