"use client";

import { DocumentDrawer } from "@/components/file/documents/document-drawer";
import { DocumentDropzone } from "@/components/file/documents/document-dropzone";
import { DocumentList } from "@/components/file/documents/document-list";
import { useLoanFileDocuments } from "@/lib/api/documents";
import type { DocumentResponse } from "@/lib/types/document";
import { useParams } from "next/navigation";
import { useState } from "react";

/**
 * Documents tab (LP-43) — the document workspace, replacing the LP-33
 * placeholder. Drag-and-drop upload, documents grouped by category, and **live
 * status** via polling (the list refetches while any document is still
 * processing and stops once all are settled). Clicking a document opens a drawer
 * with its metadata, extraction, and download.
 */
export default function DocumentsPage() {
  const { id } = useParams<{ id: string }>();
  const { data: documents, isPending, isError } = useLoanFileDocuments(id);
  const [selected, setSelected] = useState<DocumentResponse | null>(null);

  return (
    <div className="space-y-6">
      <DocumentDropzone fileId={id} />
      <DocumentList
        documents={documents}
        isPending={isPending}
        isError={isError}
        onSelect={setSelected}
      />
      <DocumentDrawer document={selected} fileId={id} onClose={() => setSelected(null)} />
    </div>
  );
}
