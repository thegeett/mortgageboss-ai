"use client";

import { FileTable } from "@/components/dashboard/file-table";
import { FilterPills } from "@/components/dashboard/filter-pills";
import { SearchInput } from "@/components/dashboard/search-input";
import { StatsCards } from "@/components/dashboard/stats-cards";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useDebouncedValue } from "@/hooks/use-debounced-value";
import { useLoanFiles } from "@/lib/api/loan-files";
import { type FilterKey, statusesForFilter } from "@/lib/loan-files/status";
import { useAuthStore } from "@/lib/stores/auth-store";
import type { LoanFileSummary } from "@/lib/types/loan-file";
import { ChevronLeft, ChevronRight, Plus } from "lucide-react";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";

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

  const [filter, setFilter] = useState<FilterKey>("all");
  const [searchInput, setSearchInput] = useState("");
  const [page, setPage] = useState(1);
  const search = useDebouncedValue(searchInput.trim(), 300);

  const statuses = useMemo(() => statusesForFilter(filter), [filter]);

  // Changing a filter or the search resets to the first page (done in the
  // handlers rather than an effect, so there's no extra render/refetch).
  const handleFilter = (next: FilterKey) => {
    setFilter(next);
    setPage(1);
  };
  const handleSearch = (next: string) => {
    setSearchInput(next);
    setPage(1);
  };

  const { data, isPending, isError } = useLoanFiles({
    page,
    pageSize: PAGE_SIZE,
    statuses,
    search,
  });

  const isFiltered = filter !== "all" || search !== "";
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
          <h1 className="text-2xl font-bold tracking-tight text-gray-900">
            {firstName ? `Welcome back, ${firstName}.` : "Dashboard"}
          </h1>
          <p className="mt-1 text-sm text-gray-500">Your loan file worklist.</p>
        </div>
        <Button type="button" onClick={newFile} className="gap-2 self-start sm:self-auto">
          <Plus className="h-4 w-4" />
          New file
        </Button>
      </div>

      <StatsCards />

      <Card className="overflow-hidden border-gray-200/80 shadow-sm">
        <div className="flex flex-col gap-3 border-b border-gray-100 p-4 sm:flex-row sm:items-center sm:justify-between">
          <FilterPills value={filter} onChange={handleFilter} />
          <SearchInput value={searchInput} onChange={handleSearch} />
        </div>

        <FileTable
          files={data?.items ?? []}
          isPending={isPending}
          isError={isError}
          isFiltered={isFiltered}
          onSelect={goToFile}
          onNewFile={newFile}
        />

        {!isError && total > 0 && (
          <div className="flex items-center justify-between border-t border-gray-100 px-4 py-3 text-sm text-gray-500">
            <span>
              Showing <span className="font-medium text-gray-700">{rangeStart}</span>–
              <span className="font-medium text-gray-700">{rangeEnd}</span> of{" "}
              <span className="font-medium text-gray-700">{total}</span>
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
