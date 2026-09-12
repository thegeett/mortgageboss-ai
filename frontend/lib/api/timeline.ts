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
    // LP-845 — RECHECK WHEN THE TAB IS LOOKED AT. The client default is `false`, which is right for
    // most of this product: a loan file's documents do not change while you are reading them. A
    // MAILBOX does — a reply arrives, or the tab next door requests a document — and this is the one
    // screen whose whole job is to show what has happened since you last looked.
    //
    // The BroadcastChannel covers two tabs open side by side; this covers the far commoner case of
    // switching back to one that has been in the background, including after a change this browser
    // never saw (another device, or an inbound message).
    // `"always"`, NOT `true`, AND THE DIFFERENCE IS THE WHOLE FIX. `true` honours `staleTime`, which
    // is 60s client-wide — so a processor who switches to the verification tab, requests a document
    // and switches back within the minute gets the cached mailbox, which is precisely the reported
    // case. Measured: with `true`, a blur/focus inside `staleTime` issues no request at all.
    //
    // The cost is one request when the tab is focused, on the one screen whose job is to show what
    // has happened since you last looked.
    refetchOnWindowFocus: "always",
  });
}
