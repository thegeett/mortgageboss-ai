// @vitest-environment jsdom
import { needsQueryKey } from "@/lib/api/needs";
import { useResolveFinding } from "@/lib/api/verification";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import React from "react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/client", () => ({
  apiClient: { post: vi.fn().mockResolvedValue({ data: { findings: [], blocking: [] } }) },
}));

/**
 * Requesting documents from a finding creates a NEED and writes into the file's OPEN DRAFT (LP-809,
 * both routes). The needs list and the communication page each read those through their own query,
 * so both writes are invisible to the person who made them unless this mutation invalidates them.
 *
 * Reported on LF-JR4T from the other side: the backend never created the draft at all. Fixing only
 * the backend leaves the same empty screen for the 60s default staleTime — a processor who had the
 * communication page open, clicks Request, and goes back still sees nothing.
 *
 * ASSERTED ON THE QUERIES THEMSELVES, NOT ON THE SPY. The first version of this test compared
 * JSON-stringified keys against literals, and the literal it used as its positive control —
 * `["needs", identifier]` — was a key no query has ever been registered under. It passed while
 * proving the opposite of what it claimed: the mutation was invalidating nothing. Registering real
 * queries and reading `isInvalidated` back cannot pass that way, because a key that matches nothing
 * leaves every query untouched.
 *
 * LP-840 — AND IT STILL PINNED THE WRONG SCREEN. It asserted `outboundDraftQueryKey`, which was the
 * communication page's query when LP-809 wrote it. LP-831 moved that page onto the timeline and
 * deleted the panel; this test kept passing, because it was asserting a KEY rather than "the list a
 * processor is looking at refreshes". Reported as: three rows on the page, request a document,
 * still three rows — the draft created and the screen never told.
 *
 * It asserts the timeline now. The lesson is the one this file already carries, one level up: a
 * guard naming an implementation survives the implementation moving out from under it.
 */
const FILE = "LF-JR4T";

describe("useResolveFinding — what the request just wrote", () => {
  it("invalidates the needs list and the MAILBOX, and nothing else", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    client.setQueryData(needsQueryKey(FILE), []);
    // The mailbox and the header badge both read this, under every filter — registered with a
    // filter so the prefix match is exercised rather than assumed.
    client.setQueryData(["timeline", FILE, "all"], { entries: [] });
    // The negative control: a query on the same file that this mutation has no business touching.
    // Without it, an `invalidateQueries()` with no key at all would satisfy every assertion above.
    client.setQueryData(["documents", FILE], []);

    const wrapper = ({ children }: { children: React.ReactNode }) =>
      React.createElement(QueryClientProvider, { client }, children);
    const { result } = renderHook(() => useResolveFinding(FILE), { wrapper });
    result.current.mutate({ kind: "request-docs", findingId: "f1", note: "" });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(client.getQueryState(needsQueryKey(FILE))?.isInvalidated).toBe(true);
    expect(client.getQueryState(["timeline", FILE, "all"])?.isInvalidated).toBe(true);
    expect(client.getQueryState(["documents", FILE])?.isInvalidated).toBe(false);
  });
});

/**
 * LP-840 REVIEW — THE RULE, NOT THE CALLERS.
 *
 * The build named the gap itself: `invalidateDraftViews` is called by several mutations and nothing
 * asserted that, so a new one could hand-roll its own list and nothing would fail. Two already had —
 * `messages.ts` and `party-requests.ts` each kept their own, and each still invalidated
 * `["outbound-draft", fileId]`, a key whose query this very ticket deleted. The named constant went
 * and two string literals stayed.
 *
 * Enumerating the callers would be a list that goes stale the same way. The rule is derivable
 * instead: **refreshing the mailbox means going through the one place that knows what else to
 * refresh.** Anything that invalidates a timeline key directly has, by construction, decided on its
 * own what a draft change is visible in — which is the decision this module exists to own.
 */
describe("the one place a draft change is refreshed from", () => {
  // `process.cwd()` rather than `import.meta.url`: vitest runs from the frontend root, and the
  // URL form resolved to a bare "/lib/api" here — measured, and it made the scan read nothing.
  const SOURCE_DIR = `${process.cwd()}/lib/api/`;

  async function apiSources(): Promise<{ name: string; body: string }[]> {
    const { readdirSync, readFileSync } = await import("node:fs");
    return readdirSync(SOURCE_DIR)
      .filter((name) => name.endsWith(".ts") && !name.endsWith(".test.ts"))
      .map((name) => ({ name, body: readFileSync(`${SOURCE_DIR}${name}`, "utf8") }));
  }

  it("is the only module that invalidates a timeline key", async () => {
    const offenders = (await apiSources())
      .filter(({ name }) => name !== "draft-views.ts" && name !== "timeline.ts")
      .filter(({ body }) => /invalidateQueries\(\{\s*queryKey:\s*\["timeline"/.test(body))
      .map(({ name }) => name);

    expect(offenders).toEqual([]);
    // The control: the scan read the modules. An empty directory reports no offenders.
    expect((await apiSources()).length).toBeGreaterThan(5);
  });

  it("leaves no invalidation of the draft query this ticket deleted", async () => {
    // `useOutboundDraft` and `outboundDraftQueryKey` are gone. A key nothing reads is the defect
    // this ticket is about, so the literal must not survive the constant.
    const offenders = (await apiSources())
      .filter(({ body }) => body.includes('"outbound-draft"'))
      .map(({ name }) => name);

    expect(offenders).toEqual([]);
  });

  it("still names the timeline somewhere, or the mailbox refreshes for nobody", async () => {
    // THE POSITIVE HALF. Both assertions above are satisfied by a codebase that never mentions the
    // timeline at all — which is the reported bug with the invalidation removed rather than moved.
    const helper = (await apiSources()).find(({ name }) => name === "draft-views.ts");
    expect(helper).toBeDefined();
    expect(helper?.body).toMatch(/invalidateQueries\(\{\s*queryKey:\s*\["timeline"/);
  });
});
