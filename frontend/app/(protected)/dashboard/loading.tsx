import { Card } from "@/components/ui/card";
import { Skeleton, SkeletonRows } from "@/components/ui/skeleton";

/**
 * Route-level loading shell for the dashboard (LP-47). Shown during the
 * navigation/code-split gap before the page mounts; mirrors the page layout
 * (title, four stat cards, the filter bar + table) so the transition reads as
 * progress, not a frozen click, and there's no jump when the page appears.
 */
export default function DashboardLoading() {
  return (
    <div className="space-y-6" aria-busy>
      <output className="sr-only">Loading your dashboard</output>

      {/* Title + action */}
      <div className="flex items-center justify-between">
        <div className="space-y-2">
          <Skeleton className="h-7 w-56" />
          <Skeleton className="h-4 w-40" />
        </div>
        <Skeleton className="h-9 w-28" />
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {[0, 1, 2, 3].map((card) => (
          <Card key={card} className="border-gray-200/80 p-4 shadow-sm">
            <div className="flex items-center justify-between">
              <Skeleton className="h-4 w-20" />
              <Skeleton className="h-4 w-4 rounded" />
            </div>
            <Skeleton className="mt-2 h-8 w-14" />
          </Card>
        ))}
      </div>

      {/* Filter bar + table */}
      <Card className="overflow-hidden border-gray-200/80 shadow-sm">
        <div className="flex items-center justify-between border-b border-gray-100 p-4">
          <Skeleton className="h-8 w-64" />
          <Skeleton className="h-8 w-48" />
        </div>
        <div className="p-4">
          <SkeletonRows count={6} itemClassName="h-10" />
        </div>
      </Card>
    </div>
  );
}
