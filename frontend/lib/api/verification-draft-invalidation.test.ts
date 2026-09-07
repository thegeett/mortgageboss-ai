// @vitest-environment jsdom
import { outboundDraftQueryKey } from "@/lib/api/communications";
import { useResolveFinding } from "@/lib/api/verification";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import React from "react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/client", () => ({
  apiClient: { post: vi.fn().mockResolvedValue({ data: { findings: [], blocking: [] } }) },
}));

/**
 * Requesting documents from a finding writes into the file's OPEN DRAFT (LP-809, both routes). The
 * communication page reads that draft through its own query, so the write is invisible to the
 * person who made it unless this mutation invalidates it.
 *
 * Reported on LF-JR4T from the other side: the backend never created the draft at all. Fixing only
 * the backend leaves the same empty screen for the 60s default staleTime — a processor who had the
 * communication page open, clicks Request, and goes back still sees nothing.
 */
describe("useResolveFinding — the draft the request just wrote", () => {
  it("invalidates the outbound draft, not only needs and activity", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const wrapper = ({ children }: { children: React.ReactNode }) =>
      React.createElement(QueryClientProvider, { client }, children);

    const { result } = renderHook(() => useResolveFinding("LF-JR4T"), { wrapper });
    result.current.mutate({ kind: "request-docs", findingId: "f1", note: "" });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const keys = invalidate.mock.calls.map((call) => JSON.stringify(call[0]?.queryKey));
    expect(keys).toContain(JSON.stringify(outboundDraftQueryKey("LF-JR4T")));
    // The positive control: without it, a spy that recorded nothing would satisfy nothing above
    // but would also never fail if the assertion were written the other way round.
    expect(keys).toContain(JSON.stringify(["needs", "LF-JR4T"]));
  });
});
