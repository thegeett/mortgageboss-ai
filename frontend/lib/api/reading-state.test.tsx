// @vitest-environment jsdom
/** LP-952 — the reading hook refetches the plan and the conditions when a running reading ends. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/client", () => ({
  apiClient: { get: vi.fn(async () => ({ data: { state: "reading", unread: 6, error: null } })) },
}));

import { readingStateQueryKey, useReadingState } from "./conditions";

describe("useReadingState", () => {
  it("refetches the plan and the conditions when reading becomes done, and not before", async () => {
    const client = new QueryClient();
    client.setQueryData(readingStateQueryKey("r2"), { state: "reading", unread: 6, error: null });
    const spy = vi.spyOn(client, "invalidateQueries");
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    const { result } = renderHook(() => useReadingState("r2", "f1"), { wrapper });
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
});
