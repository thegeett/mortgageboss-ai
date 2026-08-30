// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const pathname = vi.hoisted(() => ({ current: "/dashboard" }));
vi.mock("next/navigation", () => ({ usePathname: () => pathname.current }));

import { ContextColumn } from "./context-column";

afterEach(cleanup);

function renderAt(path: string) {
  pathname.current = path;
  render(<ContextColumn />);
}

/** Every link the column marks as the current page. */
function currentLinks(): string[] {
  return screen
    .queryAllByRole("link")
    .filter((a) => a.getAttribute("aria-current") === "page")
    .map((a) => a.textContent ?? "");
}

describe("ContextColumn", () => {
  it("marks exactly ONE link as the current page inside a file", () => {
    // The column computed `active` per item with isActivePath, so on a child
    // route the section index ("Overview", /loan-files/<id>) matched as well as
    // the child — two links carrying aria-current="page", which a screen reader
    // announces as two current pages and which reads as two selected rows.
    renderAt("/loan-files/abc/documents");
    expect(currentLinks()).toEqual(["Documents"]);
  });

  it("marks Overview when you are actually on the file's index", () => {
    renderAt("/loan-files/abc");
    expect(currentLinks()).toEqual(["Overview"]);
  });

  it("marks exactly one in Administration, which has the same shape", () => {
    renderAt("/admin/lenders");
    expect(currentLinks()).toEqual(["Lenders"]);
  });

  it("never marks more than one, on any file section", () => {
    for (const section of ["", "/documents", "/verification", "/conditions"]) {
      cleanup();
      renderAt(`/loan-files/abc${section}`);
      expect(currentLinks(), `two current pages on ${section || "/"}`).toHaveLength(1);
    }
  });

  it("renders nothing on a route with no section", () => {
    renderAt("/dev/extraction-bench");
    expect(screen.queryAllByRole("link")).toHaveLength(0);
  });
});
