"use client";

import { FileTable } from "@/components/dashboard/file-table";
import { SearchInput } from "@/components/dashboard/search-input";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useDebouncedValue } from "@/hooks/use-debounced-value";
import { useLoanFiles } from "@/lib/api/loan-files";
import { useSavedViews } from "@/lib/api/saved-views";
import { byAttention } from "@/lib/loan-files/attention";
import {
  carriesSearchTerm,
  isFiltered,
  usePipelineUrl,
  writePipelineUrl,
} from "@/lib/loan-files/view-url";
import { LOAN_FILE_STATUS } from "@/lib/status";
import { useAuthStore } from "@/lib/stores/auth-store";
import { usePipelineSearchStore } from "@/lib/stores/pipeline-search-store";
import type { LoanFileSummary } from "@/lib/types/loan-file";
import { ChevronLeft, ChevronRight, Plus } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

const PAGE_SIZE = 20;

/**
 * Dashboard — the processor's worklist (LP-31). Renders inside the LP-27 shell:
 * stats, filter pills, search, and the loan-file table, all driven by the
 * LP-28 list endpoint. "New File" → /loan-files/new (LP-32); a row →
 * /loan-files/{display_id} (LP-33).
 */
export default function DashboardPage() {
  const router = useRouter();
  const firstName = useAuthStore((state) => state.user?.first_name);

  // Filter state lives in the URL (LP-UI-014), not in component state, so a
  // processor can paste what they are looking at to a colleague. EXCEPT the
  // search (LP-933): it matches borrower names, so it lives in a per-tab store
  // and never reaches the URL (ADR-405 as amended). The box keeps local state
  // for what has been typed but not yet committed.
  const urlState = usePipelineUrl();
  const search = usePipelineSearchStore((state) => state.search);
  const hydrated = useHydratedPipelineSearch();
  useApplyViewSearch(urlState.viewId, hydrated);
  useStripSearchTermFromUrl(urlState);

  const [searchInput, setSearchInput] = useState(search);
  const [page, setPage] = useState(1);
  const debouncedSearch = useDebouncedValue(searchInput.trim(), 300);

  // The store is the source of truth; the typed value catches up when it
  // changes from elsewhere (a refresh restoring it, a saved view applying one).
  useEffect(() => {
    setSearchInput(search);
  }, [search]);

  // Page 1 whenever the FILTER changes — any part of it, not just the search.
  // Keyed on the serialised state so statuses and the selected view count too:
  // switching from "All files" on page 3 to a view with two matches left `page`
  // at 3, and the table came back empty under "Showing 41–60 of 2".
  //
  // Adjusted DURING RENDER rather than in an effect. React documents this for
  // exactly this case, and it is not a style preference here: an effect resets
  // after a paint, so the wrong page is fetched and rendered first and the
  // corrected one arrives behind it. It also keeps this off the effect graph —
  // the search sync below is then the only effect writing state, so the two
  // cannot feed each other.
  const filterKey = `${writePipelineUrl(urlState)}|${search}`;
  const [pagedFilter, setPagedFilter] = useState(filterKey);
  if (pagedFilter !== filterKey) {
    setPagedFilter(filterKey);
    setPage(1);
  }

  // ...and it catches up the other way once typing settles. Keyed on the
  // DEBOUNCED value changing, not on the store differing from it: when a view
  // applies its own term, the debounced value lags 300ms behind, and comparing
  // the two would write the stale term straight back over the view's.
  const committed = useRef(debouncedSearch);
  useEffect(() => {
    if (debouncedSearch === committed.current) return;
    committed.current = debouncedSearch;
    usePipelineSearchStore.getState().setSearch(debouncedSearch);
  }, [debouncedSearch]);

  const statuses = urlState.statuses;

  // Not before the stored search is read: the first request would otherwise
  // ask for the unsearched list and render it for a frame after a refresh.
  const { data, isPending, isError } = useLoanFiles(
    { page, pageSize: PAGE_SIZE, statuses, search },
    { enabled: hydrated },
  );
  // Default order is "what needs me first" (LP-UI-013), not most-recently-
  // touched. Memoised so the table is not handed a new array every render.
  const sorted = useMemo(() => byAttention(data?.items ?? []), [data?.items]);

  const filtered = isFiltered(urlState, search);

  // How many files exist with NOTHING filtered — fetched only when the processor
  // is already looking at an empty filtered list, so the extra request happens in
  // the one state where the answer is worth a round trip. `page_size: 1` because
  // only `total` is read.
  const { data: unfiltered } = useLoanFiles(
    { page: 1, pageSize: 1, statuses: [], search: "" },
    { enabled: filtered && !isPending && (data?.items.length ?? 0) === 0 },
  );

  const filterSummary = {
    search,
    statusLabel:
      statuses.length === 1 && statuses[0]
        ? LOAN_FILE_STATUS[statuses[0]].label
        : statuses.length > 1
          ? `${statuses.length} statuses`
          : null,
    unfilteredTotal: unfiltered?.total ?? null,
  };

  const clearFilters = () => {
    usePipelineSearchStore.getState().applyView(null, "");
    router.replace("/dashboard");
  };
  const total = data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const rangeStart = total === 0 ? 0 : (page - 1) * PAGE_SIZE + 1;
  const rangeEnd = Math.min(page * PAGE_SIZE, total);

  const goToFile = (file: LoanFileSummary) => router.push(`/loan-files/${file.display_id}`);
  const newFile = () => router.push("/loan-files/new");

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          {/* h2, not h1: the topbar breadcrumb already carries the page's h1
              ("Dashboard"), and it is the only h1 on every other route. Two h1s
              on one page gives a screen reader two answers to "where am I". This
              is a greeting under that heading, not a second title. */}
          <h2 className="text-2xl font-semibold tracking-tight text-foreground">
            {firstName ? `Welcome back, ${firstName}.` : "Dashboard"}
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">Your loan file worklist.</p>
        </div>
        <Button type="button" onClick={newFile} className="gap-2 self-start sm:self-auto">
          <Plus className="h-4 w-4" />
          New file
        </Button>
      </div>

      <Card className="border-border/80">
        <div className="flex flex-col gap-3 border-b border-border p-4 sm:flex-row sm:items-center sm:justify-between">
          {/* The four hard-coded pills are gone (LP-UI-014) — saved views in
              the context column replace them. What is left here is the search,
              and the name of the view you are looking at. */}
          <p className="text-sm text-muted-foreground">
            {total} {total === 1 ? "file" : "files"}
            {filtered ? " matching" : ""}
          </p>
          <SearchInput value={searchInput} onChange={setSearchInput} />
        </div>

        <FileTable
          files={sorted}
          isPending={isPending}
          isError={isError}
          isFiltered={filtered}
          filterSummary={filterSummary}
          onClearFilters={clearFilters}
          onSelect={goToFile}
          onNewFile={newFile}
        />

        {!isError && total > 0 && (
          <div className="flex items-center justify-between border-t border-border px-4 py-3 text-sm text-muted-foreground">
            <span>
              Showing <span className="font-medium text-foreground-2">{rangeStart}</span>–
              <span className="font-medium text-foreground-2">{rangeEnd}</span> of{" "}
              <span className="font-medium text-foreground-2">{total}</span>
            </span>
            <div className="flex items-center gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="gap-1"
                disabled={page <= 1}
                onClick={() => setPage((current) => Math.max(1, current - 1))}
              >
                <ChevronLeft className="h-4 w-4" />
                Prev
              </Button>
              <span className="tabular-nums">
                Page {page} / {totalPages}
              </span>
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="gap-1"
                disabled={page >= totalPages}
                onClick={() => setPage((current) => Math.min(totalPages, current + 1))}
              >
                Next
                <ChevronRight className="h-4 w-4" />
              </Button>
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}

/**
 * Read the stored search once, on mount, and say when it has been read.
 *
 * The store skips hydration so the server's empty render and the first client
 * render agree; this is the one place that hydrates it.
 */
function useHydratedPipelineSearch(): boolean {
  const [hydrated, setHydrated] = useState(false);
  useEffect(() => {
    void Promise.resolve(usePipelineSearchStore.persist.rehydrate()).finally(() =>
      setHydrated(true),
    );
  }, []);
  return hydrated;
}

/**
 * When the URL's view is not the one the stored search belongs to, apply that
 * view's own search term — from the server's copy of the view, never from the
 * URL (LP-933). This covers every way of arriving at a view: a click, the back
 * button, a pasted link. A refresh on the same view changes nothing, so a term
 * typed on top of a view survives it. "All files" (no view) means no search.
 *
 * A view that cannot be found (deleted, or the list failed) applies no term
 * rather than keeping the last one: a leftover search would filter a view its
 * owner never set up that way.
 */
function useApplyViewSearch(viewId: string | null, hydrated: boolean): void {
  const storedViewId = usePipelineSearchStore((state) => state.viewId);
  const { data: views, isError } = useSavedViews({ withCounts: true });
  useEffect(() => {
    if (!hydrated || storedViewId === viewId) return;
    const { applyView } = usePipelineSearchStore.getState();
    if (viewId === null) {
      applyView(null, "");
      return;
    }
    if (!views && !isError) return;
    const view = views?.find((candidate) => candidate.id === viewId);
    applyView(viewId, view?.filters.search ?? "");
  }, [hydrated, storedViewId, viewId, views, isError]);
}

/**
 * A link from before LP-933 may still carry `?q=`. It is removed from the
 * address bar and NOT applied: obeying it would keep the name in the history
 * entry the processor is looking at, and a link opened in a new tab is meant to
 * show the filters without the search.
 */
function useStripSearchTermFromUrl(urlState: ReturnType<typeof usePipelineUrl>): void {
  const router = useRouter();
  const searchParams = useSearchParams();
  const stray = carriesSearchTerm(searchParams);
  useEffect(() => {
    if (stray) router.replace(`/dashboard${writePipelineUrl(urlState)}`);
  }, [stray, urlState, router]);
}
