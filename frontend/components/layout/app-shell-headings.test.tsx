// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const pathname = vi.hoisted(() => ({ value: "/dashboard" }));
vi.mock("next/navigation", () => ({
  usePathname: () => pathname.value,
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));
vi.mock("@/lib/api/loan-files", () => ({
  useLoanFile: () => ({ data: null }),
  useLoanFiles: () => ({ data: null, isPending: false, isError: false }),
}));

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { AppShell } from "./app-shell";

afterEach(cleanup);

function Boom(): never {
  throw new Error("this screen crashed");
}

/**
 * The heading count of the COMPOSED page (LP-UI-036 review).
 *
 * The fix lives in `ErrorBoundary`, and the bug lives in how `AppShell` wires it.
 * A test on the fallback alone passes with the shell still asking for an `h1` —
 * verified by removing `headingLevel={2}` here, which left every other test in
 * the suite green.
 */
describe("AppShell when a screen crashes", () => {
  it("still has exactly one h1", () => {
    // React logs the caught error; the boundary is doing its job.
    const quiet = vi.spyOn(console, "error").mockImplementation(() => {});
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <AppShell>
          <Boom />
        </AppShell>
      </QueryClientProvider>,
    );
    quiet.mockRestore();

    expect(screen.getByText(/stopped working/i)).toBeDefined();
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
  });
});
