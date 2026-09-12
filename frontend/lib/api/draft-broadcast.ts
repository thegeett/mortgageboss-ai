import { invalidateDraftViewsLocally } from "@/lib/api/draft-views";
import type { QueryClient } from "@tanstack/react-query";

/**
 * Tell this browser's OTHER tabs that a file's drafts changed (LP-845).
 *
 * Reported: "I have to refresh the communication page, after requesting document if communication
 * page is opened in different tab of the browser."
 *
 * LP-840 made the requesting tab refresh itself. A second tab is a different React tree with a
 * different QueryClient and was told nothing, so it served its cached timeline for the full
 * `staleTime` — and with `refetchOnWindowFocus: false`, even switching to it did not recheck.
 *
 * WHAT THIS DOES NOT REACH, stated so nobody describes it as more than it is: `BroadcastChannel` is
 * same-origin and same-browser. A second device, a second browser, and another processor entirely
 * are all outside it. Reaching them needs the server to push, which is a different ticket and real
 * infrastructure; this is the half that costs nothing.
 */
const CHANNEL = "mbai:draft-views";

type DraftChange = { fileId: string };

function channel(): BroadcastChannel | null {
  // Unavailable during SSR and in a few older browsers. A page that cannot announce still works
  // exactly as it did before this ticket, which is the right degradation: the requesting tab
  // refreshes itself either way.
  if (typeof BroadcastChannel === "undefined") return null;
  try {
    return new BroadcastChannel(CHANNEL);
  } catch {
    return null;
  }
}

/** Announce a draft change. Never called by the listener — see `listenForDraftChanges`. */
export function announceDraftChange(fileId: string): void {
  const bus = channel();
  if (!bus) return;
  try {
    bus.postMessage({ fileId } satisfies DraftChange);
  } finally {
    // One channel per announcement, closed immediately: a long-lived sender would keep this tab
    // receiving its own siblings' messages through a second subscription, and the listener below is
    // already the one place that handles them.
    bus.close();
  }
}

/**
 * Refresh this tab whenever another one announces a change.
 *
 * INVALIDATES LOCALLY AND DOES NOT RE-ANNOUNCE. `BroadcastChannel` does not deliver a message back
 * to the context that posted it, but it does deliver to every OTHER tab — so a listener that called
 * the announcing variant would have two tabs echoing each other indefinitely, each refresh
 * triggering the next. The split between `invalidateDraftViews` and `invalidateDraftViewsLocally`
 * exists for exactly this and for no other reason.
 *
 * Registered on the CLIENT rather than from a hook, like the blob-url eviction handlers beside it:
 * the subscription has to outlive any component that happens to be mounted when a message arrives.
 *
 * ONE WAY IT IS NOT LIKE THOSE TWO, worth knowing before the pattern is copied to something heavier:
 * they return a QueryCache subscription, which the client owns and drops along with itself, while
 * this returns `bus.close()` on a BroadcastChannel that stays open whether the client survives or
 * not. So `makeQueryClient` discarding the teardown is safe only while it is called once per page.
 * `draft-broadcast.test.ts` asserts that rather than trusting this sentence.
 */
export function listenForDraftChanges(queryClient: QueryClient): () => void {
  const bus = channel();
  if (!bus) return () => {};
  bus.onmessage = (event: MessageEvent<DraftChange>) => {
    const fileId = event.data?.fileId;
    // A message from a future version, or from something else on this origin. Refreshing every
    // query on a malformed id would be a worse answer than ignoring it.
    if (typeof fileId !== "string" || fileId === "") return;
    invalidateDraftViewsLocally(queryClient, fileId);
  };
  return () => bus.close();
}
