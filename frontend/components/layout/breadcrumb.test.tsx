// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const pathname = vi.hoisted(() => ({ current: "/dashboard" }));
const file = vi.hoisted(() => ({ data: undefined as unknown }));
vi.mock("next/navigation", () => ({ usePathname: () => pathname.current }));
vi.mock("@/lib/api/loan-files", () => ({ useLoanFile: () => file }));
vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

import { Breadcrumb } from "./breadcrumb";

afterEach(() => {
  cleanup();
  pathname.current = "/dashboard";
  file.data = undefined;
});

describe("Breadcrumb", () => {
  it("shows the section fallback outside a file", () => {
    render(<Breadcrumb fallback="Dashboard" />);
    expect(screen.getByText("Dashboard")).toBeDefined();
    expect(screen.queryByRole("navigation", { name: /breadcrumb/i })).toBeNull();
  });

  it("shows the URL id while the file is still resolving", () => {
    // Deliberate: the id is real and already on screen, and a skeleton would
    // flicker a word into a bar and back for a query that usually hits cache.
    pathname.current = "/loan-files/LF-1234";
    render(<Breadcrumb fallback="x" />);
    expect(screen.getByText("LF-1234")).toBeDefined();
  });

  it("says 'Unnamed file' — not the id — once a nameless file resolves", () => {
    // The id fallback was for the LOADING case. Left in place after the file
    // resolved it printed the id twice on one line, beside the chip that already
    // carries it, and gave the screen two answers to what the file is called.
    // FileHeader says "Unnamed file" three feet below.
    pathname.current = "/loan-files/LF-1234";
    file.data = { display_id: "LF-1234", primary_borrower_name: null };
    render(<Breadcrumb fallback="x" />);

    expect(screen.getByText("Unnamed file")).toBeDefined();
    expect(screen.getAllByText("LF-1234")).toHaveLength(1);
  });

  it("shows the borrower and keeps the id as a chip", () => {
    pathname.current = "/loan-files/LF-1234";
    file.data = { display_id: "LF-1234", primary_borrower_name: "Mahesh Chhotala" };
    render(<Breadcrumb fallback="x" />);

    expect(screen.getByText("Mahesh Chhotala")).toBeDefined();
    expect(screen.getByText("LF-1234")).toBeDefined();
  });

  it("offers the way out", () => {
    pathname.current = "/loan-files/LF-1234";
    render(<Breadcrumb fallback="x" />);
    expect(screen.getByRole("link", { name: /pipeline/i }).getAttribute("href")).toBe("/dashboard");
  });

  it("names the new-file page and links back (LP-UI-023)", () => {
    // `/loan-files/new` is a page, not a file, so this fell through to the
    // fallback — which is the current NAV ITEM's label, and the dashboard owns
    // `/loan-files`. The topbar said "Dashboard" while a processor was creating
    // a file. It is also the only way back from that page.
    pathname.current = "/loan-files/new";
    render(<Breadcrumb fallback="Dashboard" />);
    expect(screen.getByText("New file")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Pipeline" }).getAttribute("href")).toBe("/dashboard");
    expect(screen.queryByText("Dashboard")).toBeNull();
  });
});
