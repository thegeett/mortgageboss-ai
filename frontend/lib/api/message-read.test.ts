import { apiClient } from "@/lib/api/client";
import { makeQueryClient } from "@/lib/query-client";
import type { MessageDetail } from "@/lib/types/communication";
// @vitest-environment jsdom
import { QueryClientProvider, focusManager } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { messageQueryKey, useMessageDetail } from "./communications";
import { fileMessagesQueryKey } from "./inbound";
import { useMarkRead } from "./messages";

vi.mock("@/lib/api/client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn() },
}));

/**
 * LP-1009 review — opening a received email marks it read on the server, so a fetch of the detail is
 * an "open". The lists are refreshed only when the server says this request did the marking, the
 * detail is not refetched on focus, and "mark unread" updates the open copy without refetching it.
 */
const FILE = "LF-JR4T";
const get = vi.mocked(apiClient.get);
const post = vi.mocked(apiClient.post);

afterEach(() => {
  focusManager.setFocused(undefined);
  vi.clearAllMocks();
});

function wrapperFor(client: ReturnType<typeof makeQueryClient>) {
  return ({ children }: { children: React.ReactNode }) =>
    React.createElement(QueryClientProvider, { client }, children);
}

function detail(overrides: Partial<MessageDetail>): { data: MessageDetail } {
  return {
    data: {
      id: "m1",
      direction: "inbound",
      read_at: "2026-11-05T10:00:00Z",
      ...overrides,
    } as MessageDetail,
  };
}

function invalidatedKeys(spy: { mock: { calls: unknown[][] } }): unknown[] {
  return spy.mock.calls.map((call) => (call[0] as { queryKey: unknown }).queryKey);
}

describe("opening a received email", () => {
  it("refreshes the lists when this open marked it read", async () => {
    get.mockResolvedValue(detail({ marked_read: true }) as never);
    const client = makeQueryClient();
    const spy = vi.spyOn(client, "invalidateQueries");
    const { result } = renderHook(() => useMessageDetail(FILE, "m1"), {
      wrapper: wrapperFor(client),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(invalidatedKeys(spy)).toContainEqual(["timeline", FILE]);
    expect(invalidatedKeys(spy)).toContainEqual(fileMessagesQueryKey(FILE));
  });

  it("refreshes nothing when it was already read", async () => {
    get.mockResolvedValue(detail({ marked_read: false }) as never);
    const client = makeQueryClient();
    const spy = vi.spyOn(client, "invalidateQueries");
    const { result } = renderHook(() => useMessageDetail(FILE, "m1"), {
      wrapper: wrapperFor(client),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(spy).not.toHaveBeenCalled();
  });

  it("is not opened again when the browser tab is looked at again", async () => {
    get.mockResolvedValue(detail({}) as never);
    const client = makeQueryClient();
    const { result } = renderHook(() => useMessageDetail(FILE, "m1"), {
      wrapper: wrapperFor(client),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    // Stale at once, so only the focus setting can stop a refetch.
    client
      .getQueryCache()
      .find({ queryKey: messageQueryKey(FILE, "m1") })
      ?.setState({
        isInvalidated: true,
      });
    get.mockClear();

    focusManager.setFocused(false);
    focusManager.setFocused(true);
    await new Promise((resolve) => setTimeout(resolve, 20));

    expect(get).not.toHaveBeenCalled();
  });
});

describe("marking an open email unread", () => {
  it("updates its open copy without opening it again", async () => {
    const client = makeQueryClient();
    client.setQueryData(messageQueryKey(FILE, "m1"), detail({}).data);
    post.mockResolvedValue({ data: { id: "m1", read_at: null } } as never);
    const { result } = renderHook(() => useMarkRead(FILE), { wrapper: wrapperFor(client) });

    await act(async () => {
      await result.current.mutateAsync({ communicationId: "m1", read: false });
    });

    expect(client.getQueryData<MessageDetail>(messageQueryKey(FILE, "m1"))?.read_at).toBeNull();
    expect(get).not.toHaveBeenCalled();
  });
});
