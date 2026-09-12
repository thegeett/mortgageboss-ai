// @vitest-environment jsdom
import { QueryClient } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { announceDraftChange, listenForDraftChanges } from "./draft-broadcast";
import { invalidateDraftViews } from "./draft-views";
import { needsQueryKey } from "./needs";

/**
 * LP-845 — "I have to refresh the communication page, after requesting document if communication
 * page is opened in different tab of the browser."
 *
 * TWO REAL BroadcastChannels ON ONE NAME, which is as close to two tabs as a test gets: the spec
 * says a message is delivered to every OTHER channel on the origin and never back to the sender, so
 * a fake would be asserting my belief about that rule rather than the rule.
 */
const FILE = "LF-JR4T";

function tab() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  client.setQueryData(["timeline", FILE, "all"], { entries: [] });
  client.setQueryData(needsQueryKey(FILE), []);
  client.setQueryData(["documents", FILE], []);
  return client;
}

/** A message is delivered on a later task, so the assertion has to wait for one. */
const delivered = () => new Promise((resolve) => setTimeout(resolve, 0));

let stop: (() => void) | undefined;
afterEach(() => {
  stop?.();
  stop = undefined;
});

describe("a draft change reaches the other tab", () => {
  it("invalidates the mailbox in a tab that did nothing", async () => {
    const other = tab();
    stop = listenForDraftChanges(other);

    announceDraftChange(FILE);
    await delivered();

    expect(other.getQueryState(["timeline", FILE, "all"])?.isInvalidated).toBe(true);
    expect(other.getQueryState(needsQueryKey(FILE))?.isInvalidated).toBe(true);
    // The negative control: a query on the same file this has no business touching. Without it an
    // `invalidateQueries()` with no key would satisfy everything above.
    expect(other.getQueryState(["documents", FILE])?.isInvalidated).toBe(false);
  });

  it("does not invalidate a DIFFERENT file", async () => {
    const other = tab();
    other.setQueryData(["timeline", "LF-OTHER", "all"], { entries: [] });
    stop = listenForDraftChanges(other);

    announceDraftChange(FILE);
    await delivered();

    expect(other.getQueryState(["timeline", "LF-OTHER", "all"])?.isInvalidated).toBe(false);
  });

  it("ignores a message that carries no file", async () => {
    const other = tab();
    stop = listenForDraftChanges(other);

    const bus = new BroadcastChannel("mbai:draft-views");
    bus.postMessage({ nonsense: true });
    bus.postMessage({ fileId: "" });
    bus.close();
    await delivered();

    // Refreshing everything on a malformed id is a worse answer than ignoring it.
    expect(other.getQueryState(["timeline", FILE, "all"])?.isInvalidated).toBe(false);
  });

  it("DOES NOT ECHO — the listener refreshes without re-announcing", async () => {
    // THE WAY THIS FEATURE FAILS BADLY. A listener that called the announcing variant would have
    // two tabs refreshing each other forever, each message triggering the next: not a stale screen
    // but a request storm, and it would only appear with two tabs actually open.
    const other = tab();
    stop = listenForDraftChanges(other);

    const heard: unknown[] = [];
    const eavesdropper = new BroadcastChannel("mbai:draft-views");
    eavesdropper.onmessage = (event) => heard.push(event.data);

    announceDraftChange(FILE);
    await delivered();
    await delivered();

    eavesdropper.close();
    // Exactly one: the announcement itself. A second is the listener answering it.
    expect(heard).toHaveLength(1);
  });

  it("survives a browser with no BroadcastChannel", async () => {
    // SSR, and a few older browsers. The requesting tab still refreshes itself — which is exactly
    // the behaviour before this ticket, so degrading to it is correct rather than a failure.
    const original = globalThis.BroadcastChannel;
    // @ts-expect-error deliberately removing the global
    globalThis.BroadcastChannel = undefined;
    try {
      const client = tab();
      const unsubscribe = listenForDraftChanges(client);
      expect(() => announceDraftChange(FILE)).not.toThrow();
      expect(() => unsubscribe()).not.toThrow();
    } finally {
      globalThis.BroadcastChannel = original;
    }
  });
});

describe("the app's own client listens", () => {
  it("a client from makeQueryClient refreshes on another tab's announcement", async () => {
    // THE WIRING, which every test above assumes. They call `listenForDraftChanges` themselves, so
    // all six pass against a build where nothing ever registers it — the feature complete and
    // connected to nothing, which is the shape of the LP-840 defect that started this run.
    const { makeQueryClient } = await import("@/lib/query-client");
    const client = makeQueryClient();
    client.setQueryData(["timeline", FILE, "all"], { entries: [] });

    announceDraftChange(FILE);
    await delivered();

    expect(client.getQueryState(["timeline", FILE, "all"])?.isInvalidated).toBe(true);
  });
});

describe("invalidateDraftViews", () => {
  it("refreshes this tab AND announces to the others", async () => {
    const mine = tab();
    const other = tab();
    stop = listenForDraftChanges(other);

    invalidateDraftViews(mine, FILE);
    await delivered();

    expect(mine.getQueryState(["timeline", FILE, "all"])?.isInvalidated).toBe(true);
    expect(other.getQueryState(["timeline", FILE, "all"])?.isInvalidated).toBe(true);
  });
});
