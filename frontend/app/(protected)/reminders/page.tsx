"use client";

/**
 * Reminders (LP-814) — everything worth chasing, across every open file.
 *
 * COMPANY-WIDE IS THE POINT. "Nothing has happened on this file for a week" is by definition about
 * a file nobody is opening, so a per-file view could never surface it: a processor would have to
 * visit the file to be told they have not visited the file. That rule only exists because this page
 * does.
 *
 * IT SUGGESTS AND NEVER SENDS (spec 4.5). Nothing on this page emails anybody.
 */

import { SuggestionList } from "@/components/reminders/suggestion-cards";
import { InlineErrorState } from "@/components/ui/error-state";
import { SkeletonText } from "@/components/ui/skeleton";
import { useReminders } from "@/lib/api/reminders";

export default function RemindersPage() {
  const { data, isPending, isError, refetch } = useReminders();

  return (
    <div className="flex max-w-3xl flex-col gap-6 p-6">
      <header className="flex flex-col gap-1">
        <h1 className="text-lg font-semibold text-foreground">Reminders</h1>
        <p className="text-sm text-muted-foreground">
          Requests nobody has answered, messages nobody has replied to, and files that have gone
          quiet. Nothing here sends anything — opening a file is what lets you act.
        </p>
      </header>

      {isPending ? (
        <SkeletonText lines={4} />
      ) : isError ? (
        <InlineErrorState message="Reminders could not be loaded." onRetry={() => void refetch()} />
      ) : (
        <SuggestionList suggestions={data} emptyTitle="Nothing needs chasing" />
      )}
    </div>
  );
}
