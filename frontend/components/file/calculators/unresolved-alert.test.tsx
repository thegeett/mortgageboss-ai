// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { UnresolvedAlert } from "./unresolved-alert";

const breakdown = (over: Partial<Record<string, number>> = {}) => ({
  governed: 0,
  cross_source: 0,
  legacy: 0,
  other: 0,
  ...over,
});

afterEach(cleanup);

describe("UnresolvedAlert", () => {
  it("names each system separately, never as one total", () => {
    // "91 unresolved findings" reconciled with nothing a processor could see.
    render(
      <UnresolvedAlert breakdown={breakdown({ governed: 75, cross_source: 3, legacy: 13 })} />,
    );
    const text = screen.getByRole("alert").textContent ?? "";
    expect(text).toContain("75 rule findings");
    expect(text).toContain("3 cross-checks");
    expect(text).toContain("13 old findings");
    expect(text).not.toContain("91");
  });

  it("renders a generator it does not know rather than hiding it", () => {
    render(<UnresolvedAlert breakdown={breakdown({ governed: 2, other: 4 })} />);
    expect(screen.getByRole("alert").textContent).toContain("4 other");
  });

  it("says nothing at all rather than a warning with no subject", () => {
    // An all-zero breakdown cannot reach here from any caller today — all three
    // derive it from the same in-scope list that sets `unresolved`. It DID reach
    // here once from a fixture that type-checked and could not occur, and
    // rendered " unresolved — this calculation may be incomplete".
    const { container } = render(<UnresolvedAlert breakdown={breakdown()} />);
    expect(container.textContent).toBe("");
  });

  it("reads as English for a single finding", () => {
    render(<UnresolvedAlert breakdown={breakdown({ governed: 1 })} />);
    expect(screen.getByRole("alert").textContent).toContain("1 rule finding unresolved");
  });
});
