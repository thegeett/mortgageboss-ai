"use client";

import { BoxOverlay } from "@/components/file/documents/reviewer/box-overlay";
import { PageCanvas } from "@/components/file/documents/reviewer/page-canvas";
import { ReviewerFields } from "@/components/file/documents/reviewer/reviewer-fields";
import { type PaneSplit, ReviewerShell } from "@/components/file/documents/reviewer/reviewer-shell";
import { useFieldSelection } from "@/components/file/documents/reviewer/use-field-selection";
import { StatusToken } from "@/components/status-token";
import { useDocumentDetail, useLoanFileDocuments } from "@/lib/api/documents";
import { useFieldBoxes } from "@/lib/api/field-boxes";
import { usePreferences, useUpdatePreferences } from "@/lib/api/preferences";
import { currentDocuments, extractionFields } from "@/lib/loan-files/documents";
import { DOCUMENT_STATUS, resolveStatus } from "@/lib/status";
import { cn } from "@/lib/utils";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";

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
            pageCount={null}
            onPageChange={setPage}
            overlay={
              <BoxOverlay
                boxes={boxes?.boxes ?? []}
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
          />
        }
      />
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
