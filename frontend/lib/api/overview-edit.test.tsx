// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

// The mutations PATCH through the shared client — stub it so the hook resolves.
vi.mock("@/lib/api/client", () => ({
  apiClient: { patch: vi.fn().mockResolvedValue({ data: {} }) },
}));

import { useUpdateLoanFile, useUpdateProperty } from "./overview-edit";

function wrapper(client: QueryClient) {
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
}

afterEach(() => vi.clearAllMocks());

describe("overview-edit invalidation (LP-80.5)", () => {
  // Invalidation is by key PREFIX so it matches whether a query was cached under the
  // file's UUID or the route's display_id (the cards pass the UUID).
  it("a property edit refreshes the file + coupled DTI / LTV / verification queries", async () => {
    const qc = new QueryClient();
    const spy = vi.spyOn(qc, "invalidateQueries");
    const { result } = renderHook(() => useUpdateProperty("LF-1"), { wrapper: wrapper(qc) });

    result.current.mutate({ city: "Austin" });

    await waitFor(() => expect(spy).toHaveBeenCalledWith({ queryKey: ["verification"] }));
    expect(spy).toHaveBeenCalledWith({ queryKey: ["loan-file"] });
    expect(spy).toHaveBeenCalledWith({ queryKey: ["dti"] });
    expect(spy).toHaveBeenCalledWith({ queryKey: ["ltv"] });
  });

  it("a loan edit refreshes the same coupled queries", async () => {
    const qc = new QueryClient();
    const spy = vi.spyOn(qc, "invalidateQueries");
    const { result } = renderHook(() => useUpdateLoanFile("LF-1"), { wrapper: wrapper(qc) });

    result.current.mutate({ lender_id: "L1" });

    await waitFor(() => expect(spy).toHaveBeenCalledWith({ queryKey: ["dti"] }));
    expect(spy).toHaveBeenCalledWith({ queryKey: ["ltv"] });
    expect(spy).toHaveBeenCalledWith({ queryKey: ["verification"] });
    expect(spy).toHaveBeenCalledWith({ queryKey: ["loan-file"] });
    // LP-949 review: a lender edit reaches the Conditions tab's banner and lists.
    expect(spy).toHaveBeenCalledWith({ queryKey: ["condition-file-lender"] });
    expect(spy).toHaveBeenCalledWith({ queryKey: ["conditions"] });
  });

  it("an edit that does not name the lender leaves the conditions alone (LP-949 review)", async () => {
    const qc = new QueryClient();
    const spy = vi.spyOn(qc, "invalidateQueries");
    const { result } = renderHook(() => useUpdateLoanFile("LF-1"), { wrapper: wrapper(qc) });

    result.current.mutate({ loan_amount: "1" });

    await waitFor(() => expect(spy).toHaveBeenCalledWith({ queryKey: ["loan-file"] }));
    expect(spy).not.toHaveBeenCalledWith({ queryKey: ["condition-file-lender"] });
  });
});
