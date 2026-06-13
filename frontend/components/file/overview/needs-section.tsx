import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { InlineErrorState } from "@/components/ui/error-state";
import { SkeletonRows } from "@/components/ui/skeleton";
import {
  NEEDS_STATUS_LABELS,
  PRIORITY_META,
  categoryLabel,
  outstandingNeedsCount,
} from "@/lib/loan-files/needs";
import type { NeedsItemPublic } from "@/lib/types/needs-item";
import { cn } from "@/lib/utils";
import { ClipboardList } from "lucide-react";

export function NeedsSection({
  needs,
  isPending,
  isError,
  onRetry,
}: {
  needs: NeedsItemPublic[] | undefined;
  isPending: boolean;
  isError: boolean;
  onRetry?: () => void;
}) {
  const outstanding = needs ? outstandingNeedsCount(needs) : 0;

  return (
    <Card className="border-gray-200/80 shadow-sm">
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-3">
        <CardTitle className="flex items-center gap-2 text-sm font-semibold text-gray-900">
          <ClipboardList className="h-4 w-4 text-gray-400" />
          Needs list
        </CardTitle>
        {!isPending && !isError && needs && needs.length > 0 && (
          <span className="text-sm font-medium text-gray-500">{outstanding} outstanding</span>
        )}
      </CardHeader>
      <CardContent aria-busy={isPending}>
        {isPending ? (
          <>
            <output className="sr-only">Loading the needs list</output>
            <SkeletonRows count={3} itemClassName="h-9" />
          </>
        ) : isError ? (
          <InlineErrorState message="Couldn't load the needs list." onRetry={onRetry} />
        ) : !needs || needs.length === 0 ? (
          <p className="py-4 text-sm text-gray-400">No outstanding needs.</p>
        ) : (
          <>
            <ul className="divide-y divide-gray-100">
              {needs.map((item) => {
                const priority = PRIORITY_META[item.priority];
                return (
                  <li key={item.id} className="flex items-center justify-between gap-3 py-2.5">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium text-gray-900">{item.title}</p>
                      <p className="text-xs text-gray-400">{categoryLabel(item.category)}</p>
                    </div>
                    <div className="flex shrink-0 items-center gap-2">
                      <span
                        className={cn(
                          "rounded-full border px-2 py-0.5 text-xs font-medium",
                          priority.className,
                        )}
                      >
                        {priority.label}
                      </span>
                      <span className="text-xs text-gray-500">
                        {NEEDS_STATUS_LABELS[item.status]}
                      </span>
                    </div>
                  </li>
                );
              })}
            </ul>
            <p className="mt-3 text-xs text-gray-400">
              Provisional starter list — refined as the file progresses.
            </p>
          </>
        )}
      </CardContent>
    </Card>
  );
}
