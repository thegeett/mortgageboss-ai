"use client";

import { LinkDocumentDialog } from "@/components/file/conditions/link-document-dialog";
import { Button } from "@/components/ui/button";
import { useUpdateItem, useUploadToItem } from "@/lib/api/conditions";
import { getErrorMessage } from "@/lib/errors/api-error";
import type { Condition, ConditionItem, Performer } from "@/lib/types/conditions";
import { ChevronDown, Paperclip, Send } from "lucide-react";
import { useEffect, useRef, useState } from "react";

/**
 * Who "Ask someone for it" can ask: EVERY recipient an ask reaches, and the backend's `_RECIPIENT`
 * table is the list (LP-955 review — it offered four of seven, so the insurance, HOA and employer
 * emails were unreachable from the only door that delegates her task, and an insurance ask sent as
 * "Someone else" lost the mortgagee clause the insurance email carries).
 *
 * The four absences, each for a reason: the PROCESSOR is her own task already; the ATTORNEY shares
 * Title's one email (`title_attorney`), so offering both would be two labels for one draft; the
 * LENDER and the APPRAISER go to the lender's draft (LP-942 — appraiser independence), which is not
 * a delegation she makes from here.
 */
const ASK_WHO: [Performer, string][] = [
  ["lo", "The LO"],
  ["borrower", "The borrower"],
  ["title", "Title"],
  ["insurance", "The insurance agent"],
  ["hoa", "The HOA"],
  ["employer", "The employer"],
  ["other_party", "Someone else"],
];

/**
 * A small disclosure menu: a button, and under it the choices as buttons. Not Radix's dropdown — two
 * or seven plain choices need no portal, and the drawer is itself a dialog that a portalled menu has
 * to fight for focus. Escape and a click outside close it.
 *
 * IT KEEPS THE KEYBOARD THE NATIVE `<select>` HAD (LP-958 review). This replaced a `<select>`, which
 * came with arrow keys, Home/End and focus management; a div that says `role="menu"` has made the same
 * promise to a screen reader and has to keep it by hand. So: the trigger opens on ArrowDown, opening
 * focuses the first choice, Up/Down wrap, Home/End jump, and closing returns focus to the trigger —
 * without which a keyboard user is dropped at the top of the drawer after every choice.
 */
function ActionMenu({
  label,
  icon,
  disabled,
  choices,
}: {
  label: string;
  icon: React.ReactNode;
  disabled: boolean;
  choices: [string, string, () => void][];
}) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const items = useRef<(HTMLButtonElement | null)[]>([]);
  const focusItem = (index: number) => {
    const count = choices.length;
    if (count === 0) return;
    items.current[((index % count) + count) % count]?.focus();
  };
  useEffect(() => {
    // The ref needs no dependency, and opening is the only time focus is moved for her.
    if (open) items.current[0]?.focus();
  }, [open]);
  useEffect(() => {
    if (!open) return;
    const away = (event: MouseEvent) => {
      if (box.current && !box.current.contains(event.target as Node)) setOpen(false);
    };
    const onEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        setOpen(false);
        trigger.current?.focus();
      }
    };
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", onEscape, true);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", onEscape, true);
    };
  }, [open]);
  return (
    <div ref={box} className="relative">
      <Button
        ref={trigger}
        type="button"
        variant="outline"
        size="sm"
        aria-haspopup="menu"
        aria-expanded={open}
        disabled={disabled}
        onClick={() => setOpen((was) => !was)}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown") {
            event.preventDefault();
            setOpen(true);
          }
        }}
      >
        {icon}
        {label}
        <ChevronDown className="h-3.5 w-3.5" aria-hidden />
      </Button>
      {open ? (
        <div
          role="menu"
          aria-label={label}
          className="absolute left-0 top-full z-20 mt-1 flex min-w-[15rem] flex-col rounded-md border border-input bg-popover py-1 shadow-md"
          onKeyDown={(event) => {
            const here = items.current.findIndex((el) => el === document.activeElement);
            if (event.key === "ArrowDown") {
              event.preventDefault();
              focusItem(here + 1);
            } else if (event.key === "ArrowUp") {
              event.preventDefault();
              focusItem(here <= 0 ? choices.length - 1 : here - 1);
            } else if (event.key === "Home") {
              event.preventDefault();
              focusItem(0);
            } else if (event.key === "End") {
              event.preventDefault();
              focusItem(choices.length - 1);
            }
          }}
        >
          {choices.map(([key, text, act], index) => (
            <button
              key={key}
              type="button"
              role="menuitem"
              ref={(el) => {
                items.current[index] = el;
              }}
              className="px-3 py-2 text-left text-sm text-foreground hover:bg-muted"
              onClick={() => {
                setOpen(false);
                trigger.current?.focus();
                act();
              }}
            >
              {text}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

/**
 * LP-953, redrawn by LP-958 (item 9) — her actions on one item, as one full-width row under it:
 *
 * - **Add document ▾** — "Link a document on this file…" opens `LinkDocumentDialog`; "Upload a new
 *   document…" uploads and links it to this item as it is created.
 * - **Ask someone ▾** — on her own task only (LP-955): the task becomes an ask in that person's draft.
 *
 * LP-953 put these in the item's 9rem right-hand column, where three controls and an inline picker
 * wrapped against each other (the owner's screenshot, 2026-10-03). The row now spans the card.
 *
 * With `replaceDocumentId` this is the evidence card's "Change": only the dialog, open, and closing it
 * is `onDone`.
 *
 * The server decides everything that matters: another file's document is refused, a document of the
 * wrong type is linked but fails "Right document type", and her checks run once it has been read.
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
  const [error, setError] = useState<string | null>(null);
  const update = useUpdateItem(fileId);
  const upload = useUploadToItem(fileId);
  const fileInput = useRef<HTMLInputElement>(null);
  const pending = upload.isPending || update.isPending;

  const dialog = (
    <LinkDocumentDialog
      open={picking}
      onOpenChange={(open) => {
        setPicking(open);
        if (!open && replaceDocumentId) onDone?.();
      }}
      fileId={fileId}
      condition={condition}
      item={item}
      replaceDocumentId={replaceDocumentId}
      onDone={replaceDocumentId ? undefined : onDone}
    />
  );
  if (replaceDocumentId) return dialog;

  const ask = (who: Performer) => {
    setError(null);
    // LP-955 — her task becomes an ask in that person's draft: the step and who acts.
    update.mutate(
      {
        conditionId: condition.id,
        itemId: item.id,
        option: who === "borrower" ? "ask_borrower" : "ask_third_party",
        performers: [who],
      },
      { onError: (err) => setError(getErrorMessage(err)) },
    );
  };

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex flex-wrap items-center gap-2">
        <ActionMenu
          label="Add document"
          icon={<Paperclip className="h-3.5 w-3.5" aria-hidden />}
          disabled={pending}
          choices={[
            ["link", "Link a document on this file…", () => setPicking(true)],
            ["upload", "Upload a new document…", () => fileInput.current?.click()],
          ]}
        />
        {item.option === "i_will_do_it" ? (
          <ActionMenu
            label="Ask someone"
            icon={<Send className="h-3.5 w-3.5" aria-hidden />}
            disabled={pending}
            choices={ASK_WHO.map(([who, label]) => [who, label, () => ask(who)])}
          />
        ) : null}
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
      {dialog}
      {error ? <p className="text-xs text-destructive">{error}</p> : null}
    </div>
  );
}
