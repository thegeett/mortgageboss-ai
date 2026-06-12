import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { InlineErrorState } from "@/components/ui/error-state";
import { Skeleton } from "@/components/ui/skeleton";
import type { ActivityPublic } from "@/lib/types/activity";
import { formatDistanceToNow } from "date-fns";
import { Activity } from "lucide-react";

function relative(iso: string): string {
  try {
    return formatDistanceToNow(new Date(iso), { addSuffix: true });
  } catch {
    return "";
  }
}

export function ActivityFeed({
  activity,
  isPending,
  isError,
  onRetry,
}: {
  activity: ActivityPublic[] | undefined;
  isPending: boolean;
  isError: boolean;
  onRetry?: () => void;
}) {
  return (
    <Card className="border-gray-200/80 shadow-sm">
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-sm font-semibold text-gray-900">
          <Activity className="h-4 w-4 text-gray-400" />
          Recent activity
        </CardTitle>
      </CardHeader>
      <CardContent>
        {isPending ? (
          <div className="space-y-3">
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-5/6" />
            <Skeleton className="h-4 w-2/3" />
          </div>
        ) : isError ? (
          <InlineErrorState message="Couldn't load activity." onRetry={onRetry} />
        ) : !activity || activity.length === 0 ? (
          <p className="py-4 text-sm text-gray-400">No activity yet.</p>
        ) : (
          <ul className="space-y-3">
            {activity.map((entry) => (
              <li key={entry.id} className="flex gap-3">
                <span
                  aria-hidden
                  className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-primary/60"
                />
                <div className="min-w-0">
                  <p className="text-sm text-gray-700">{entry.summary}</p>
                  <p className="text-xs text-gray-400">{relative(entry.created_at)}</p>
                </div>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
