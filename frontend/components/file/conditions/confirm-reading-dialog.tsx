"use client";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useConfirmReading, useLibraryDefaultReading } from "@/lib/api/conditions";
import { PERFORMER_LABEL, performersLabel } from "@/lib/conditions/plan-words";
import { getErrorMessage } from "@/lib/errors/api-error";
import type { Condition, Performer } from "@/lib/types/conditions";
import { Check, Info, Plus, Sparkles, X } from "lucide-react";
import { useEffect, useState } from "react";

interface DraftItem {
  key: string | null;
  name: string;
  performers: Performer[];
}

/** The choices in an item's "who" select: every single performer, plus the pair the reading found. */
const SINGLE: Performer[] = [
  "borrower",
  "lo",
  "title",
  "attorney",
  "insurance",
  "hoa",
  "employer",
  "appraiser",
  "processor",
  "lender",
  "other_party",
];

function whoValue(performers: Performer[]): string {
  return performers.join("+");
}

/**
 * "Please confirm how we read 0132" (S3-03, LP-919).
 *
 * Opened for a reading below the confidence bar, or one made without the AI. The lender's words stay
 * in full above the items (principle 6). Each item is editable text with a "who" select and a remove
 * control; **This is right** saves her items and remembers them for this lender code (names and who
 * only, never this borrower's specifics); **Use the library default** takes the library type's items.
 * Nothing is drafted for the condition until one of the two is pressed (README rule 3).
 */
