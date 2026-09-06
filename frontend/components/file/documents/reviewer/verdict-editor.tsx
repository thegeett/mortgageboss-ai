"use client";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { useEffect, useRef, useState } from "react";

/**
 * Correct a value, say why it can't be verified, or take it off the document
 * (LP-UI-033, LP-703).
 *
 * Opened by `E` or `R` on the focused field, and it is the one place in the
 * reviewer where a processor types. That matters twice over: the shortcut layer
 * stands down while focus is in here (`isTypingTarget`), and Escape has to close
 * it, because a processor who opens this by mistake would otherwise have no
 * keyboard way out of a keyboard-first screen.
 *
 * A REASON IS REQUIRED for both of the bottom two actions. The API refuses either
 * without one and the buttons are disabled until there is one — the same rule
 * enforced in both places, because a disabled button that the server also rejects
 * is a rule, while either alone is a suggestion.
 *
 * THE TWO BOTTOM ACTIONS ARE NOT THE SAME, and the copy has to carry that or the
 * pair is worse than either alone. "Can't verify" leaves the model's value in
 * place for the next person to try again. "Not on this document" TAKES THE FIELD
 * OUT of the snapshot the rule engine reads. Both are undoable.
 *
 * The copy says "the checks no longer read it" and stops there deliberately. It
 * would read better to promise the rule then reports `couldnt_check`, and that IS
 * the intended degrade — but it runs through tag materialisation, and whether
 * every rule touching a field degrades that way is not something this component
 * can know. Promising it would be a sentence nothing tests.
 */
export function VerdictEditor({
  fieldLabel,
  currentValue,
  onCorrect,
  onReject,
  onRemove,
  onCancel,
  busy = false,
}: {
  fieldLabel: string;
  /** What the extraction read, as the starting point for a correction. */
  currentValue: string;
  onCorrect: (value: string) => void;
  onReject: (reason: string) => void;
  /** Take the field out of the snapshot — it is not on this document (LP-703). */
  onRemove: (reason: string) => void;
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
        Or give a reason instead
      </label>
      <Textarea
        id="verdict-reason"
        value={reason}
        onChange={(event) => setReason(event.target.value)}
        rows={2}
        className="mt-1 md:text-sm"
        placeholder="The page is a scan; this figure isn't printed anywhere…"
      />
      <div className="mt-1.5 flex flex-wrap items-center justify-end gap-1.5">
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
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="h-8"
          disabled={busy || !reason.trim()}
          onClick={() => onRemove(reason.trim())}
        >
          Not on this document
        </Button>
      </div>
      {/* The consequence, stated once, because the two buttons above differ only
        in what they do to the rules and nothing else on screen would say so. */}
      <p className="mt-1.5 text-[11px] leading-relaxed text-muted-foreground">
        &ldquo;Can&rsquo;t verify&rdquo; keeps the extracted value and records that you
        couldn&rsquo;t check it. &ldquo;Not on this document&rdquo; takes the field out, so the
        checks no longer read it. Both can be undone.
      </p>
    </div>
  );
}
