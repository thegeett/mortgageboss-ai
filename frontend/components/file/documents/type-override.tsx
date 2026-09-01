"use client";

import { Button } from "@/components/ui/button";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { Spinner } from "@/components/ui/spinner";
import { useDocumentTypes, useOverrideDocumentType } from "@/lib/api/documents";
import { getErrorMessage } from "@/lib/errors/api-error";
import { humanize } from "@/lib/format";
import type { DocumentResponse } from "@/lib/types/document";
import { PencilLine } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";
import { ReprocessDocumentButton } from "./reprocess-document";

/**
 * Manual document-type override (LP-44) — the human-correction half of the loop.
 * When the AI is unsure (`needs_review`) or simply wrong, the processor sets the
 * authoritative type here; saving PATCHes the document and the server re-runs
 * extraction for the corrected type (relabel-only for types we don't extract).
 */
export function TypeOverride({
  summary,
  fileId,
  onPickerOpenChange,
}: {
  summary: DocumentResponse;
  fileId: string;
  onPickerOpenChange: (open: boolean) => void;
}) {
  const override = useOverrideDocumentType(fileId, summary.id);
  const [selected, setSelected] = useState(summary.document_type ?? "");
  const needsReview = summary.status === "needs_review";
  const { data: catalog, isPending: typesPending, isError: typesFailed } = useDocumentTypes();

  // LP-638 — THE CATALOG, not a hardcoded list. The eight options this replaces were written when
  // the catalog had three document types; it has 164, so a processor could not correct a document
  // to `closing_disclosure` at all — which is exactly what LF-ZE9N's stuck document needed.
  //
  // The current type is kept selectable even if the catalog no longer lists it, so a document
  // carrying a retired slug still shows what it is rather than reading as blank.
  const options = useMemo(() => {
    const fromCatalog = (catalog ?? []).map((type) => ({
      value: type.value,
      label: type.label,
      group: humanize(type.category),
    }));
    const current = summary.document_type;
    if (current && !fromCatalog.some((o) => o.value === current)) {
      return [{ value: current, label: humanize(current), group: "Current" }, ...fromCatalog];
    }
    return fromCatalog;
  }, [catalog, summary.document_type]);

  const changed = selected !== "" && selected !== summary.document_type;
  // LP-638 REVIEW — CONFIRMING IS AN ACTION, and the ticket closed without it. The report was
  // "there is no way to confirm in drawer, there is no field to update and say it is this type".
  // The picker fixed the second half; this is the first. A `needs_review` document whose AI type is
  // already RIGHT is the common case — the banner directly above says "confirm or correct the type
  // below" — and Apply was disabled precisely then, because the selection equalled the current
  // type. There was still no way to confirm.
  //
  // The PATCH is the confirm: it sets `classification_confidence = 1.0` and clears the review
  // state, which is what takes the document out of the queue.
  //
  // Gated on the type being a REAL catalog entry, which also closes the other half: the retired-slug
  // fallback option below keeps a non-catalog type visible, and the endpoint now 422s anything not
  // in the catalog. Without this, confirming a document typed `unknown` would be a guaranteed error.
  const isCatalogType = (catalog ?? []).some((type) => type.value === selected);
  const canApply = isCatalogType && (changed || needsReview);
  // LP-638 — READ FROM THE CATALOG, not from a local set. The frontend's own answer was three
  // types (`pay_stub`, `w2`, `bank_statement`) written in Phase 1 while the backend registry grew
  // to 121 — so correcting a document to `closing_disclosure` said "recorded only — no data is
  // extracted" while the pipeline extracted it. A sentence about what the system will do, wrong.
  const chosen = (catalog ?? []).find((type) => type.value === selected);
  const reExtracts = chosen?.extracts ?? false;
  const chosenLabel = chosen?.label ?? humanize(selected);

  function handleSave() {
    override.mutate(selected, {
      onSuccess: () =>
        // The catalog's own label, not a re-humanised slug — otherwise choosing "W-2" in the
        // picker confirms "Type set to W2", and the two names for one thing are back. And
        // "Type set to" is wrong for a confirmation, where nothing was set.
        toast.success(changed ? `Type set to ${chosenLabel}` : `Confirmed as ${chosenLabel}`, {
          description: reExtracts
            ? "Re-extracting in the background…"
            : "Relabeled — this type isn’t extracted.",
        }),
      onError: (error) =>
        toast.error("Couldn’t update the type", { description: getErrorMessage(error) }),
    });
  }

  return (
    <section className="mt-6">
      <h3 className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-gray-400">
        <PencilLine className="h-3.5 w-3.5" />
        Correct type
      </h3>
      {typesFailed && (
        // A FAILED FETCH IS NOT AN EMPTY CATALOG. `catalog` is undefined either way, so without
        // this the picker simply offers nothing (or only the document's current type) and the
        // processor is left to conclude the list is broken — on the one control LP-638 exists to
        // restore. `isPending` goes false on error, so the "Loading types…" placeholder does not
        // cover this.
        <p className="mt-2 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">
          Couldn’t load the document types. Reopen this document or refresh the page to try again.
        </p>
      )}
      {needsReview && (
        <p className="mt-2 rounded-lg border border-warning/30 bg-warning/10 px-3 py-2 text-xs text-warning">
          The AI wasn’t confident about this classification — confirm or correct the type below.
        </p>
      )}
      <div className="mt-3 flex items-center gap-2">
        <div className="flex-1">
          <SearchableSelect
            id={`doc-type-${summary.id}`}
            label="Document type"
            onOpenChange={onPickerOpenChange}
            options={options}
            value={selected || null}
            onChange={setSelected}
            disabled={override.isPending || typesPending}
            placeholder={typesPending ? "Loading types…" : "Search document types…"}
            emptyMessage="No document type matches"
          />
        </div>
        <Button
          type="button"
          size="sm"
          onClick={handleSave}
          disabled={!canApply || override.isPending}
          className="gap-1.5"
        >
          {override.isPending && <Spinner className="h-3.5 w-3.5" />}
          {changed ? "Apply" : "Confirm"}
        </Button>
      </div>
      <p className="mt-1.5 text-[11px] text-gray-400">
        {/*
          NO CLAIM UNTIL THE CATALOG IS KNOWN (LP-638 review). `reExtracts` reads `catalog ?? []`,
          so while the list is loading — and permanently if the request fails — it is `false`, and
          this line asserted "no data is extracted" about types that are. The sentence it replaced
          was wrong for the same reason, from a stale local list; getting the source right does not
          help if the fallback still speaks with certainty.
        */}
        {catalog === undefined
          ? "Checking whether this type is extracted…"
          : reExtracts
            ? "Saving re-runs extraction for this type."
            : "This type is recorded only — no data is extracted."}
      </p>
      <ReprocessDocumentButton summary={summary} fileId={fileId} />
    </section>
  );
}

/**
 * Explicit replace (Model C, LP-71) — the processor deliberately supersedes THIS
 * document with a new upload (old → historical, new → current, both kept). A hidden
 * file input + a button; reused in the staleness warning and the footer.
 */
