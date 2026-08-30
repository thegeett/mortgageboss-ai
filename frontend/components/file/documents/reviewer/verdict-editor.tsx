"use client";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { useEffect, useRef, useState } from "react";

/**
 * Correct a value, or say why it can't be verified (LP-UI-033).
 *
 * Opened by `E` or `R` on the focused field, and it is the one place in the
 * reviewer where a processor types. That matters twice over: the shortcut layer
 * stands down while focus is in here (`isTypingTarget`), and Escape has to close
 * it, because a processor who opens this by mistake would otherwise have no
 * keyboard way out of a keyboard-first screen.
 *
 * A REJECTION REQUIRES A REASON. The API refuses one without, and the button is
 * disabled until there is one — the same rule enforced in both places, because a
 * disabled button that the server also rejects is a rule, while either alone is a
 * suggestion.
 */
export function VerdictEditor({
  fieldLabel,
  currentValue,
  onCorrect,
  onReject,
  onCancel,
  busy = false,
}: {
  fieldLabel: string;
  /** What the extraction read, as the starting point for a correction. */
  currentValue: string;
  onCorrect: (value: string) => void;
  onReject: (reason: string) => void;
  onCancel: () => void;
  busy?: boolean;
}) {
  const [value, setValue] = useState(currentValue);
  const [reason, setReason] = useState("");
  const firstField = useRef<HTMLInputElement | null>(null);

  // Focus on open: the processor pressed a key to get here and their hands have
  // not moved. Landing them outside the field would mean reaching for the mouse
  // in the one flow built to avoid it.
  useEffect(() => {
    firstField.current?.focus();
    firstField.current?.select();
  }, []);

  return (
    <div
      className="mt-2 rounded-md border border-border bg-muted/40 p-2"
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          event.stopPropagation();
          onCancel();
        }
      }}
    >
      <label className="block text-xs text-muted-foreground" htmlFor="verdict-value">
        Correct {fieldLabel}
      </label>
      <div className="mt-1 flex gap-1.5">
        <Input
          id="verdict-value"
          ref={firstField}
          value={value}
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && value.trim()) {
              event.preventDefault();
              onCorrect(value.trim());
            }
          }}
          className="h-8 md:text-sm"
        />
        <Button
          type="button"
          size="sm"
          className="h-8"
          disabled={busy || !value.trim()}
          onClick={() => onCorrect(value.trim())}
        >
          Save
        </Button>
      </div>

      <label className="mt-3 block text-xs text-muted-foreground" htmlFor="verdict-reason">
        Or say why you can&rsquo;t verify it
      </label>
      <Textarea
        id="verdict-reason"
        value={reason}
        onChange={(event) => setReason(event.target.value)}
        rows={2}
        className="mt-1 md:text-sm"
        placeholder="The page is a scan, the figure isn't on this document…"
      />
      <div className="mt-1.5 flex justify-end gap-1.5">
        <Button type="button" size="sm" variant="ghost" className="h-8" onClick={onCancel}>
          Cancel
        </Button>
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="h-8"
          disabled={busy || !reason.trim()}
          onClick={() => onReject(reason.trim())}
        >
          Can&rsquo;t verify
        </Button>
      </div>
    </div>
  );
}
