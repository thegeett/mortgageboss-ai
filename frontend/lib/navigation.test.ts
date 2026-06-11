import { isActivePath, visibleNavItems } from "@/lib/navigation";
import { describe, expect, it } from "vitest";

describe("visibleNavItems", () => {
  it("shows processors only the non-gated items (Dashboard, Loan Files)", () => {
    const labels = visibleNavItems("processor").map((item) => item.label);
    expect(labels).toEqual(["Dashboard", "Loan Files"]);
    expect(labels).not.toContain("Administration");
  });

  it("shows admins the admin-gated item too", () => {
    const labels = visibleNavItems("admin").map((item) => item.label);
    expect(labels).toContain("Administration");
    expect(labels).toEqual(["Dashboard", "Loan Files", "Administration"]);
  });

  it("hides role-gated items when the role is unknown", () => {
    const labels = visibleNavItems(undefined).map((item) => item.label);
    expect(labels).toEqual(["Dashboard", "Loan Files"]);
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
