// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/client", () => ({ apiClient: { get } }));

import { makeQueryClient } from "@/lib/query-client";

import { pageImageQueryKey, usePageImage } from "./page-image";

const revoke = vi.fn();
const create = vi.fn(() => `blob:page-${create.mock.calls.length}`);

beforeEach(() => {
  vi.clearAllMocks();
  URL.createObjectURL = create as unknown as typeof URL.createObjectURL;
  URL.revokeObjectURL = revoke as unknown as typeof URL.revokeObjectURL;
  get.mockResolvedValue({
    data: new Blob(["x"]),
    headers: {
      "x-page-width-points": "612",
      "x-page-height-points": "792",
      "x-page-zoom": "2",
    },
  });
});
afterEach(() => vi.restoreAllMocks());

function wrapper(client: QueryClient) {
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
}

/**
 * An object url lives as long as the CACHED OBJECT that holds it.
 *
 * The first version revoked in an effect cleanup keyed on the url — which also
 * runs when the url merely changes — while TanStack went on serving that same
 * object for five minutes. Paging 1 → 2 → 1 returned a dead blob, and the
 * browser drew its broken-image icon. Reported from the app; reproduced at
 * `naturalWidth: 0`; this is the regression test.
 */
describe("the page count", () => {
  it("comes back from the header, so the reviewer can say 'of 5'", async () => {
    get.mockResolvedValue({
      data: new Blob(["x"]),
      headers: { "x-page-count": "5", "x-page-zoom": "2" },
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { result } = renderHook(() => usePageImage("d1", 1), { wrapper: wrapper(client) });
    await waitFor(() => expect(result.current.data).toBeTruthy());
    expect(result.current.data?.pageCount).toBe(5);
    client.clear();
  });

  it("is null when the server did not say, never zero", async () => {
    // A missing header reads as 0, and "a document of zero pages" is a claim
    // nobody made. Null lets the control guard only the lower bound.
    get.mockResolvedValue({ data: new Blob(["x"]), headers: {} });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { result } = renderHook(() => usePageImage("d1", 1), { wrapper: wrapper(client) });
    await waitFor(() => expect(result.current.data).toBeTruthy());
    expect(result.current.data?.pageCount).toBeNull();
    client.clear();
  });
});

describe("usePageImage", () => {
  it("does NOT revoke when the page changes", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { result, rerender } = renderHook(({ page }) => usePageImage("d1", page), {
      initialProps: { page: 1 },
      wrapper: wrapper(client),
    });
    await waitFor(() => expect(result.current.data).toBeTruthy());
    const first = result.current.data?.url;

    rerender({ page: 2 });
    await waitFor(() => expect(result.current.data?.url).not.toBe(first));

    // The whole bug: page 1's url is still in the cache and must still work.
    expect(revoke).not.toHaveBeenCalledWith(first);
    client.clear();
  });

  it("serves a working url when the reader pages back", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { result, rerender } = renderHook(({ page }) => usePageImage("d1", page), {
      initialProps: { page: 1 },
      wrapper: wrapper(client),
    });
    await waitFor(() => expect(result.current.data).toBeTruthy());
    const first = result.current.data?.url;

    rerender({ page: 2 });
    await waitFor(() => expect(result.current.data?.url).not.toBe(first));
    rerender({ page: 1 });
    await waitFor(() => expect(result.current.data?.url).toBe(first));

    expect(revoke).not.toHaveBeenCalledWith(first);
    client.clear();
  });

  it("revokes when the cache evicts the entry", async () => {
    // The other half. Without this a forty-page document leaks forty images.
    //
    // `makeQueryClient()` rather than a bare `new QueryClient` — the revoke
    // subscription belongs to the client now, not to the hook, so a hand-built
    // client here would be testing a client the app never constructs.
    const client = makeQueryClient();
    const { result } = renderHook(() => usePageImage("d1", 1), { wrapper: wrapper(client) });
    await waitFor(() => expect(result.current.data).toBeTruthy());
    const url = result.current.data?.url as string;

    const cache = client.getQueryCache();
    const entry = cache.find({ queryKey: pageImageQueryKey("d1", 1) });
    expect(entry, "the query should be in the cache to evict").toBeTruthy();
    if (entry) cache.remove(entry);
    expect(revoke).toHaveBeenCalledWith(url);
  });
});

describe("the blob survives the component that fetched it", () => {
  /**
   * The revoke subscription used to live inside `usePageImage`, so it was torn
   * down with the component — and eviction happens LATER, by design, five
   * minutes after the last observer unmounts (TanStack's default `gcTime`).
   *
   * So leaving the reviewer removed every listener, and when the cache finally
   * dropped the entries nothing was there to revoke them. The comment said
   * "something must outlive the component, because the cached url does"; nothing
   * outlived ALL of them. Page after page of full-page PNGs stayed held for the
   * rest of the session.
   */
  it("revokes on eviction even after every component has unmounted", async () => {
    // The real client, because the subscription is now part of what MAKES one —
    // a hand-built QueryClient here would test a client the app never uses.
    const client = makeQueryClient();
    const { result, unmount } = renderHook(() => usePageImage("doc-1", 1), {
      wrapper: wrapper(client),
    });
    await waitFor(() => expect(result.current.data?.url).toBeTruthy());
    const url = result.current.data?.url;

    unmount(); // the processor leaves the reviewer
    expect(revoke).not.toHaveBeenCalled(); // still cached — correct so far

    const cache = client.getQueryCache();
    const entry = cache.find({ queryKey: pageImageQueryKey("doc-1", 1) });
    expect(entry, "the entry should still be cached after unmount").toBeTruthy();
    if (entry) cache.remove(entry);
    expect(revoke, "the blob leaked for the rest of the session").toHaveBeenCalledWith(url);
  });
});
