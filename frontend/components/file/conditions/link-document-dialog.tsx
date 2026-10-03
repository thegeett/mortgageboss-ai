"use client";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { useLinkCandidates, useLinkItemDocument } from "@/lib/api/conditions";
import { getErrorMessage } from "@/lib/errors/api-error";
import type { Condition, ConditionItem, LinkCandidate } from "@/lib/types/conditions";
import { cn } from "@/lib/utils";
import Link from "next/link";
import { useEffect, useId, useState } from "react";

/** `2026-07-15T…` → `07/15`, the app's short form. */
function uploaded(iso: string): string {
  const when = new Date(iso);
  if (Number.isNaN(when.getTime())) return "";
  return `${`${when.getMonth() + 1}`.padStart(2, "0")}/${`${when.getDate()}`.padStart(2, "0")}`;
}

/**
 * LP-958 — "Link a document to 0006" (item 9, the mockup the owner approved 2026-10-03). It replaces
 * LP-953's inline select, which squeezed a picker into the item's narrow right-hand column.
 *
 * THE GROUPS ARE THE SERVER'S. "Matches this item" is `matches` from the link-candidates endpoint, the
 * same rule that links a document by itself (type, the library's words, her unlinks), so the dialog
 * cannot call a document a match that the plan would not. Everything else is "Other documents", and
 * linking one is allowed: the server links it and its "Right document type" check fails, so the item
 * stays open until she accepts it anyway. The warning says that before she clicks.
 *
 * With `replaceDocumentId` this is "Change": the old document is not offered, and the server swaps the
 * link in one step.
 */
