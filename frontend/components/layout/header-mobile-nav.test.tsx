// @vitest-environment jsdom
/**
 * A file must be navigable below `md`.
 *
 * LP-UI-016 removed the file's tab strip, which was the mobile affordance, and
 * the context column that replaced it is `hidden md:block`. Between the two you
 * could open a file on a phone and have no way to reach Documents or
 * Verification at all — not a narrow-width polish item but a route becoming
 * unreachable, so the header's menu carries the column's items where the column
 * cannot be.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const pathname = vi.hoisted(() => ({ current: "/dashboard" }));
vi.mock("next/navigation", () => ({ usePathname: () => pathname.current }));
vi.mock("@/lib/stores/auth-store", () => ({
  useAuthStore: (selector: (s: unknown) => unknown) =>
    selector({ user: { first_name: "Pat", last_name: "P", email: "p@a.com", role: "processor" } }),
}));
vi.mock("@/components/layout/user-menu", () => ({ UserMenu: () => null }));
vi.mock("@/components/layout/breadcrumb", () => ({ Breadcrumb: () => null }));

import { Header } from "./header";

afterEach(() => {
  cleanup();
  pathname.current = "/dashboard";
});

function openMenu() {
  render(<Header />);
  fireEvent.pointerDown(
    screen.getByRole("button", { name: /open navigation menu/i }),
    new MouseEvent("pointerdown", { bubbles: true }),
  );
  return screen.queryAllByRole("menuitem").map((el) => el.textContent ?? "");
}

describe("the header's mobile navigation", () => {
  it("reaches every file section from inside a file", () => {
    pathname.current = "/loan-files/LF-1234/documents";
    const items = openMenu().join("|");
    for (const label of ["Overview", "Documents", "Verification", "Conditions"]) {
      expect(items, `${label} is unreachable below md`).toContain(label);
    }
  });

  it("still offers the top-level destinations", () => {
    pathname.current = "/loan-files/LF-1234";
    expect(openMenu().join("|")).toContain("Dashboard");
  });

  it("adds nothing on a route whose column is not a link list", () => {
    // The dashboard's column is saved views, whose `items` are empty — there is
    // nothing to mirror, and a bare section heading would be worse than nothing.
    pathname.current = "/dashboard";
    const items = openMenu();
    // Asserted alongside a POSITIVE: a not-toContain passes just as well when
    // the menu never opened, which is how a broken probe reads as a feature.
    expect(items.join("|")).toContain("Dashboard");
    expect(items.join("|")).not.toContain("Documents");
  });

  it("marks the section you are actually in, and only it", () => {
    pathname.current = "/loan-files/LF-1234/documents";
    render(<Header />);
    fireEvent.pointerDown(
      screen.getByRole("button", { name: /open navigation menu/i }),
      new MouseEvent("pointerdown", { bubbles: true }),
    );
    const current = screen
      .queryAllByRole("menuitem")
      .filter((el) => el.querySelector('[aria-current="page"]') ?? el.getAttribute("aria-current"))
      .map((el) => el.textContent ?? "");
    expect(current.filter((t) => t.includes("Documents"))).toHaveLength(1);
    expect(current.filter((t) => t.includes("Overview"))).toHaveLength(0);
  });
});
