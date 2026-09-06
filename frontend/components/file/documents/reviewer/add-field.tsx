"use client";

import { Plus } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

/**
 * Add a field the extraction missed (LP-703).
 *
 * A PICK FROM A LIST, NEVER FREE TEXT. The choices are the document type's own
 * declared field names, sent by the API with the ones already extracted removed.
 * A key outside that set is data no rule can ever read, so a text box here would
 * let a processor type a value into a field that reaches nobody — busy work that
 * looks like progress, and the worst kind, because the file then looks more
 * complete than it is.
 *
 * COLLAPSED BY DEFAULT. The reviewer's job is checking what the model read;
 * adding is the rarer move, and a permanently open form at the foot of every
 * document's field list would be a control in the way of the common case.
 */
export function AddField({
  fields,
  onAdd,
  busy = false,
}: {
  /** Field names this document type declares and the extraction does not carry. */
  fields: readonly string[];
  onAdd: (fieldKey: string, value: string) => void;
  busy?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [fieldKey, setFieldKey] = useState("");
  const [value, setValue] = useState("");

  // NOTHING TO OFFER IS NOT AN EMPTY MENU. An untyped document has no declared
  // field set, and one whose extraction already carries every declared field has
  // nothing left to add. Either way a control that opens onto no choices is worse
  // than no control.
  if (fields.length === 0) return null;

  if (!open) {
    return (
      <Button
        type="button"
        size="sm"
        variant="ghost"
        className="mt-2 h-8 w-full justify-start text-xs text-muted-foreground"
        onClick={() => setOpen(true)}
      >
        <Plus className="mr-1.5 h-3.5 w-3.5" aria-hidden />
        Add a field the extraction missed
      </Button>
    );
  }

  const ready = Boolean(fieldKey) && Boolean(value.trim());
  const submit = () => {
    if (!ready) return;
    onAdd(fieldKey, value.trim());
    setFieldKey("");
    setValue("");
    setOpen(false);
  };

  return (
    <div
      className="mt-2 rounded-md border border-border bg-muted/40 p-2"
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          event.stopPropagation();
          setOpen(false);
        }
      }}
    >
      <label className="block text-xs text-muted-foreground" htmlFor="add-field-key">
        Which field
      </label>
      {/* A native select: the list is short, it is keyboard-navigable without any
        code of ours, and this sits inside a pane whose whole premise is that a
        processor never reaches for the mouse. */}
      <select
        id="add-field-key"
        value={fieldKey}
        onChange={(event) => setFieldKey(event.target.value)}
        className="mt-1 h-8 w-full rounded-md border border-input bg-background px-2 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <option value="">Choose a field…</option>
        {fields.map((name) => (
          <option key={name} value={name}>
            {name}
          </option>
        ))}
      </select>

      <label className="mt-2 block text-xs text-muted-foreground" htmlFor="add-field-value">
        What it says on the document
      </label>
      <div className="mt-1 flex gap-1.5">
        <Input
          id="add-field-value"
          value={value}
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              submit();
            }
          }}
          className="h-8 md:text-sm"
        />
        <Button type="button" size="sm" className="h-8" disabled={busy || !ready} onClick={submit}>
          Add
        </Button>
      </div>
      <div className="mt-1.5 flex justify-end">
        <Button
          type="button"
          size="sm"
          variant="ghost"
          className="h-8"
          onClick={() => setOpen(false)}
        >
          Cancel
        </Button>
      </div>
      <p className="mt-1.5 text-[11px] leading-relaxed text-muted-foreground">
        The checks will read this the way they read an extracted value, and the file will show that
        you supplied it. It can be undone.
      </p>
    </div>
  );
}
