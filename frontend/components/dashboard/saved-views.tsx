"use client";

import { type SavedView, useSavedViews } from "@/lib/api/saved-views";
import { writePipelineUrl } from "@/lib/loan-files/view-url";
import { usePipelineSearchStore } from "@/lib/stores/pipeline-search-store";
import { cn } from "@/lib/utils";
import Link from "next/link";

/**
 * Saved views in the context column (LP-UI-014).
 *
 * These replace the four hard-coded filter pills. "Blocked to submit" and
 * "Docs stale > 30d" are things a processing company decides for itself, not
 * things the product should enumerate — which is why the pills were wrong even
 * when they were useful.
 *
 * Each view is a LINK, not a button. The filter state lives in the URL
 * (`view-url.ts`), so a view is a place you can navigate to, bookmark, and
 * paste to a colleague. Making them buttons would put the state back in React
 * where nobody else can see it.
 *
 * Counts come from the server in the same response. Counting in the browser
 * would mean one `pageSize: 1` request per view — the StatsCards pattern
 * LP-UI-013 deleted, reintroduced through a different door.
 *
 * A VIEW'S SEARCH TERM IS NOT IN ITS LINK (LP-933). A view can store one, and
 * it matches borrower names, so the link carries the statuses and the view id
 * only. Clicking applies the term to the per-tab search store; arriving any
 * other way (back button, pasted link) is handled by the dashboard, which looks
 * the term up from the server's copy of the view.
 */
export function SavedViews({
  activeViewId,
  filtered = false,
}: {
  activeViewId: string | null;
  /** True when a filter is applied that is not one of these views. */
  filtered?: boolean;
}) {
  const { data: views, isPending, isError } = useSavedViews({ withCounts: true });

  const mine = views?.filter((view) => view.is_mine) ?? [];
  const shared = views?.filter((view) => !view.is_mine) ?? [];

  return (
    <nav aria-label="Saved views" className="w-nav p-2">
      {/* "All files" is current only when nothing is filtered. A hand-edited
          filter is not "All files", and marking it so tells the reader they are
          looking at everything when they are not. */}
      <ViewLink
        href="/dashboard"
        label="All files"
        count={null}
        active={activeViewId === null && !filtered}
        onSelect={() => usePipelineSearchStore.getState().applyView(null, "")}
      />

      {isPending ? <Hint>Loading…</Hint> : null}
      {isError ? <Hint>Views unavailable</Hint> : null}

      <Group title="Saved views" views={mine} activeViewId={activeViewId} />
      <Group title="Shared" views={shared} activeViewId={activeViewId} />

      {!isPending && !isError && (views?.length ?? 0) === 0 ? (
        <Hint>No saved views yet.</Hint>
      ) : null}
    </nav>
  );
}

function Group({
  title,
  views,
  activeViewId,
}: {
  title: string;
  views: SavedView[];
  activeViewId: string | null;
}) {
  if (views.length === 0) return null;
  return (
    <>
      <p className="px-2 pb-1 pt-3 text-label uppercase text-muted-foreground">{title}</p>
      {views.map((view) => (
        <ViewLink
          key={view.id}
          href={`/dashboard${writePipelineUrl({
            statuses: view.filters.statuses,
            viewId: view.id,
          })}`}
          label={view.name}
          count={view.count}
          active={view.id === activeViewId}
          onSelect={() =>
            usePipelineSearchStore.getState().applyView(view.id, view.filters.search ?? "")
          }
        />
      ))}
    </>
  );
}

function ViewLink({
  href,
  label,
  count,
  active,
  onSelect,
}: {
  href: string;
  label: string;
  count: number | null;
  active: boolean;
  /** Applies the view's search before navigating; it has no place in `href`. */
  onSelect: () => void;
}) {
  return (
    <Link
      href={href}
      onClick={onSelect}
      aria-current={active ? "page" : undefined}
      className={cn(
        "flex h-7 items-center gap-2 rounded-md px-2 text-sm transition-colors",
        active
          ? "bg-primary/10 font-medium text-primary"
          : "text-foreground-2 hover:bg-muted hover:text-foreground",
      )}
    >
      <span className="min-w-0 flex-1 truncate">{label}</span>
      {count !== null ? (
        <span className="tabular shrink-0 text-xs text-muted-foreground">{count}</span>
      ) : null}
    </Link>
  );
}

function Hint({ children }: { children: React.ReactNode }) {
  return <p className="px-2 py-1 text-xs text-muted-foreground">{children}</p>;
}
