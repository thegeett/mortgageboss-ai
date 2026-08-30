// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const pathname = vi.hoisted(() => ({ value: "/dashboard" }));
vi.mock("next/navigation", () => ({ usePathname: () => pathname.value }));
vi.mock("@/lib/api/loan-files", () => ({ useLoanFile: () => ({ data: null }) }));

import { Breadcrumb } from "./breadcrumb";

afterEach(() => {
  cleanup();
  pathname.value = "/dashboard";
});

/**
 * One h1 per route, and it names WHERE YOU ARE (LP-UI-036).
 *
 * Measured across every route: `/loan-files/new` had none — its branch rendered
 * the location as a plain span, so nothing announced what the page was — and the
 * dashboard had two, because the page added its own greeting as a second h1.
 * Both are answers to "where am I", and a screen reader should get exactly one.
 */
describe("Breadcrumb", () => {
  it("names the page as an h1 on a listed route", () => {
    render(<Breadcrumb fallback="Dashboard" />);
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Dashboard");
  });

  it("names the page as an h1 on the new-file route too", () => {
    // This is the one that had no h1 at all.
    pathname.value = "/loan-files/new";
    render(<Breadcrumb fallback="ignored" />);
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("New file");
  });

  it("renders exactly one h1", () => {
    pathname.value = "/loan-files/new";
    render(<Breadcrumb fallback="Dashboard" />);
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
  });

  it("keeps the way back out of the heading", () => {
    // "Pipeline" is a link, not part of the page's name. Asserted on a route
    // that HAS a trail — the dashboard is the pipeline, so it has nothing to
    // link back to and renders the heading alone.
    pathname.value = "/loan-files/new";
    render(<Breadcrumb fallback="Dashboard" />);
    expect(screen.getByRole("link", { name: "Pipeline" })).toBeTruthy();
    expect(screen.getByRole("heading", { level: 1 }).textContent).not.toContain("Pipeline");
  });
});
