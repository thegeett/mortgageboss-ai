// @vitest-environment jsdom
/** LP-952 — the reading hook refetches the plan and the conditions when a running reading ends. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  reading: { state: "reading", unread: 6, error: null } as Record<string, unknown>,
  post: undefined as undefined | (() => Promise<unknown>),
}));
vi.mock("@/lib/api/client", () => ({
  apiClient: {
    get: vi.fn(async () => ({ data: api.reading })),
    post: vi.fn(async () => (api.post ? api.post() : { data: {} })),
    put: vi.fn(async () => ({ data: {} })),
  },
}));

import { apiClient } from "@/lib/api/client";
import {
  READING_POLL_MS,
  readingStateQueryKey,
  useAttachPdf,
  useReadAgain,
  useReadingState,
  useSetFileLender,
} from "./conditions";

function setup(client: QueryClient) {
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
}

afterEach(() => {
  vi.useRealTimers();
  vi.mocked(apiClient.get).mockClear();
  api.reading = { state: "reading", unread: 6, error: null };
  api.post = undefined;
});

describe("useReadingState", () => {
  it("refetches the plan and the conditions when reading becomes done, and not before", async () => {
    const client = new QueryClient();
    client.setQueryData(readingStateQueryKey("r2"), { state: "reading", unread: 6, error: null });
    const spy = vi.spyOn(client, "invalidateQueries");
    const { result } = renderHook(() => useReadingState("r2", "f1"), { wrapper: setup(client) });
    // Let the mount's own fetch settle first ("reading"), so it cannot overwrite the change below.
    await waitFor(() => expect(result.current.isFetching).toBe(false));
    expect(result.current.data?.state).toBe("reading");
    expect(spy).not.toHaveBeenCalled();

    await act(async () => {
      client.setQueryData(readingStateQueryKey("r2"), { state: "done", unread: 0, error: null });
    });
    await waitFor(() => expect(spy).toHaveBeenCalledWith({ queryKey: ["condition-round-plan"] }));
    expect(spy).toHaveBeenCalledWith({ queryKey: ["conditions", "f1"] });
  });

  it("starts polling again after Read conditions, from a state that did not poll (review)", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    api.reading = { state: "not_queued", unread: 6, error: null };
    const client = new QueryClient();
    const wrapper = setup(client);
    const { result } = renderHook(
      () => ({ s: useReadingState("r2", "f1"), r: useReadAgain("f1") }),
      {
        wrapper,
      },
    );
    await waitFor(() => expect(result.current.s.data?.state).toBe("not_queued"));
    // The positive control: not_queued does not poll.
    const idle = vi.mocked(apiClient.get).mock.calls.length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(READING_POLL_MS * 2);
    });
    expect(vi.mocked(apiClient.get).mock.calls.length).toBe(idle);

    api.post = async () => ({ data: { state: "queued", unread: 6, error: null } });
    api.reading = { state: "reading", unread: 6, error: null };
    await act(async () => {
      result.current.r.mutate("r2");
    });
    await waitFor(() => expect(result.current.s.data?.state).toBe("queued"));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(READING_POLL_MS + 100);
    });
    await waitFor(() => expect(result.current.s.data?.state).toBe("reading"));
    expect(vi.mocked(apiClient.get).mock.calls.length).toBeGreaterThan(idle);
  });

  it("refetches the reading state when Read again is refused (review)", async () => {
    const client = new QueryClient();
    const spy = vi.spyOn(client, "invalidateQueries");
    api.post = async () => {
      throw new Error("409");
    };
    const { result } = renderHook(() => useReadAgain("f1"), { wrapper: setup(client) });
    await act(async () => {
      result.current.mutate("r2");
    });
    await waitFor(() => expect(spy).toHaveBeenCalledWith({ queryKey: readingStateQueryKey("r2") }));
  });

  it("refetches the reading state when the lender is set, which queues a reading (review)", async () => {
    const client = new QueryClient();
    const spy = vi.spyOn(client, "invalidateQueries");
    const { result } = renderHook(() => useSetFileLender("f1"), { wrapper: setup(client) });
    await act(async () => {
      result.current.mutate({ lender_key: "uwm" });
    });
    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith({ queryKey: ["condition-reading-state"] }),
    );
  });

  it("refetches the reading state when a PDF is attached, which can add unread conditions (review)", async () => {
    const client = new QueryClient();
    const spy = vi.spyOn(client, "invalidateQueries");
    api.post = async () => ({ data: { round_id: "r2" } });
    const { result } = renderHook(() => useAttachPdf("f1"), { wrapper: setup(client) });
    await act(async () => {
      result.current.mutate({ roundId: "r2", file: new File(["x"], "sheet.pdf") });
    });
    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith({ queryKey: ["condition-reading-state"] }),
    );
  });
});
