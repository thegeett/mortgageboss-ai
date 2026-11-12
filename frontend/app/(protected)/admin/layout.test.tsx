// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const held = vi.hoisted(() => ({ permissions: [] as string[] }));
vi.mock("@/lib/stores/auth-store", () => ({
  useAuthStore: (selector: (s: unknown) => unknown) =>
    selector({ user: { permissions: held.permissions } }),
}));

import AdminLayout from "./layout";

afterEach(() => {
  cleanup();
  held.permissions = [];
});

describe("AdminLayout", () => {
  it("shows a loan officer the message, not the page", () => {
    held.permissions = ["borrower.invite", "loan.create", "loan.team.change"];
    render(
      <AdminLayout>
        <p>admin page</p>
      </AdminLayout>,
    );
    expect(screen.getByText("Administration is available to admins only.")).toBeTruthy();
    expect(screen.queryByText("admin page")).toBeNull();
  });

  it("renders the page for a user holding users.manage", () => {
    held.permissions = ["users.manage"];
    render(
      <AdminLayout>
        <p>admin page</p>
      </AdminLayout>,
    );
    expect(screen.getByText("admin page")).toBeTruthy();
    expect(screen.queryByText(/available to admins only/)).toBeNull();
  });
});