export function ConfirmReadingDialog({
  fileId,
  condition,
  open,
  onOpenChange,
}: {
  fileId: string;
  condition: Condition;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const reading = condition.reading;
  const [items, setItems] = useState<DraftItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const confirm = useConfirmReading(fileId);
  const libraryDefault = useLibraryDefaultReading(fileId);

  useEffect(() => {
    if (open && reading) {
      setItems(
        reading.items.map((item) => ({
          key: item.key,
          name: item.name,
          performers: item.performers,
        })),
      );
      setError(null);
    }
  }, [open, reading]);

  if (!reading) return null;
  const confidence = condition.reading_confidence;
  const busy = confirm.isPending || libraryDefault.isPending;
  const update = (index: number, patch: Partial<DraftItem>) =>
    setItems((current) => current.map((item, i) => (i === index ? { ...item, ...patch } : item)));

  const onRight = () =>
    confirm.mutate(
      { conditionId: condition.id, items },
      {
        onSuccess: () => onOpenChange(false),
        onError: (e) => setError(getErrorMessage(e)),
      },
    );
  const onLibrary = () =>
    libraryDefault.mutate(
      { conditionId: condition.id },
      {
        onSuccess: () => onOpenChange(false),
        onError: (e) => setError(getErrorMessage(e)),
      },
    );

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>
            Please confirm how we read {condition.lender_code ?? "this condition"}
          </DialogTitle>
          <DialogDescription>
            The reading is below our confidence bar, so nothing is drafted for this condition until
            you confirm it.
          </DialogDescription>
        </DialogHeader>

        <section className="rounded-lg border border-input bg-card p-3">
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Lender’s words
          </p>
          <p className="mt-1 font-serif text-sm leading-relaxed text-foreground">
            {condition.verbatim_text}
          </p>
        </section>

        <div className="flex items-center justify-between">
          <p className="text-sm font-semibold text-foreground">
            What we think it asks · {items.length} {items.length === 1 ? "item" : "items"}
          </p>
          {reading.source === "ai" && confidence !== null ? (
            <span className="inline-flex items-center gap-1 rounded-md border border-ai/30 bg-ai/10 px-1.5 py-0.5 text-xs text-ai">
              <Sparkles className="h-3 w-3" aria-hidden />
              Read by AI · {confidence.toFixed(2)}
            </span>
          ) : (
            <span className="rounded-md border border-input px-1.5 py-0.5 text-xs text-muted-foreground">
              Read without the AI
            </span>
          )}
        </div>

        <ol className="flex flex-col divide-y divide-border">
          {items.map((item, index) => (
            <li
              key={`${item.key ?? "new"}-${index}`}
              className="grid grid-cols-[1.5rem_1fr_11rem_1.25rem] items-start gap-2 py-2"
            >
              <span className="mt-1.5 flex h-5 w-5 items-center justify-center rounded-full border border-input text-xs text-foreground-2">
                {index + 1}
              </span>
              <textarea
                aria-label={`Item ${index + 1}`}
                value={item.name}
                rows={2}
                onChange={(event) => update(index, { name: event.target.value })}
                className="min-h-9 resize-none rounded-md border border-input bg-background px-2 py-1.5 text-sm"
              />
              <select
                aria-label={`Who acts on item ${index + 1}`}
                value={whoValue(item.performers)}
                onChange={(event) =>
                  update(index, { performers: event.target.value.split("+") as Performer[] })
                }
                className="h-9 rounded-md border border-input bg-background px-2 text-sm"
              >
                {item.performers.length > 1 ? (
                  <option value={whoValue(item.performers)}>
                    {performersLabel(item.performers)}
                  </option>
                ) : null}
                {SINGLE.map((performer) => (
                  <option key={performer} value={performer}>
                    {PERFORMER_LABEL[performer]}
                  </option>
                ))}
              </select>
              <button
                type="button"
                aria-label={`Remove item ${index + 1}`}
                onClick={() => setItems((current) => current.filter((_, i) => i !== index))}
                className="mt-1.5 text-muted-foreground hover:text-foreground"
              >
                <X className="h-4 w-4" aria-hidden />
              </button>
            </li>
          ))}
        </ol>

        <div className="flex items-start gap-2 rounded-lg border border-warning/40 bg-warning/10 p-3 text-xs text-foreground-2">
          <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" aria-hidden />
          <p>
            {whyUnsure(condition)} Your answer is saved for this lender code
            {condition.lender_code ? ` (${condition.lender_code})` : ""} so the next file reads it
            the same way.
          </p>
        </div>

        {error ? <p className="text-sm text-destructive">{error}</p> : null}

        <div className="flex items-center justify-end gap-2">
          <Button
            type="button"
            variant="ghost"
            disabled={busy || !condition.library_type}
            onClick={onLibrary}
          >
            Use the library default
          </Button>
          <Button
            type="button"
            variant="outline"
            disabled={busy}
            onClick={() =>
              setItems((current) => [...current, { key: null, name: "", performers: ["borrower"] }])
            }
          >
            <Plus className="h-4 w-4" aria-hidden />
            Add an item
          </Button>
          <Button type="button" disabled={busy || items.length === 0} onClick={onRight}>
            <Check className="h-4 w-4" aria-hidden />
            This is right
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

/**
 * Why the reading is unsure, in plain words. Built from what the app knows rather than asked of the
 * model: a reading without the AI, one with no library type, or one that mixes several people.
 */
function whyUnsure(condition: Condition): string {
  const reading = condition.reading;
  if (!reading || reading.source !== "ai") {
    return "Why it’s unsure: the AI could not read this sheet, so these are the library’s usual items.";
  }
  const performers = new Set(reading.items.flatMap((item) => item.performers));
  if (!condition.library_type) {
    return "Why it’s unsure: the library has no type for this condition yet.";
  }
  if (performers.size > 1) {
    return `Why it’s unsure: the condition mixes ${reading.items.length} different requests for ${performers.size} different people.`;
  }
  return "Why it’s unsure: the reading scored below our confidence bar.";
}

/** The dialog for one condition picked by id from the caller's rows, or nothing when none is picked. */
export function ConfirmReadingFor({
  fileId,
  conditions,
  conditionId,
  onClose,
}: {
  fileId: string;
  conditions: Condition[];
  conditionId: string | null;
  onClose: () => void;
}) {
  const condition = conditionId ? conditions.find((row) => row.id === conditionId) : undefined;
  if (!condition) return null;
  return (
    <ConfirmReadingDialog
      fileId={fileId}
      condition={condition}
      open
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
    />
  );
}
