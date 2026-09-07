"use client";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { useComposeRequest } from "@/lib/api/communications";
import { useDocumentTypes } from "@/lib/api/documents";
import { useNeeds } from "@/lib/api/needs";
import { getErrorMessage } from "@/lib/errors/api-error";
import { notifyError, notifySuccess } from "@/lib/toast";
import { useMemo, useState } from "react";

/**
 * Asking for documents nothing flagged (LP-833).
 *
 * UNTIL THIS, A DRAFT COULD ONLY COME FROM A FINDING. A processor who knew they needed something no
 * rule had asked for could add a needs item by hand, and nothing drafted from it.
 *
 * THE FILE'S OWN NEEDS LEAD, and the rest of the catalog follows. There are 166 document types; a
 * flat alphabetical list of them is a list nobody reads, and the eight this file is actually waiting
 * on are the likely answer. Search covers the rest.
 *
 * WHAT "GENERATE" MEANS HERE, said plainly because the flag is off everywhere: selecting documents
 * produces the needs items and the draft DETERMINISTICALLY — that part involves no model. The model
 * writes three framing sentences around LP-817's render when `email_draft_enabled` is on, and
 * returns nothing rather than failing when it cannot. So a processor always gets a complete email,
 * and the toast says which kind rather than claiming the model wrote one it did not.
 */
export function ComposeRequestDialog({
  fileId,
  open,
  onOpenChange,
}: {
  fileId: string;
  open: boolean;
  onOpenChange: (next: boolean) => void;
}) {
  const { data: types } = useDocumentTypes();
  const { data: needs } = useNeeds(fileId);
  const compose = useComposeRequest(fileId);
  const [query, setQuery] = useState("");
  const [picked, setPicked] = useState<string[]>([]);

  const outstanding = useMemo(
    () => new Set((needs ?? []).map((need) => need.needs_type).filter(Boolean) as string[]),
    [needs],
  );

  const matches = useMemo(() => {
    const term = query.trim().toLowerCase();
    const all = types ?? [];
    const shown = term
      ? all.filter(
          (type) =>
            type.label.toLowerCase().includes(term) || type.value.toLowerCase().includes(term),
        )
      : all;
    // THIS FILE'S OUTSTANDING NEEDS FIRST, then everything else, each already sorted by the server.
    // Ordered rather than filtered: the rest of the catalog is what this dialog is FOR.
    return [
      ...shown.filter((type) => outstanding.has(type.value)),
      ...shown.filter((type) => !outstanding.has(type.value)),
    ];
  }, [types, query, outstanding]);

  function toggle(value: string) {
    setPicked((current) =>
      current.includes(value) ? current.filter((v) => v !== value) : [...current, value],
    );
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[85vh] flex-col sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle className="text-base">Request documents</DialogTitle>
          <DialogDescription className="text-xs">
            Pick what you need. They join this file&apos;s needs list and a draft to the borrower.
          </DialogDescription>
        </DialogHeader>

        <Input
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search documents"
          aria-label="Search documents"
        />

        <ul className="flex min-h-0 flex-1 flex-col overflow-y-auto">
          {matches.map((type) => (
            <li key={type.value}>
              <label className="flex cursor-pointer items-center gap-2 border-b border-border px-1 py-2 text-sm last:border-b-0 hover:bg-muted">
                <input
                  type="checkbox"
                  checked={picked.includes(type.value)}
                  onChange={() => toggle(type.value)}
                />
                <span className="flex-1 truncate text-foreground">{type.label}</span>
                {outstanding.has(type.value) ? (
                  // SAID AT SELECTION, NOT AFTER. LP-826 built the after-the-fact answer; telling a
                  // processor before they pick is cheaper for everybody, and asking twice for one
                  // document is the mistake this prevents.
                  <span className="shrink-0 text-xs text-muted-foreground">already requested</span>
                ) : (
                  <span className="shrink-0 text-xs text-muted-foreground">{type.category}</span>
                )}
              </label>
            </li>
          ))}
        </ul>

        <div className="flex items-center justify-between gap-2 border-t border-border pt-3">
          <span className="text-xs text-muted-foreground">
            {picked.length === 0 ? "Nothing selected" : `${picked.length} selected`}
          </span>
          <Button
            type="button"
            disabled={picked.length === 0 || compose.isPending}
            onClick={() =>
              compose.mutate(picked, {
                onSuccess: (result) => {
                  notifySuccess({
                    title: "Draft prepared",
                    // NAMES WHICH KIND OF EMAIL IT IS. `email_draft_enabled` is off in every
                    // environment, so this says "from the template" today — and a message claiming
                    // the model wrote it would be the untrue half of this feature's own headline.
                    consequence: result.composed_by_model
                      ? `${result.needs_added} document(s) added, with wording drafted for this file. It is in this file's drafts.`
                      : `${result.needs_added} document(s) added, using the standard wording. It is in this file's drafts.`,
                  });
                  setPicked([]);
                  onOpenChange(false);
                },
                onError: (error) =>
                  notifyError({
                    title: "Couldn’t prepare the request",
                    whatToDo: getErrorMessage(error),
                  }),
              })
            }
          >
            {compose.isPending ? "Preparing…" : "Generate email"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
