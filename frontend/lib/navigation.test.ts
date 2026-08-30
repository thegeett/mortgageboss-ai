import {
  NAV_ITEMS,
  activeItemHref,
  contextSection,
  fileTabSegment,
  isActivePath,
  isNavItemActive,
  visibleNavItems,
} from "@/lib/navigation";
import { describe, expect, it } from "vitest";

describe("visibleNavItems", () => {
  it("shows processors only the non-gated item (Dashboard)", () => {
    const labels = visibleNavItems("processor").map((item) => item.label);
    // "Loan Files" was removed in LP-UI-011: it pointed at a stub, and the
    // dashboard is the list. /loan-files now redirects here.
    expect(labels).toEqual(["Dashboard"]);
    expect(labels).not.toContain("Loan Files");
    expect(labels).not.toContain("Administration");
  });

  it("shows admins the admin-gated item too", () => {
    const labels = visibleNavItems("admin").map((item) => item.label);
    expect(labels).toContain("Administration");
    expect(labels).toEqual(["Dashboard", "Administration"]);
  });

  it("hides role-gated items when the role is unknown", () => {
    const labels = visibleNavItems(undefined).map((item) => item.label);
    expect(labels).toEqual(["Dashboard"]);
  });
});

describe("isActivePath", () => {
  it("matches the exact path", () => {
    expect(isActivePath("/dashboard", "/dashboard")).toBe(true);
  });

  it("matches a nested child route", () => {
    expect(isActivePath("/loan-files/abc-123", "/loan-files")).toBe(true);
  });

  it("does not match an unrelated or prefix-colliding route", () => {
    expect(isActivePath("/loan-files", "/dashboard")).toBe(false);
    expect(isActivePath("/loan-files-archive", "/loan-files")).toBe(false);
  });
});

describe("activeItemHref", () => {
  // `isActivePath` per item marked BOTH the section index and the child you are
  // actually on as `aria-current="page"` — two current pages announced, two rows
  // reading as selected. The longest match is the specific one.
  const fileHrefs = [
    "/loan-files/abc",
    "/loan-files/abc/documents",
    "/loan-files/abc/verification",
  ];
  // The same set with the index LAST. Any "first/last match wins" implementation
  // gives a different answer for one of these two orders; only "longest match"
  // gives the same answer for both, which is what makes this pair a real check.
  const reordered = [...fileHrefs.slice(1), "/loan-files/abc"];

  it("picks the child over the section index", () => {
    expect(activeItemHref("/loan-files/abc/documents", fileHrefs)).toBe(
      "/loan-files/abc/documents",
    );
  });

  it("picks the index when you are actually on it", () => {
    expect(activeItemHref("/loan-files/abc", fileHrefs)).toBe("/loan-files/abc");
  });

  it("marks exactly one item, never two", () => {
    for (const pathname of ["/loan-files/abc", ...fileHrefs.slice(1)]) {
      const current = activeItemHref(pathname, fileHrefs);
      expect(fileHrefs.filter((href) => href === current)).toHaveLength(1);
    }
  });

  it("handles Administration, which has the same index-plus-children shape", () => {
    const admin = ["/admin", "/admin/lenders", "/admin/validation"];
    expect(activeItemHref("/admin/lenders", admin)).toBe("/admin/lenders");
    expect(activeItemHref("/admin", admin)).toBe("/admin");
  });

  it("does not depend on the order the items are declared in", () => {
    expect(activeItemHref("/loan-files/abc/documents", reordered)).toBe(
      "/loan-files/abc/documents",
    );
    expect(activeItemHref("/loan-files/abc", reordered)).toBe("/loan-files/abc");
  });

  it("returns null when nothing matches", () => {
    expect(activeItemHref("/dashboard", fileHrefs)).toBeNull();
  });
});

describe("contextSection", () => {
  it("shows a file's sections inside a file", () => {
    expect(contextSection("/loan-files/abc/documents")?.title).toBe("File");
  });

  it("treats /loan-files/new as NOT a file", () => {
    // `new` is the only non-id segment under /loan-files today; every other child
    // of the route group lives under [id]. It resolves to no section rather than
    // to "File" — the pipeline section went with the stub in LP-UI-011, and its
    // replacement is LP-UI-012's saved views.
    expect(contextSection("/loan-files/new")).toBeNull();
  });

  it("shows nothing on a route with no section", () => {
    expect(contextSection("/dev/extraction-bench")).toBeNull();
  });
});

describe("fileTabSegment", () => {
  // `pathname.endsWith("/documents")` answered this by matching the END of the
  // whole path — true for any route finishing with the same word however deeply
  // nested, and false for a trailing slash. This anchors to the file's base.
  it("names the section you are in", () => {
    expect(fileTabSegment("/loan-files/abc/documents")).toBe("documents");
    expect(fileTabSegment("/loan-files/abc/verification")).toBe("verification");
  });

  it("returns null on the file's own index", () => {
    expect(fileTabSegment("/loan-files/abc")).toBeNull();
  });

  it("tolerates a trailing slash", () => {
    expect(fileTabSegment("/loan-files/abc/documents/")).toBe("documents");
    expect(fileTabSegment("/loan-files/abc/")).toBeNull();
  });

  it("names the SECTION, not the last segment", () => {
    // A deeper route under a section still belongs to that section, and one that
    // merely ends with the same word does not belong to it at all.
    expect(fileTabSegment("/loan-files/abc/documents/xyz")).toBe("documents");
    expect(fileTabSegment("/loan-files/abc/conditions/documents")).toBe("conditions");
  });

  it("returns null outside a file", () => {
    expect(fileTabSegment("/loan-files")).toBeNull();
    expect(fileTabSegment("/loan-files/new")).toBeNull();
    expect(fileTabSegment("/admin/lenders")).toBeNull();
  });
});

describe("isNavItemActive", () => {
  const dashboard = NAV_ITEMS.find((item) => item.href === "/dashboard");
  if (!dashboard) throw new Error("the Dashboard rail item is gone");

  it("marks Dashboard while you are inside a file", () => {
    // LP-UI-011 removed the "Loan Files" rail item, which was the only thing
    // marking the rail in the file workspace — so the rail showed NOTHING
    // current on the screen the product is mostly used on, and the header fell
    // back to the wordmark. The dashboard IS the loan-file list (ADR-390), so a
    // file is inside its territory.
    expect(isNavItemActive("/loan-files/abc", dashboard)).toBe(true);
    expect(isNavItemActive("/loan-files/abc/documents", dashboard)).toBe(true);
  });

  it("still marks it on its own route", () => {
    expect(isNavItemActive("/dashboard", dashboard)).toBe(true);
  });

  it("does not reach routes it merely prefixes", () => {
    expect(isNavItemActive("/loan-files-archive", dashboard)).toBe(false);
    expect(isNavItemActive("/admin/lenders", dashboard)).toBe(false);
  });

  it("leaves an item with no `owns` exactly as before", () => {
    const admin = NAV_ITEMS.find((item) => item.href === "/admin");
    if (!admin) throw new Error("the Administration rail item is gone");
    expect(isNavItemActive("/admin/lenders", admin)).toBe(true);
    expect(isNavItemActive("/loan-files/abc", admin)).toBe(false);
  });
});
