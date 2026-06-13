import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Skeleton, SkeletonText } from "@/components/ui/skeleton";

/**
 * Route-level loading shell for the file workspace (LP-47). Mirrors the LP-33
 * header + tab bar and the overview's three cards, so navigating into a file
 * shows structured progress (not a blank) and the real header/tabs slot in
 * without a shift.
 */
export default function FileWorkspaceLoading() {
  return (
    <div className="space-y-6" aria-busy>
      <output className="sr-only">Loading this loan file</output>

      {/* Header (title + subtitle) */}
      <div className="space-y-4">
        <div className="space-y-2">
          <Skeleton className="h-8 w-64" />
          <Skeleton className="h-4 w-80" />
        </div>
        {/* Tab bar */}
        <div className="flex gap-6 border-b border-gray-100 pb-2">
          {[0, 1, 2, 3, 4].map((tab) => (
            <Skeleton key={tab} className="h-5 w-20" />
          ))}
        </div>
      </div>

      {/* Overview cards */}
      <div className="grid gap-4 lg:grid-cols-3">
        {[0, 1, 2].map((card) => (
          <Card key={card} className="border-gray-200/80 shadow-sm">
            <CardHeader className="pb-2">
              <Skeleton className="h-4 w-28" />
            </CardHeader>
            <CardContent className="pt-0">
              <SkeletonText lines={4} widths={["w-full", "w-5/6", "w-4/6", "w-3/4"]} />
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
