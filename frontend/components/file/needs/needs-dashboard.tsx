"use client";

import { AddNeedDialog } from "@/components/file/needs/add-need-dialog";
import { NeedCard } from "@/components/file/needs/need-card";
import { EmptyState } from "@/components/ui/empty-state";
import { InlineErrorState } from "@/components/ui/error-state";
import { SkeletonRows } from "@/components/ui/skeleton";
import { useLoanFileDocuments } from "@/lib/api/documents";
import { useLoanFile } from "@/lib/api/loan-files";
import { useNeeds } from "@/lib/api/needs";
import { hasInProgressDocuments } from "@/lib/loan-files/documents";
import { groupNeeds, outstandingNeedsCount, proposedNeedsCount } from "@/lib/loan-files/needs";
import type { AiNeedsStatus } from "@/lib/types/loan-file";
import { cn } from "@/lib/utils";
import { ClipboardList, Sparkles, TriangleAlert } from "lucide-react";

/**
 * The needs-list dashboard (LP-70) — the self-maintaining checklist, the face of
 * the differentiator. Opens the file → a tailored checklist appears (built by the
 * MISMO floor + the AI reasoning). It groups needs action-first, surfaces each
 * need's "why", and hosts the disposition flow.
 *
 * Live updates: it reads the documents query (already polling) to know when any
 * document is in-flight, and feeds that to `useNeeds` as `live` so the list polls
 * while a document is processing and settles once it's done — reflecting a
 * satisfied need (Pending → Received → Verified) without a manual refresh. While
 * the list is settling, a subtle "Updating…" cue shows the OUTCOME (the list
 * keeping current), never the engine's mechanism.
 */
export function NeedsDashboard({ fileId }: { fileId: string }) {
  const documents = useLoanFileDocuments(fileId);
  const file = useLoanFile(fileId);
  const live = hasInProgressDocuments(documents.data ?? []);
  const needs = useNeeds(fileId, { live });
  const aiStatus = file.data?.ai_needs_status ?? null;

  const items = needs.data ?? [];
  const groups = groupNeeds(items);
  const outstanding = outstandingNeedsCount(items);
  const proposed = proposedNeedsCount(items);
  // The subtle, transient "updating" cue: the list is settling while documents
  // process (or during a refetch after an action). NOT a queue-depth meter.
  const updating = !needs.isPending && (live || needs.isFetching);

  return (
    // LP-UI-022: a section on its own route, not a card in the middle of the
    // Overview. The list is the differentiator and it was the third thing on a
    // page about something else; the Card came off for the same reason
    // LP-UI-020's did — a box inside a box to reach one line.
    <section aria-labelledby="needs-heading" className="space-y-4">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h2 id="needs-heading" className="text-label uppercase text-muted-foreground">
              Needs list
            </h2>
            <UpdatingCue show={updating} />
          </div>
          {!needs.isPending && !needs.isError && items.length > 0 && (
            <p className="mt-1 text-xs text-muted-foreground">
              <span className="font-medium text-foreground-2">{outstanding}</span> need
              {outstanding === 1 ? "" : "s"} action
              {proposed > 0 && (
                <>
                  {" · "}
                  <span className="font-medium text-primary">{proposed}</span> to review
                </>
              )}
            </p>
          )}
        </div>
        <AddNeedDialog fileId={fileId} />
      </header>

      <div aria-busy={needs.isPending}>
        <AiNeedsNote status={aiStatus} />
        {needs.isPending ? (
          <>
            <output className="sr-only">Loading the needs list</output>
            <SkeletonRows count={4} itemClassName="h-14" />
          </>
        ) : needs.isError ? (
          <InlineErrorState
            message="Couldn't load the needs list."
            onRetry={() => void needs.refetch()}
          />
        ) : items.length === 0 ? (
          <EmptyNeeds />
        ) : (
          <div className="space-y-5">
            {groups.map((group) => (
              <section key={group.key}>
                <div className="mb-2 flex items-baseline gap-2">
                  <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                    {group.meta.label}
                  </h3>
                  <span className="text-xs text-muted-foreground">{group.items.length}</span>
                  <span className="text-xs text-muted-foreground">· {group.meta.hint}</span>
                </div>
                <ul className="space-y-2">
                  {group.items.map((need) => (
                    <NeedCard key={need.id} fileId={fileId} need={need} />
                  ))}
                </ul>
              </section>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}

/**
 * The AI-needs reasoning note (LP-71.5) — so a floor-only list is never silently
 * presented as complete. `pending`: the async reasoning is still running (more needs
 * may appear). `failed`: it didn't finish (the list may be incomplete). Otherwise
 * nothing — a settled, complete list needs no note.
 */
function AiNeedsNote({ status }: { status: AiNeedsStatus | null }) {
  if (status === "pending") {
    return (
      <div
        className="mb-3 flex items-start gap-2 rounded-md bg-info/5 px-3 py-2"
        aria-live="polite"
      >
        <Sparkles className="mt-0.5 h-3.5 w-3.5 shrink-0 text-info" aria-hidden />
        <p className="text-xs text-foreground-2">
          AI is still reviewing this file — more needs may appear shortly.
        </p>
      </div>
    );
  }
  if (status === "failed") {
    return (
      <div
        aria-live="polite"
        className="mb-3 flex items-start gap-2 rounded-md bg-warning/5 px-3 py-2"
      >
        <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" aria-hidden />
        <p className="text-xs text-foreground-2">
          AI review didn't finish, so this checklist may be incomplete. The required documents below
          are still accurate — re-import the file to retry the AI review.
        </p>
      </div>
    );
  }
  return null;
}

/** The subtle, transient "updating" cue — a soft pulsing dot + label. */
function UpdatingCue({ show }: { show: boolean }) {
  if (!show) return null;
  return (
    <span
      className="inline-flex items-center gap-1.5 text-[11px] font-medium text-muted-foreground"
      aria-live="polite"
    >
      <span className={cn("h-1.5 w-1.5 rounded-full bg-primary/60", "animate-pulse")} aria-hidden />
      Updating…
    </span>
  );
}

function EmptyNeeds() {
  return (
    <EmptyState kind="nothing-yet" title="No needs yet">
      A tailored checklist appears once the file is imported and its documents are read. You can
      also add a need yourself.
    </EmptyState>
  );
}
