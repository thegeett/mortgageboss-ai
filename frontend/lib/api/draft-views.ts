import { announceDraftChange } from "@/lib/api/draft-broadcast";
import { needsQueryKey } from "@/lib/api/needs";
import type { QueryClient } from "@tanstack/react-query";

/**
 * Refresh everything a change to a file's drafts is visible in (LP-840).
 *
 * ONE FUNCTION BECAUSE THE LIST IS NOT OBVIOUS AND KEEPS MOVING. A request for a document changes a
 * draft, a needs item and the activity log, and each of those is read by a different screen — so
 * every mutation that touches a draft had its own list of keys, and the lists drifted apart exactly
 * as you would expect.
 *
 * THE DEFECT THAT PRODUCED THIS: after LP-831 the Communication page reads `["timeline", fileId]`,
 * and the request mutations still invalidated `outboundDraftQueryKey` — the key of
 * `OutboundDraftPanel`, which that same ticket took off the page and which nothing renders any more.
 * So requesting a document refreshed a query nobody reads and left the list a processor was looking
 * at untouched: the draft was created, the page showed the same three rows, and it looked exactly
 * like a button that did nothing. The header badge reads the same key, so it did not move either.
 *
 * PREFIX MATCHING IS ELEMENT BY ELEMENT, which is the other half of that story. LP-809's review found
 * `["needs", id]` matching no query at all, because the real key is `["loan-file-needs", id]` — so
 * `needsQueryKey` is imported here rather than spelled out. `["timeline", fileId]` DOES match every
 * filter's query, which is what makes one line cover the pills.
 */
export function invalidateDraftViews(queryClient: QueryClient, fileId: string): void {
  invalidateDraftViewsLocally(queryClient, fileId);
  // LP-845 — AND TELL THE OTHER TABS. A processor with the communication page open beside the
  // verification tab clicks Request and goes back to a list that has not moved. This tab refreshing
  // itself was LP-840; the second tab is a different QueryClient and hears nothing without this.
  announceDraftChange(fileId);
}

/**
 * The three invalidations, WITHOUT announcing them.
 *
 * Separate from the function above so the broadcast listener has something to call that does not
 * broadcast. Two tabs each re-announcing what they received would refresh each other forever.
 */
export function invalidateDraftViewsLocally(queryClient: QueryClient, fileId: string): void {
  // The mailbox and the header badge — both read the timeline, under every filter.
  void queryClient.invalidateQueries({ queryKey: ["timeline", fileId] });
  // A request creates a needs item; the needs list is what tracks it.
  void queryClient.invalidateQueries({ queryKey: needsQueryKey(fileId) });
  // And the request is audited.
  void queryClient.invalidateQueries({ queryKey: ["loan-file-activity", fileId] });
}
