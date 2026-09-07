"use client";

/**
 * Reminder suggestion cards (LP-814).
 *
 * THEY SUGGEST AND NEVER SEND. Spec 4.5 says so, and the card says so too: every action here either
 * takes you to the file or puts the suggestion off. There is no button that emails anybody, and the
 * copy does not imply one — a card offering "Remind" would read as having sent something.
 *
 * SNOOZE AND DISMISS ARE THE SAME DECISION AT TWO DISTANCES, so they sit together rather than one
 * being a menu item inside the other. A processor who will deal with something on Monday and one
 * who will never deal with it are both saying "not this list, not now".
 */

import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { useSnooze } from "@/lib/api/reminders";
import { getErrorMessage } from "@/lib/errors/api-error";
import { notifyError, notifySuccess } from "@/lib/toast";
import type { ReminderKind, Suggestion } from "@/lib/types/reminder";
import { formatDistanceToNow } from "date-fns";
import { Clock, MailQuestion, Moon } from "lucide-react";
import Link from "next/link";

/**
 * The icon per rule — a second channel beside the words.
 *
 * THREE, NOT ONE. "A document is overdue", "nobody replied" and "this file has gone quiet" lead to
 * three different actions, and a column of identical clocks makes them one thing to scroll past.
 */
const ICONS: Record<ReminderKind, typeof Clock> = {
  needs_item_pending: Clock,
  no_reply: MailQuestion,
  file_untouched: Moon,
};

/** How long the suggestion has to run before it comes back. Days, because a processor thinks in
 *  them and an hour-level snooze on a three-day threshold is a button that does nothing. */
const SNOOZE_DAYS = 3;

export function SuggestionCard({
  suggestion,
  showFile = true,
}: {
  suggestion: Suggestion;
  /** False on a file's own page, where naming the file in every card is noise. */
  showFile?: boolean;
}) {
  const snooze = useSnooze(suggestion.loan_file_id);
  const Icon = ICONS[suggestion.kind];

  function decide(until: string | null, title: string) {
    snooze.mutate(
      { kind: suggestion.kind, subject_id: suggestion.subject_id, until },
      {
        onSuccess: () =>
          notifySuccess({
            title,
            consequence: until
              ? "It will come back if nothing changes."
              : "It will not be suggested again.",
          }),
        onError: (error) =>
          notifyError({ title: "Couldn’t save that", whatToDo: getErrorMessage(error) }),
      },
    );
  }

  return (
    <li className="flex items-start gap-3 rounded-lg border border-input bg-card p-3">
      <Icon className="mt-0.5 h-4 w-4 shrink-0 text-warning" aria-hidden />
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <span className="text-sm text-foreground">{suggestion.summary}</span>
        <span className="text-xs text-muted-foreground">
          {showFile ? (
            <>
              <Link
                href={`/loan-files/${suggestion.loan_file_id}/communication`}
                className="text-primary underline-offset-2 hover:underline"
              >
                {suggestion.display_id}
              </Link>
              {" · "}
            </>
          ) : null}
          since {formatDistanceToNow(new Date(suggestion.since), { addSuffix: true })}
        </span>
      </div>
      <div className="flex shrink-0 gap-1">
        <Button
          size="sm"
          variant="ghost"
          disabled={snooze.isPending}
          onClick={() =>
            decide(new Date(Date.now() + SNOOZE_DAYS * 24 * 3600 * 1000).toISOString(), "Snoozed")
          }
        >
          Snooze {SNOOZE_DAYS}d
        </Button>
        <Button
          size="sm"
          variant="ghost"
          disabled={snooze.isPending}
          onClick={() => decide(null, "Dismissed")}
        >
          Dismiss
        </Button>
      </div>
    </li>
  );
}

export function SuggestionList({
  suggestions,
  showFile = true,
  emptyTitle = "Nothing needs chasing",
}: {
  suggestions: Suggestion[];
  showFile?: boolean;
  emptyTitle?: string;
}) {
  if (suggestions.length === 0) {
    // "structural", not "nothing-yet": an empty list here is the CORRECT state and gets no action.
    // Offering one would imply a processor should go and find something to chase.
    return (
      <EmptyState kind="structural" title={emptyTitle}>
        Requests that go unanswered, messages nobody replies to, and files that go quiet appear
        here.
      </EmptyState>
    );
  }
  return (
    <ul className="flex flex-col gap-2">
      {suggestions.map((suggestion) => (
        <SuggestionCard
          key={`${suggestion.loan_file_id}-${suggestion.kind}-${suggestion.subject_id ?? "file"}`}
          suggestion={suggestion}
          showFile={showFile}
        />
      ))}
    </ul>
  );
}
