"use client";

import { useLoanFileDocuments } from "@/lib/api/documents";
import { useNeeds } from "@/lib/api/needs";
import { hasInProgressDocuments } from "@/lib/loan-files/documents";
import { groupNeeds, proposedNeedsCount } from "@/lib/loan-files/needs";
import { cn } from "@/lib/utils";
import Link from "next/link";

/**
 * The Overview's compact view of the needs list (LP-UI-022).
 *
 * The full list moved to its own route. What the Overview still owes a processor
 * opening a file is how much is outstanding — so this is the group counts and a
 * way through, not a second copy of the list.
 *
 * Counted with `groupNeeds`, the same function the list itself groups by. A
 * summary that counted its own way is the LP-UI-013 defect: the number here and
 * the list one click away must not be able to disagree.
 */
export function NeedsSummary({ fileId }: { fileId: string }) {
  const documents = useLoanFileDocuments(fileId);
  const live = hasInProgressDocuments(documents.data ?? []);
  const { data, isPending, isError } = useNeeds(fileId, { live });

  const items = data ?? [];
  const groups = groupNeeds(items);
  const proposed = proposedNeedsCount(items);
  const href = `/loan-files/${fileId}/needs`;

  return (
    <section aria-labelledby="needs-summary-heading">
      <header className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 pb-2">
        <h2 id="needs-summary-heading" className="text-label uppercase text-muted-foreground">
          Needs
        </h2>
        <Link
          href={href}
          className="text-xs text-muted-foreground hover:text-primary hover:underline"
        >
          Open the needs list
        </Link>
      </header>

      {isPending ? (
        <p className="text-sm text-muted-foreground" aria-busy>
          <output className="sr-only">Loading the needs summary</output>
          Loading…
        </p>
      ) : isError ? (
        <p className="text-sm text-muted-foreground">The needs list is unavailable.</p>
      ) : items.length === 0 ? (
        <p className="max-w-prose text-sm text-muted-foreground">
          No needs yet. A tailored checklist appears once the file is imported and its documents are
          read.
        </p>
      ) : (
        <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
          {groups.map((group) => (
            <Link key={group.key} href={href} className="group flex items-baseline gap-1.5">
              <span
                className={cn(
                  "tabular text-lg font-medium",
                  group.key === "needs_action" && group.items.length > 0
                    ? "text-warning"
                    : "text-foreground",
                )}
              >
                {group.items.length}
              </span>
              <span className="text-sm text-foreground-2 group-hover:text-primary">
                {group.meta.label}
              </span>
            </Link>
          ))}
          {/* An AI proposal is never acted on until a processor confirms it, so
              "to review" is a distinct call to action rather than part of the
              chase pile. */}
          {proposed > 0 ? (
            <Link href={href} className="text-sm text-primary hover:underline">
              {proposed} to review
            </Link>
          ) : null}
        </div>
      )}
    </section>
  );
}