export function LinkDocumentDialog({
  open,
  onOpenChange,
  fileId,
  condition,
  item,
  replaceDocumentId,
  onDone,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  fileId: string;
  condition: Condition;
  item: ConditionItem;
  replaceDocumentId?: string;
  onDone?: () => void;
}) {
  const candidates = useLinkCandidates(condition.id, item.id, open);
  const link = useLinkItemDocument(fileId);
  const [query, setQuery] = useState("");
  const [chosen, setChosen] = useState<string | null>(null);
  const [page, setPage] = useState("");
  const [error, setError] = useState<string | null>(null);
  const searchId = useId();
  const pageId = useId();

  useEffect(() => {
    if (!open) {
      setQuery("");
      setChosen(null);
      setPage("");
      setError(null);
    }
  }, [open]);

  const needle = query.trim().toLowerCase();
  const offered = (candidates.data ?? []).filter(
    (doc) =>
      doc.document_id !== replaceDocumentId &&
      !doc.linked &&
      (!needle || `${doc.name} ${doc.type_label}`.toLowerCase().includes(needle)),
  );
  const matching = offered.filter((doc) => doc.matches);
  const others = offered.filter((doc) => !doc.matches);
  const picked = offered.find((doc) => doc.document_id === chosen) ?? null;
  const code = condition.lender_code ?? "this condition";

  const submit = () => {
    if (!picked) return;
    setError(null);
    link.mutate(
      {
        conditionId: condition.id,
        itemId: item.id,
        document_id: picked.document_id,
        page: page ? Number(page) : null,
        replace_document_id: replaceDocumentId ?? null,
      },
      {
        onError: (err) => setError(getErrorMessage(err)),
        onSuccess: () => {
          onOpenChange(false);
          onDone?.();
        },
      },
    );
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[85vh] flex-col sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>
            {replaceDocumentId ? `Change the document for ${code}` : `Link a document to ${code}`}
          </DialogTitle>
          <DialogDescription>{item.name}</DialogDescription>
        </DialogHeader>

        <div className="flex min-h-0 flex-col gap-3 overflow-y-auto">
          <label htmlFor={searchId} className="flex flex-col gap-1 text-xs text-muted-foreground">
            Search this file’s documents
            <input
              id={searchId}
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              className="h-9 rounded-md border border-input bg-background px-2.5 text-sm text-foreground"
            />
          </label>

          {candidates.isPending ? (
            <div className="flex flex-col gap-2" aria-busy>
              <Skeleton className="h-12 w-full" />
              <Skeleton className="h-12 w-full" />
            </div>
          ) : candidates.isError ? (
            <p className="text-sm text-destructive">
              The file’s documents couldn’t be loaded. {getErrorMessage(candidates.error)}
            </p>
          ) : offered.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              {needle
                ? "No document on this file matches that search."
                : "There is no other document on this file to link. Upload it instead."}
            </p>
          ) : (
            <div
              role="radiogroup"
              aria-label="Documents on this file"
              className="flex flex-col gap-2"
            >
              {matching.length > 0 ? (
                <CandidateGroup
                  heading="Matches this item"
                  primary
                  docs={matching}
                  fileId={fileId}
                  chosen={chosen}
                  onChoose={setChosen}
                />
              ) : null}
              {others.length > 0 ? (
                <CandidateGroup
                  heading={matching.length > 0 ? "Other documents" : "Documents on this file"}
                  docs={others}
                  fileId={fileId}
                  chosen={chosen}
                  onChoose={setChosen}
                />
              ) : null}
            </div>
          )}

          <div className="flex items-end gap-3">
            <label htmlFor={pageId} className="flex flex-col gap-1 text-xs text-muted-foreground">
              Page (optional)
              <input
                id={pageId}
                type="number"
                min={1}
                value={page}
                onChange={(event) => setPage(event.target.value)}
                className="h-9 w-24 rounded-md border border-input bg-background px-2.5 text-sm text-foreground"
              />
            </label>
            <p className="pb-2 text-xs text-muted-foreground">
              Its checks run as soon as it is linked.
            </p>
          </div>

          {picked && !picked.matches ? (
            <p className="rounded-md border border-warning/40 bg-warning/10 p-2.5 text-sm text-foreground-2">
              {picked.unlinked_by_her
                ? "You unlinked this document from this item before. "
                : `${picked.name} does not look like what this item asks for. `}
              It will be linked, but this item stays open until you accept it anyway, with a reason.
            </p>
          ) : null}
          {error ? <p className="text-sm text-destructive">{error}</p> : null}
        </div>

        <DialogFooter>
          <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button type="button" disabled={!picked || link.isPending} onClick={submit}>
            {replaceDocumentId ? "Use this document" : "Link document"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function CandidateGroup({
  heading,
  primary = false,
  docs,
  fileId,
  chosen,
  onChoose,
}: {
  heading: string;
  primary?: boolean;
  docs: LinkCandidate[];
  fileId: string;
  chosen: string | null;
  onChoose: (documentId: string) => void;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <p
        className={cn(
          "text-xs font-semibold uppercase tracking-wide",
          primary ? "text-primary" : "text-muted-foreground",
        )}
      >
        {heading}
      </p>
      {docs.map((doc) => {
        const selected = chosen === doc.document_id;
        return (
          <div
            key={doc.document_id}
            className={cn(
              "flex items-start gap-2.5 rounded-md border p-2.5",
              selected ? "border-primary bg-primary/5" : "border-input",
            )}
          >
            <label className="flex min-w-0 flex-1 cursor-pointer items-start gap-2.5">
              <input
                type="radio"
                name="link-document"
                className="mt-1"
                checked={selected}
                onChange={() => onChoose(doc.document_id)}
              />
              <span className="flex min-w-0 flex-col gap-0.5">
                <span className="truncate text-sm font-medium text-foreground">{doc.name}</span>
                <span className="text-xs text-muted-foreground">
                  {[doc.type_label, `Uploaded ${uploaded(doc.created_at)}`]
                    .filter(Boolean)
                    .join(" · ")}
                  {doc.unlinked_by_her ? " · you unlinked it from this item" : ""}
                </span>
              </span>
            </label>
            <Link
              href={`/loan-files/${fileId}/documents?doc=${doc.document_id}`}
              target="_blank"
              className="shrink-0 text-sm text-primary hover:underline"
            >
              Open
            </Link>
          </div>
        );
      })}
    </div>
  );
}
