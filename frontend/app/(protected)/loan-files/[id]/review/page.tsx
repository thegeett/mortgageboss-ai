"use client";

import { PageCanvas } from "@/components/file/documents/reviewer/page-canvas";
import { ReviewerFields } from "@/components/file/documents/reviewer/reviewer-fields";
import { type PaneSplit, ReviewerShell } from "@/components/file/documents/reviewer/reviewer-shell";
import { StatusToken } from "@/components/status-token";
import { useLoanFileDocuments } from "@/lib/api/documents";
import { usePreferences, useUpdatePreferences } from "@/lib/api/preferences";
import { currentDocuments } from "@/lib/loan-files/documents";
import { DOCUMENT_STATUS, resolveStatus } from "@/lib/status";
import { cn } from "@/lib/utils";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

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

  // `?doc=` opens straight into one document — the same parameter the Documents
  // tab uses for its drawer (LP-114), so a link keeps working whichever surface
  // it was written for.
  const requested = params.get("doc");
  const documentId = selected ?? requested ?? current[0]?.id ?? null;

  const split: PaneSplit | null = preferences?.reviewer_pane_split ?? null;

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
          <PageCanvas documentId={documentId} page={page} pageCount={null} onPageChange={setPage} />
        }
        fields={<ReviewerFields documentId={documentId} />}
      />
    </div>
  );
}
