// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const held = vi.hoisted(() => ({ permissions: [] as string[] }));
vi.mock("@/lib/stores/auth-store", () => ({
  useAuthStore: (selector: (s: unknown) => unknown) =>
    selector({ user: { permissions: held.permissions } }),
}));
vi.mock("@/lib/api/overlay-admin", () => ({
  useOverlayLenders: () => ({ data: [], isPending: false, isError: false }),
}));
vi.mock("./company-settings-card", () => ({
  CompanySettingsCard: () => <p>settings card</p>,
}));

import AdminPage from "./page";

afterEach(() => {
  cleanup();
  held.permissions = [];
});

describe("AdminPage", () => {
  it("shows an admin every section", () => {
    held.permissions = ["users.manage", "overlays.manage", "company.settings.manage"];
    render(<AdminPage />);
    expect(screen.getByText("Lender overlays")).toBeTruthy();
    expect(screen.getByText("settings card")).toBeTruthy();
  });

  it("shows only the sections whose key the user holds", () => {
    held.permissions = ["users.manage", "overlays.manage"];
    render(<AdminPage />);
    expect(screen.getByText("Lender overlays")).toBeTruthy();
    expect(screen.queryByText("settings card")).toBeNull();
  });
});
