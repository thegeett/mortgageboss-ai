"use client";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useTimeline } from "@/lib/api/timeline";
import { messageTimeLabel, messageTimeShort } from "@/lib/message-time";
import { FileText } from "lucide-react";
import Link from "next/link";

/** The most rows the popover shows before deferring to the page. */
export const POPOVER_LIMIT = 5;

/**
 * How many unsent drafts this file has, wherever a processor is standing (LP-837).
 *
 * IN THE FILE HEADER, NOT THE TOPBAR, and the precedent is already written down two components
 * along: `FileContextDrawer` "lives beside the file's other actions rather than in the topbar,
 * because it is about THIS file". Drafts are per loan file. A global badge would have to answer
 * "whose drafts" on the files list and the dashboard, where the honest answer is none — and a badge
 * that is absent on most screens is not a place anybody looks. The header renders on every page of a
 * file, so "from anywhere" holds wherever the number is true.
 *
 * IT REPLACES LP-826's `DraftBadge`, whose two limits are this ticket. That badge was on the
 * verification screen alone, and it counted ONE draft — it read `useOutboundDraft`, which returns the
 * file's newest. LP-832 made several the ordinary state, so a badge reading the first is worse than
 * none.
 *
 * THE LIST IS THE SERVER'S "drafts", NOT A SECOND DEFINITION. `TimelineFilter.DRAFTS` decides what
 * counts, and it deliberately includes QUEUED: "a queued automatic reply is a message not yet gone,
 * which is what a processor means by looking at drafts". Defining the word again here is how the
 * mailbox and the header start disagreeing about what a file contains — the exact failure LP-812
 * refused when it put the filter on the server. So a queued auto-reply would count, and today none
 * exist: `record_auto_reply` has no caller.
 *
 * ABSENT RATHER THAN ZERO. A "0" badge is a permanent decoration on every file that has never
 * requested anything.
 */
export function DraftsIndicator({ fileId }: { fileId: string }) {
  const { data } = useTimeline(fileId, "drafts");
  const drafts = data?.entries ?? [];
  if (drafts.length === 0) return null;

  const shown = drafts.slice(0, POPOVER_LIMIT);
  const communicationPath = `/loan-files/${fileId}/communication`;

  return (
    // A MENU RATHER THAN A BARE POPOVER, and not only because no popover primitive exists here. A
    // menu is what this is — a short list of things to go to — and Radix gives it the keyboard
    // behaviour the ticket asks for: Enter opens, arrows move, Escape closes, focus returns to the
    // trigger. Hand-rolling that is how a control ends up mouse-only.
    <DropdownMenu>
      <DropdownMenuTrigger
        className="inline-flex items-center gap-1.5 rounded-full border border-primary/30 bg-primary/5 px-2.5 py-1 text-xs font-medium text-primary hover:bg-primary/10"
        aria-label={
          drafts.length === 1 ? "1 draft on this file" : `${drafts.length} drafts on this file`
        }
      >
        <FileText className="h-3.5 w-3.5" aria-hidden />
        {drafts.length}
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-80 p-0">
        {shown.map((draft) => (
          <DropdownMenuItem key={draft.id} asChild className="cursor-pointer p-0">
            {/* GOES TO THE PAGE AND OPENS THE DRAFT. Landing on the list with the modal shut is
                  how this fails quietly — it looks exactly like a mis-click — so the link carries
                  `?draft`, which LP-831 built the panel to read. */}
            <Link
              href={`${communicationPath}?draft=${draft.id}`}
              className="flex flex-col gap-0.5 px-3 py-2 hover:bg-muted"
            >
              <span className="truncate text-sm text-foreground">
                {draft.subject ?? draft.summary}
              </span>
              <span className="text-xs text-muted-foreground">
                {/* LP-838 — the shared formatter, not a fourth copy of a date format. The guard in
                      `message-time.test.ts` scans this file and fails if it grows its own. */}
                {messageTimeLabel(draft)} {messageTimeShort(draft.at)}
              </span>
            </Link>
          </DropdownMenuItem>
        ))}
        {drafts.length > POPOVER_LIMIT ? (
          <>
            <DropdownMenuSeparator />
            {/* ONLY WHEN THERE IS MORE. A "see more" that leads to the same rows is the LP-825 pill
                again: a control that always says nothing. */}
            <Link
              href={communicationPath}
              className="block border-t border-border px-3 py-2 text-xs font-medium text-primary hover:bg-muted"
            >
              See all {drafts.length} drafts
            </Link>
          </>
        ) : null}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
