"use client";

import { FileTable } from "@/components/dashboard/file-table";
import { SearchInput } from "@/components/dashboard/search-input";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useDebouncedValue } from "@/hooks/use-debounced-value";
import { useLoanFiles } from "@/lib/api/loan-files";
import { byAttention } from "@/lib/loan-files/attention";
import { isFiltered, usePipelineUrl, writePipelineUrl } from "@/lib/loan-files/view-url";
import { useAuthStore } from "@/lib/stores/auth-store";
import type { LoanFileSummary } from "@/lib/types/loan-file";
import { ChevronLeft, ChevronRight, Plus } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

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
  // processor can paste what they are looking at to a colleague. The search box
  // keeps local state only for what has been typed but not yet committed —
  // pushing a route on every keystroke would fill the history with fragments.
  const urlState = usePipelineUrl();

  const [searchInput, setSearchInput] = useState(urlState.search);
  const [page, setPage] = useState(1);
  const debouncedSearch = useDebouncedValue(searchInput.trim(), 300);

  // The URL is the source of truth; the typed value catches up to it.
  useEffect(() => {
    setSearchInput(urlState.search);
  }, [urlState.search]);

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
  const filterKey = writePipelineUrl(urlState);
  const [pagedFilter, setPagedFilter] = useState(filterKey);
  if (pagedFilter !== filterKey) {
    setPagedFilter(filterKey);
    setPage(1);
  }

  // ...and it catches up the other way once typing settles.
  useEffect(() => {
    if (debouncedSearch === urlState.search) return;
    router.replace(`/dashboard${writePipelineUrl({ ...urlState, search: debouncedSearch })}`);
  }, [debouncedSearch, urlState, router]);

  const statuses = urlState.statuses;
  const search = urlState.search;

  const { data, isPending, isError } = useLoanFiles({
    page,
    pageSize: PAGE_SIZE,
    statuses,
    search,
  });
  // Default order is "what needs me first" (LP-UI-013), not most-recently-
  // touched. Memoised so the table is not handed a new array every render.
  const sorted = useMemo(() => byAttention(data?.items ?? []), [data?.items]);

  const filtered = isFiltered(urlState);
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
          <h1 className="text-2xl font-semibold tracking-tight text-foreground">
            {firstName ? `Welcome back, ${firstName}.` : "Dashboard"}
          </h1>
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
