import { FILE_TABS, activeTabKey, tabHref } from "@/lib/loan-files/tabs";
import { describe, expect, it } from "vitest";

describe("activeTabKey", () => {
  it("a bare file path is the Overview tab", () => {
    expect(activeTabKey("/loan-files/LF-AB12")).toBe("overview");
  });

  it("a tab sub-route resolves to that tab", () => {
    expect(activeTabKey("/loan-files/LF-AB12/documents")).toBe("documents");
    expect(activeTabKey("/loan-files/LF-AB12/lender-package")).toBe("lender-package");
  });

  it("an unknown trailing segment falls back to Overview", () => {
    expect(activeTabKey("/loan-files/LF-AB12/nope")).toBe("overview");
  });
});

describe("tabHref", () => {
  it("Overview → the bare file path", () => {
    expect(tabHref("LF-AB12", "")).toBe("/loan-files/LF-AB12");
  });

  it("a tab → its sub-route", () => {
    expect(tabHref("LF-AB12", "documents")).toBe("/loan-files/LF-AB12/documents");
  });
});

describe("FILE_TABS", () => {
  it("is overview + the five phased tabs, each non-overview declaring a phase", () => {
    expect(FILE_TABS.map((tab) => tab.key)).toEqual([
      "overview",
      "documents",
      "verification",
      "communication",
      "conditions",
      "lender-package",
    ]);
    for (const tab of FILE_TABS.filter((tab) => tab.key !== "overview")) {
      expect(tab.phase).toBeTruthy();
    }
  });
});
