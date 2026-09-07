/**
 * The communication timeline (LP-812).
 *
 * THE FILTER IS A SERVER PARAMETER, not a client-side `.filter()`. Sent, received, drafts and
 * activity are defined in `services/timeline.py`; defining them again here would be two definitions
 * of one word that nothing forces to agree, and the first to drift is "sent", which would start
 * showing drafts and tell a processor they had already asked for something they had not.
 */
import { apiClient } from "@/lib/api/client";
import type { Timeline, TimelineFilter } from "@/lib/types/timeline";
import { useQuery } from "@tanstack/react-query";

export const timelineQueryKey = (fileId: string, filter: TimelineFilter) =>
  ["timeline", fileId, filter] as const;

export function useTimeline(fileId: string, filter: TimelineFilter) {
  return useQuery({
    queryKey: timelineQueryKey(fileId, filter),
    queryFn: async () =>
      (
        await apiClient.get<Timeline>(`/api/v1/loan-files/${fileId}/timeline`, {
          params: { filter },
        })
      ).data,
    enabled: Boolean(fileId),
  });
}
