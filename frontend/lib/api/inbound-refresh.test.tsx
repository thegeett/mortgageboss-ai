// @vitest-environment jsdom
/**
 * LP-1012 — an action on an attachment refreshes the open message. Staging: after Accept, the card said
 * "Added to documents" and the open message's "What arrived" above it still said "not yet accepted",
 * because no attachment action refreshed the message's own query.
 *
 * And not one she marked unread: fetching an unread message marks it read on the server (LP-1009).
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/client", () => ({
  apiClient: {
    post: vi.fn(async () => ({ data: { document_id: "d1", disposition: "accepted" } })),
    get: (url: string) => get(url),
  },
}));

const READ = { id: "m1", direction: "inbound", read_at: "2026-11-07T01:45:00Z", attachments: [] };
const get = vi.fn(async (_url: string) => ({ data: { ...READ, marked_read: false } }));

import { messageQueryKey, useMessageDetail } from "./communications";
import { useAcceptAttachment, useForwardAttachmentAsSheet, useRejectAttachment } from "./inbound";

function wrapper(client: QueryClient) {
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
}

function cacheWithTwoOpenMessages(): QueryClient {
  const client = new QueryClient();
  client.setQueryData(messageQueryKey("f1", "m1"), READ);
  client.setQueryData(messageQueryKey("f2", "m2"), { ...READ, id: "m2" });
  return client;
}

const isStale = (client: QueryClient, fileId: string, messageId: string) =>
  client.getQueryState(messageQueryKey(fileId, messageId))?.isInvalidated;

type Wrap = ReturnType<typeof wrapper>;

/** Each action renders its hook, then returns the call to make inside `act`. */
const ACTIONS: [string, (wrap: Wrap) => () => Promise<unknown>][] = [
  [
    "Accept",
    (wrap) => {
      const { result } = renderHook(() => useAcceptAttachment("f1"), { wrapper: wrap });
      return () => result.current.mutateAsync({ attachmentId: "a1" });
    },
  ],
  [
    "Correspondence",
    (wrap) => {
      const { result } = renderHook(() => useAcceptAttachment("f1"), { wrapper: wrap });
      return () => result.current.mutateAsync({ attachmentId: "a1", asCorrespondence: true });
    },
  ],
  [
    "Use as condition sheet",
    (wrap) => {
      const { result } = renderHook(() => useForwardAttachmentAsSheet("f1"), { wrapper: wrap });
      return () => result.current.mutateAsync({ attachmentId: "a1" });
    },
  ],
  [
    "Reject",
    (wrap) => {
      const { result } = renderHook(() => useRejectAttachment("f1"), { wrapper: wrap });
      return () => result.current.mutateAsync("a1");
    },
  ],
];

describe("an attachment action refreshes the open message", () => {
  it.each(ACTIONS)("%s", async (_name, render) => {
    const client = cacheWithTwoOpenMessages();
    const mutate = render(wrapper(client));
    expect(isStale(client, "f1", "m1")).toBe(false);
    await act(async () => {
      await mutate();
    });
    expect(isStale(client, "f1", "m1")).toBe(true);
    // Another file's open message is left alone.
    expect(isStale(client, "f2", "m2")).toBe(false);
  });
});

describe("what is not refreshed", () => {
  it.each(ACTIONS)(
    "%s leaves a message she marked unread unread: no second fetch",
    async (_name, render) => {
      get.mockClear();
      const client = new QueryClient();
      const wrap = wrapper(client);
      renderHook(() => useMessageDetail("f1", "m1"), { wrapper: wrap });
      await waitFor(() => expect(get).toHaveBeenCalledTimes(1));
      // "Mark unread" updates the open copy in place (messages.ts), as here.
      client.setQueryData(messageQueryKey("f1", "m1"), { ...READ, read_at: null });
      const mutate = render(wrap);
      await act(async () => {
        await mutate();
      });
      expect(isStale(client, "f1", "m1")).toBe(false);
      expect(get).toHaveBeenCalledTimes(1);
    },
  );

  it.each(ACTIONS)("%s leaves an open draft alone", async (_name, render) => {
    const client = new QueryClient();
    client.setQueryData(messageQueryKey("f1", "d1"), {
      id: "d1",
      direction: "outbound",
      read_at: null,
      attachments: [],
    });
    const mutate = render(wrapper(client));
    await act(async () => {
      await mutate();
    });
    expect(isStale(client, "f1", "d1")).toBe(false);
  });
});
