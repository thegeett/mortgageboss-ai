// @vitest-environment jsdom
import { readFileSync, readdirSync } from "node:fs";
import { join, relative } from "node:path";
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

/**
 * WHY THIS IS A SOURCE SCAN AND NOT A BEHAVIOUR TEST.
 *
 * `listenForDraftChanges` returns a teardown and `makeQueryClient` drops it, which is safe for
 * exactly one reason: the client is built once, from the lazy `useState` initialiser in the root
 * layout's provider. That reason is a property of two call sites, so nothing inside the module can
 * check it, and a comment saying "only call this once" enforces nothing.
 *
 * The difference from the two blob-url eviction handlers registered beside it, which is easy to miss
 * because the comment there presents all three as the same move: those return a QueryCache
 * subscription, which is owned by the client and dies with it. This one returns `bus.close()` on a
 * BroadcastChannel — a browser resource whose `onmessage` closes over the client, so a discarded
 * client stays reachable and its channel stays open for the life of the page. One is free to drop.
 * The other is free to drop only while there is one client.
 */
// `process.cwd()` rather than `import.meta.url`, which Vite serves through a `/@fs/` prefix that
// `node:fs` cannot open. `lib/status.test.ts` resolves its source the same way.
const FRONTEND_ROOT = process.cwd();

function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) {
      return entry.name === "node_modules" || entry.name.startsWith(".") ? [] : sourceFiles(path);
    }
    if (!/\.tsx?$/.test(entry.name) || /\.test\.tsx?$/.test(entry.name)) return [];
    // The file that DEFINES it is not a call site.
    return path.endsWith(join("lib", "query-client.ts")) ? [] : [path];
  });
}

function productionCallers(): string[] {
  return sourceFiles(FRONTEND_ROOT)
    .filter((file) => /\bmakeQueryClient\s*\(/.test(readFileSync(file, "utf8")))
    .map((file) => relative(FRONTEND_ROOT, file));
}

describe("the draft listener is registered once per page", () => {
  it("one production call site builds the client", () => {
    const callers = productionCallers();
    // THE POSITIVE CONTROL, FIRST. A walker that returned nothing — wrong root, a rename, the
    // extension test inverted — makes the assertion below pass by finding no callers at all, which
    // is the failure mode this whole describe block exists to catch in other code.
    expect(callers).toContain(join("components", "providers.tsx"));
    expect(callers).toHaveLength(1);
  });

  it("and builds it in a lazy initialiser, not on every render", () => {
    // The regression this guards is a simplification, not a mistake: `const queryClient =
    // makeQueryClient()` in the component body reads fine and runs on EVERY render, and since the
    // teardown is dropped each render would leave another open BroadcastChannel behind.
    const providers = readFileSync(join(FRONTEND_ROOT, "components/providers.tsx"), "utf8");
    expect(providers).toMatch(/useState\(\s*\(\)\s*=>\s*makeQueryClient\(\)\s*\)/);
  });
});
