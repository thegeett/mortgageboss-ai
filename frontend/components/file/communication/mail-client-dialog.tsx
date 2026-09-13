"use client";

/**
 * "Where do you write your email?" — Screen 10 (LP-855).
 *
 * SHOWN ONCE, ON THE FIRST DRAFT. Nothing in a browser reports which mail client somebody uses, so
 * it is asked rather than detected. Asking on the first draft is asking at the moment it is about
 * to matter, which is the only moment the question makes sense.
 *
 * THE SEED MOVES A RADIO BUTTON AND SAYS WHY. IT NEVER DECIDES. A guess that applied itself would
 * open the wrong compose window with nothing on screen explaining it, and the processor would have
 * to work out that we had chosen for them. A guess that is visible and wrong costs one click.
 *
 * "NOT NOW" SELECTS `mailto:` AND STORES IT. A dialog that could be dismissed without answering
 * would come back on every draft, and a processor who wanted the desktop default would have no way
 * to say so — which is the same trap as asking forever.
 */

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { MailClient } from "@/lib/api/preferences";
import { cn } from "@/lib/utils";
import { useState } from "react";

/** The three options, in the order Screen 10 lists them. */
const OPTIONS: { value: MailClient; title: string; detail: string }[] = [
  { value: "gmail", title: "Gmail", detail: "Opens mail.google.com" },
  { value: "outlook_work", title: "Outlook on the web", detail: "Work or school account" },
  {
    value: "outlook_personal",
    title: "Outlook.com",
    detail: "A personal outlook.com or hotmail.com account",
  },
  {
    value: "mailto",
    title: "Whatever this computer opens",
    detail: "Apple Mail, desktop Outlook, Thunderbird — the safe answer if you're unsure",
  },
];

export function MailClientDialog({
  open,
  suggested,
  reason,
  pending = false,
  onChoose,
}: {
  open: boolean;
  /** Which option to pre-select. From the caller's own sign-in domain, server-side. */
  suggested: MailClient;
  /** Why, in the picker's own words. Empty when the domain says nothing. */
  reason: string;
  pending?: boolean;
  onChoose: (client: MailClient) => void;
}) {
  const [picked, setPicked] = useState<MailClient>(suggested);
  // Seeded on the suggestion's identity rather than in an effect: the dialog opens once, and the
  // suggestion arriving after the first render must fill the radio without throwing away a click.
  const [seededFrom, setSeededFrom] = useState<MailClient>(suggested);
  if (suggested !== seededFrom) {
    setSeededFrom(suggested);
    setPicked(suggested);
  }

  return (
    <Dialog open={open} onOpenChange={() => undefined}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="text-base">Where do you write your email?</DialogTitle>
          <DialogDescription className="text-xs">
            We&apos;ll copy the message and open the right compose window for you. You can change
            this any time in settings.
          </DialogDescription>
        </DialogHeader>

        <fieldset className="flex flex-col gap-2">
          <legend className="sr-only">Mail client</legend>
          {OPTIONS.map((option) => {
            const active = picked === option.value;
            return (
              <label
                key={option.value}
                className={cn(
                  "flex cursor-pointer items-start gap-2 border px-3 py-2 text-sm",
                  // THE SEEDED ONE GETS A PETROL BORDER. One accent, and this is a selection —
                  // the Ledger's rule 3 covers primary buttons and active navigation, and a chosen
                  // option in a picker is the same act.
                  active ? "border-primary" : "border-border",
                )}
              >
                <input
                  type="radio"
                  name="mail-client"
                  className="mt-1"
                  value={option.value}
                  checked={active}
                  onChange={() => setPicked(option.value)}
                />
                <span className="flex flex-col">
                  <span className="text-foreground">{option.title}</span>
                  <span className="text-xs text-muted-foreground">
                    {option.detail}
                    {/* THE REASON SITS ON THE SUGGESTED OPTION AND NOWHERE ELSE, because that is
                        the only place it explains anything. It is also why the guess is visible: a
                        pre-selected radio with no explanation is a decision somebody else made. */}
                    {option.value === suggested && reason ? (
                      <span className="text-foreground-2"> — suggested, because {reason}</span>
                    ) : null}
                  </span>
                </span>
              </label>
            );
          })}
        </fieldset>

        <div className="flex flex-wrap justify-end gap-2 border-t border-border pt-3">
          {/* "NOT NOW" IS AN ANSWER, not a dismissal — it stores the safe one. A dialog that could
              be closed without answering would reappear on every draft. */}
          <Button variant="ghost" disabled={pending} onClick={() => onChoose("mailto")}>
            Not now
          </Button>
          <Button disabled={pending} onClick={() => onChoose(picked)}>
            {picked === "mailto" ? "Use my mail app" : `Use ${OPTION_VERB[picked]}`}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

/** The primary's label follows the selection, so the button says what will happen. */
const OPTION_VERB: Record<MailClient, string> = {
  gmail: "Gmail",
  outlook_work: "Outlook",
  outlook_personal: "Outlook",
  mailto: "my mail app",
};
