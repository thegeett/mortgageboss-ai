// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const useNeedsMock = vi.fn();
vi.mock("@/lib/api/needs", () => ({ useNeeds: () => useNeedsMock() }));
// Count outstanding via the real helper, but stub its module-free dependency surface.
vi.mock("@/lib/loan-files/needs", () => ({
  outstandingNeedsCount: (needs: { outstanding?: boolean }[]) =>
    needs.filter((n) => n.outstanding).length,
}));

import { NeedsCompleteness } from "./needs-completeness";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("NeedsCompleteness — the false-confidence guard", () => {
  it("shows the outstanding count + 'may be incomplete' message", () => {
    useNeedsMock.mockReturnValue({ data: [{ outstanding: true }, { outstanding: true }] });
    render(<NeedsCompleteness fileId="LF-1" />);
    expect(screen.getByText(/2 outstanding document needs/)).toBeDefined();
    expect(screen.getByText(/results may be incomplete/)).toBeDefined();
  });

  it("renders nothing when no documents are outstanding (sparse = genuinely clean)", () => {
    useNeedsMock.mockReturnValue({ data: [{ outstanding: false }] });
    const { container } = render(<NeedsCompleteness fileId="LF-1" />);
    expect(container.firstChild).toBeNull();
  });

  it("renders nothing while needs are still loading", () => {
    useNeedsMock.mockReturnValue({ data: undefined });
    const { container } = render(<NeedsCompleteness fileId="LF-1" />);
    expect(container.firstChild).toBeNull();
  });
});
