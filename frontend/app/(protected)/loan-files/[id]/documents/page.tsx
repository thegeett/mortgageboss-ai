"use client";

import { DocumentDrawer } from "@/components/file/documents/document-drawer";
import { DocumentDropzone } from "@/components/file/documents/document-dropzone";
import { DocumentList } from "@/components/file/documents/document-list";
import { ProcessingStrip } from "@/components/file/documents/processing-strip";
import { useLoanFileDocuments } from "@/lib/api/documents";
import type { DocumentResponse } from "@/lib/types/document";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

/**
 * Documents tab (LP-43) — the document workspace, replacing the LP-33
 * placeholder. Drag-and-drop upload, documents grouped by category, and **live
 * status** via polling (the list refetches while any document is still
 * processing and stops once all are settled). Clicking a document opens a drawer
 * with its metadata, extraction, and download.
 *
 * LP-114: a ``?doc=<id>`` query param deep-opens that document's drawer — the
 * lightweight cross-tab nav a finding's source-document link uses to bring the
 * processor from a finding straight to the document that grounds it.
 */
export default function DocumentsPage() {
  // useSearchParams needs a Suspense boundary (Next 15 App Router).
  return (
    <Suspense fallback={null}>
      <DocumentsWorkspace />
    </Suspense>
  );
}

function DocumentsWorkspace() {
  const { id } = useParams<{ id: string }>();
  const { data: documents, isPending, isError, refetch } = useLoanFileDocuments(id);
  const [selected, setSelected] = useState<DocumentResponse | null>(null);

  // LP-114: honor ?doc=<id> — open that document once it's loaded, then strip the param so the
  // drawer can be closed (and a refetch doesn't reopen it).
  const searchParams = useSearchParams();
  const router = useRouter();
  const docParam = searchParams.get("doc");
  useEffect(() => {
    if (!docParam || !documents) return;
    const match = documents.find((doc) => doc.id === docParam);
    if (match) {
      setSelected(match);
      router.replace(`/loan-files/${id}/documents`, { scroll: false });
    }
  }, [docParam, documents, id, router]);

  return (
    <div className="space-y-6">
      {/* The way into the reviewer (LP-UI-030). Without an entry point the route
          is reachable only by typing a URL, which is the LP-UI-016 rule facing
          the other way: a screen nobody can get to is not shipped. */}
      <div className="flex justify-end">
        <Link
          href={`/loan-files/${id}/review`}
          className="text-sm text-muted-foreground hover:text-primary hover:underline"
        >
          Open the document reviewer
        </Link>
      </div>

      <DocumentDropzone fileId={id} />
      {/* Above the list on purpose (LP-UI-019): watching uploads land must not
          move the documents already settled underneath them. */}
      <ProcessingStrip documents={documents ?? []} />
      <DocumentList
        documents={documents}
        isPending={isPending}
        isError={isError}
        onRetry={() => void refetch()}
        onSelect={setSelected}
      />
      <DocumentDrawer document={selected} fileId={id} onClose={() => setSelected(null)} />
    </div>
  );
}
