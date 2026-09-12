import { apiClient } from "@/lib/api/client";
import { makeQueryClient } from "@/lib/query-client";
// @vitest-environment jsdom
import { QueryClientProvider, focusManager } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useTimeline } from "./timeline";

vi.mock("@/lib/api/client", () => ({
  apiClient: { get: vi.fn() },
}));

/**
 * LP-845 — the mailbox rechecks when you look at it.
 *
 * The client default is `refetchOnWindowFocus: false`, which is right for most of this product: a
 * loan file's documents do not change while you are reading them. A MAILBOX does — a reply arrives,
 * or the tab next door requests a document — and `staleTime` is a minute, so switching back to a
 * backgrounded communication page showed a list up to a minute behind with no way to know.
 *
 * ASSERTED AS BEHAVIOUR, NOT AS A SETTING. The first version read
 * `query.options.refetchOnWindowFocus` back off the cache, which typechecks as `unknown` because it
 * is an OBSERVER option rather than a query option — the value being there at runtime is an
 * implementation detail of this version of TanStack. Driving `focusManager` and counting requests
 * asserts the thing a processor experiences and survives that internal moving.
 */
const FILE = "LF-JR4T";
const get = vi.mocked(apiClient.get);

afterEach(() => {
  focusManager.setFocused(undefined);
  vi.clearAllMocks();
});

function wrapperFor(client: ReturnType<typeof makeQueryClient>) {
  return ({ children }: { children: React.ReactNode }) =>
    React.createElement(QueryClientProvider, { client }, children);
}

/** Leave the tab and come back, the way a processor does. */
async function blurAndFocus() {
  focusManager.setFocused(false);
  focusManager.setFocused(true);
}

describe("the timeline refetches on focus", () => {
  it("refetches when the tab is looked at again", async () => {
    get.mockResolvedValue({ data: { entries: [], inbox_address: "a@b.test" } } as never);
    const client = makeQueryClient();
    const { result } = renderHook(() => useTimeline(FILE, "all"), {
      wrapper: wrapperFor(client),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(get).toHaveBeenCalledTimes(1);

    await blurAndFocus();

    // Inside `staleTime`, so this is the focus opt-in and nothing else: without it the cached
    // minute-old mailbox is what the processor comes back to.
    await waitFor(() => expect(get).toHaveBeenCalledTimes(2));
  });

  it("opts in per query, rather than flipping the default for the whole product", () => {
    // Refetching every query on every focus is how a background tab becomes a request generator: a
    // loan file's documents do not change while you read them. The control is the CLIENT DEFAULT
    // rather than another hook, because the hooks around this one have refetch behaviour of their
    // own (documents polls while work is in flight) and would make this assert something else.
    expect(makeQueryClient().getDefaultOptions().queries?.refetchOnWindowFocus).toBe(false);
  });
});
