// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type React from "react";
import { describe, expect, it, vi } from "vitest";

const post = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/client", () => ({ apiClient: { post } }));

import { useAddProcessor } from "./loan-teams";

describe("team changes refresh what they change (LP-MB-Admin-05 review, finding 7)", () => {
  it("marks the file's timeline stale, along with the file and its lists", async () => {
    post.mockResolvedValue({ data: { loan_officer: null, processors: [], can_change: true } });
    const client = new QueryClient();
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    const { result } = renderHook(() => useAddProcessor("LF-1"), { wrapper });

    await act(() => result.current.mutateAsync("u-1"));

    const keys = invalidate.mock.calls.map((call) => JSON.stringify(call[0]?.queryKey));
    expect(keys).toContain(JSON.stringify(["loan-file-activity", "LF-1"]));
    expect(keys).toContain(JSON.stringify(["loan-file", "LF-1"]));
  });
});
