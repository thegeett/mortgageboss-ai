"use client";

/**
 * The shortcut sheet (LP-UI-033), on `?`.
 *
 * A keyboard-only loop that nobody can discover is a keyboard-only loop nobody
 * uses. This is the discoverability half of the ticket, and it is deliberately a
 * plain list: a processor opens it once a week to check one binding, so the job is
 * to be scannable, not to be a product tour.
 *
 * The keys shown here are the SAME strings the binding table uses, but they are
 * written out rather than derived from it. Deriving them would couple the
 * documentation to the implementation in the direction that hides a bug: if a
 * binding silently changed, a generated sheet would change with it and still look
 * right. `shortcut-sheet.test.tsx` asserts the two agree instead.
 */

import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";

export interface Shortcut {
  keys: string;
  what: string;
}

export const SHORTCUTS: readonly Shortcut[] = [
  { keys: "Tab / ↓", what: "Next field needing attention" },
  { keys: "Shift+Tab / ↑", what: "Previous field" },
  { keys: "Enter", what: "Accept the extracted value" },
  { keys: "Shift+Enter", what: "Accept and go to the next flagged field" },
  { keys: "E", what: "Correct the value" },
  { keys: "R", what: "Can't verify — say why" },
  { keys: "Space", what: "Show or hide the highlight boxes" },
  { keys: "Alt (hold)", what: "Reveal every other highlight at once" },
  { keys: "+ / -", what: "Zoom the page in or out" },
  { keys: "0", what: "Back to fitting the column" },
  { keys: "[ / ]", what: "Previous / next document" },
  { keys: "⌘Enter", what: "Mark reviewed and move to the next document" },
  { keys: "?", what: "This list" },
];

export function ShortcutSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Keyboard shortcuts</DialogTitle>
        </DialogHeader>
        <dl className="mt-1 space-y-1.5">
          {SHORTCUTS.map((shortcut) => (
            <div key={shortcut.keys} className="flex items-baseline justify-between gap-4">
              <dt className="shrink-0 font-mono text-xs text-foreground-2">{shortcut.keys}</dt>
              <dd className="text-right text-sm text-muted-foreground">{shortcut.what}</dd>
            </div>
          ))}
        </dl>
        <p className="mt-3 border-t border-border pt-3 text-xs text-muted-foreground">
          Shortcuts pause while you are typing, so a correction can contain any letter.
        </p>
      </DialogContent>
    </Dialog>
  );
}
