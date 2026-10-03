// @vitest-environment jsdom
/**
 * LP-957 — moving a condition to Ready to send refreshes the lender-package panel. Before, the panel's
 * query had its own key, so a status move refreshed the list and left "Build package" hidden.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/client", () => ({
  apiClient: {
    post: vi.fn(async () => ({ data: { id: "c1" } })),
    get: vi.fn(async () => ({ data: null })),
  },
}));

import { conditionPackageQueryKey, conditionsQueryPrefix, usePrepStatus } from "./conditions";

function wrapper(client: QueryClient) {
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
}

describe("the package panel follows the conditions", () => {
  it("a status move marks the package stale (the path she used)", async () => {
    const client = new QueryClient();
    client.setQueryData(conditionPackageQueryKey("f1"), { ready_count: 0 });
    const { result } = renderHook(() => usePrepStatus("f1"), { wrapper: wrapper(client) });
    expect(client.getQueryState(conditionPackageQueryKey("f1"))?.isInvalidated).toBe(false);
    await act(async () => {
      await result.current.mutateAsync({
        conditionId: "c1",
        to: "ready",
        waiting_on: null,
        expected_updated_at: "2026-10-02T00:00:00Z",
      });
    });
    expect(client.getQueryState(conditionPackageQueryKey("f1"))?.isInvalidated).toBe(true);
  });

  it("any refresh of the file's conditions covers the package, and another file's does not", async () => {
    const client = new QueryClient();
    client.setQueryData(conditionPackageQueryKey("f1"), { ready_count: 0 });
    client.setQueryData(conditionPackageQueryKey("f2"), { ready_count: 0 });
    await client.invalidateQueries({ queryKey: conditionsQueryPrefix("f1") });
    expect(client.getQueryState(conditionPackageQueryKey("f1"))?.isInvalidated).toBe(true);
    expect(client.getQueryState(conditionPackageQueryKey("f2"))?.isInvalidated).toBe(false);
  });
});
