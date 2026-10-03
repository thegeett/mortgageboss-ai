"use client";

import { Button } from "@/components/ui/button";
import { useLinkItemDocument, useUploadToItem } from "@/lib/api/conditions";
import { useLoanFileDocuments } from "@/lib/api/documents";
import { getErrorMessage } from "@/lib/errors/api-error";
import type { Condition, ConditionItem } from "@/lib/types/conditions";
import { Link2, Upload } from "lucide-react";
import { useId, useRef, useState } from "react";

/**
 * LP-953 — her own links on one item: "Link a document" (a document already on the file, and a page)
 * and "Upload here" (a new upload, linked to this item as it is created). With `replaceDocumentId` the
 * picker is "Change": the old link is removed and the new one made in one step.
 *
 * The server decides everything that matters: another file's document is refused, a document of the
 * wrong type is linked but fails "Right document type" (so the item is not done until she accepts it
 * anyway), and her checks run once the document has been read. This only sends her choice and shows
 * the sentence when it is refused.
 */
export function ItemLinkActions({
  fileId,
  condition,
  item,
  replaceDocumentId,
  onDone,
}: {
  fileId: string;
  condition: Condition;
  item: ConditionItem;
  replaceDocumentId?: string;
  onDone?: () => void;
}) {
  const [picking, setPicking] = useState(Boolean(replaceDocumentId));
  const [documentId, setDocumentId] = useState("");
  const [page, setPage] = useState("");
  const [error, setError] = useState<string | null>(null);
  const link = useLinkItemDocument(fileId);
  const upload = useUploadToItem(fileId);
  const documents = useLoanFileDocuments(fileId, { enabled: picking });
  const fileInput = useRef<HTMLInputElement>(null);
  const pickerId = useId();

  const choices = (documents.data ?? []).filter((doc) => doc.id !== replaceDocumentId);
  const pending = link.isPending || upload.isPending;

  return (
    <div className="flex flex-col gap-1.5">
      {!replaceDocumentId ? (
        <div className="flex flex-wrap gap-1.5">
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={pending}
            onClick={() => setPicking((open) => !open)}
          >
            <Link2 className="h-3.5 w-3.5" aria-hidden />
            Link a document
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={pending}
            onClick={() => fileInput.current?.click()}
          >
            <Upload className="h-3.5 w-3.5" aria-hidden />
            Upload here
          </Button>
          <input
            ref={fileInput}
            type="file"
            aria-label={`Upload a document for ${item.name}`}
            className="hidden"
            onChange={(event) => {
              const files = Array.from(event.target.files ?? []);
              event.target.value = "";
              if (files.length === 0) return;
              setError(null);
              upload.mutate(
                { conditionId: condition.id, itemId: item.id, files },
                { onError: (err) => setError(getErrorMessage(err)), onSuccess: () => onDone?.() },
              );
            }}
          />
        </div>
      ) : null}

      {picking ? (
        <div className="flex flex-wrap items-end gap-2 rounded-md border border-input bg-background p-2">
          <label htmlFor={pickerId} className="flex min-w-[12rem] flex-1 flex-col gap-0.5 text-xs">
            {replaceDocumentId ? "Change to" : "Document on this file"}
            <select
              id={pickerId}
              value={documentId}
              onChange={(event) => setDocumentId(event.target.value)}
              className="h-8 rounded-md border border-input bg-background px-2 text-sm"
            >
              <option value="">Choose a document…</option>
              {choices.map((doc) => (
                <option key={doc.id} value={doc.id}>
                  {doc.standard_name || doc.original_filename}
                </option>
              ))}
            </select>
          </label>
          <label className="flex w-20 flex-col gap-0.5 text-xs">
            Page
            <input
              type="number"
              min={1}
              value={page}
              onChange={(event) => setPage(event.target.value)}
              className="h-8 rounded-md border border-input bg-background px-2 text-sm"
            />
          </label>
          <Button
            type="button"
            size="sm"
            disabled={!documentId || pending}
            onClick={() => {
              setError(null);
              link.mutate(
                {
                  conditionId: condition.id,
                  itemId: item.id,
                  document_id: documentId,
                  page: page ? Number(page) : null,
                  replace_document_id: replaceDocumentId ?? null,
                },
                {
                  onError: (err) => setError(getErrorMessage(err)),
                  onSuccess: () => {
                    setPicking(false);
                    setDocumentId("");
                    setPage("");
                    onDone?.();
                  },
                },
              );
            }}
          >
            {replaceDocumentId ? "Use this document" : "Link"}
          </Button>
        </div>
      ) : null}
      {error ? <p className="text-xs text-destructive">{error}</p> : null}
    </div>
  );
}
