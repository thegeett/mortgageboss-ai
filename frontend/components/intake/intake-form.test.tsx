// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }));
vi.mock("@/lib/api/lenders", () => ({ useLenders: () => ({ data: [], isPending: false }) }));
const me = vi.hoisted(() => ({ user: null as unknown }));
vi.mock("@/lib/stores/auth-store", () => ({
  useAuthStore: (selector: (s: unknown) => unknown) => selector({ user: me.user }),
}));

import { IntakeForm } from "./intake-form";

afterEach(() => {
  cleanup();
  me.user = null;
});

function renderForm() {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <IntakeForm />
    </QueryClientProvider>,
  );
}

describe("IntakeForm — the loan officer fields (LP-MB-Admin-05 review, finding 6)", () => {
  it("lets a loan officer enter a broker's LO, and says blank makes them the LO", () => {
    me.user = { first_name: "Bea", last_name: "Test", roles: ["admin", "loan_officer"] };
    renderForm();
    expect(screen.getByLabelText("Loan officer name")).toBeTruthy();
    expect(screen.getByLabelText("Loan officer email")).toBeTruthy();
    expect(
      screen.getByText(/Leave blank to be this file’s loan officer yourself \(Bea Test\)/),
    ).toBeTruthy();
  });

  it("shows no such hint to someone who is not a loan officer", () => {
    me.user = { first_name: "Pat", last_name: "Test", roles: ["processor"] };
    renderForm();
    expect(screen.getByLabelText("Loan officer name")).toBeTruthy();
    expect(screen.queryByText(/Leave blank to be/)).toBeNull();
  });
});
