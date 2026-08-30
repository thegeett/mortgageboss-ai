// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const pathname = vi.hoisted(() => ({ current: "/dashboard" }));
vi.mock("next/navigation", () => ({
  usePathname: () => pathname.current,
  // LP-UI-014: the column reads `?view` on the pipeline to mark the active
  // saved view. Every path these tests use is a file or admin route, so the
  // saved-views branch never renders here — the mock only has to exist.
  useSearchParams: () => new URLSearchParams(),
}));

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

describe("the rail's current-destination marker", () => {
  async function renderRail(path: string) {
    const { IconRail } = await import("@/components/layout/icon-rail");
    const { TooltipProvider } = await import("@/components/ui/tooltip");
    pathname.current = path;
    render(
      <TooltipProvider>
        <IconRail collapsed={false} onToggleContext={() => {}} />
      </TooltipProvider>,
    );
    return screen
      .queryAllByRole("link")
      .filter((a) => a.getAttribute("aria-current") === "page")
      .map((a) => a.getAttribute("aria-label"));
  }

  it("marks Dashboard while you are inside a file", async () => {
    // Asserted on the RAIL, not only on the helper: testing `isNavItemActive`
    // alone leaves the component free to go on calling `isActivePath(item.href)`
    // and nothing notices. That is the wiring, and the wiring is what regressed.
    expect(await renderRail("/loan-files/abc/documents")).toEqual(["Dashboard"]);
  });

  it("marks Dashboard on the dashboard itself", async () => {
    expect(await renderRail("/dashboard")).toEqual(["Dashboard"]);
  });
});

describe("the rail's sidebar toggle", () => {
  // A disclosure button that discloses nothing is a control that lies. Both the
  // button and ⌘B are gated on there being a column.
  //
  // LP-UI-014 note: this used to point at /dashboard, which had no section after
  // LP-UI-011 removed the one-item pipeline column. The dashboard has a real
  // column again — saved views — so the assertion moved to a route that still
  // genuinely has none. The property being tested is unchanged; only the example
  // of a column-less route is.
  it("is not rendered where there is no context column", async () => {
    const { IconRail } = await import("@/components/layout/icon-rail");
    const { TooltipProvider } = await import("@/components/ui/tooltip");
    pathname.current = "/dev/extraction-bench";
    render(
      <TooltipProvider>
        <IconRail collapsed={false} onToggleContext={() => {}} />
      </TooltipProvider>,
    );
    expect(screen.queryByRole("button", { name: /toggle the context column/i })).toBeNull();
  });

  it("IS rendered on the dashboard, which has saved views (LP-UI-014)", async () => {
    const { IconRail } = await import("@/components/layout/icon-rail");
    const { TooltipProvider } = await import("@/components/ui/tooltip");
    pathname.current = "/dashboard";
    render(
      <TooltipProvider>
        <IconRail collapsed={false} onToggleContext={() => {}} />
      </TooltipProvider>,
    );
    expect(screen.queryByRole("button", { name: /toggle the context column/i })).not.toBeNull();
  });

  it("is rendered inside a file, where there is one", async () => {
    const { IconRail } = await import("@/components/layout/icon-rail");
    const { TooltipProvider } = await import("@/components/ui/tooltip");
    pathname.current = "/loan-files/abc/documents";
    render(
      <TooltipProvider>
        <IconRail collapsed={false} onToggleContext={() => {}} />
      </TooltipProvider>,
    );
    expect(screen.queryByRole("button", { name: /toggle the context column/i })).not.toBeNull();
  });
});
