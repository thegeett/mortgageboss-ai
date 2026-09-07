// @vitest-environment jsdom
/**
 * LP-UI-012's named criterion, pinned: the two notices are RAILS, not fills.
 *
 * The ticket shipped with no test at all, which left the one property it exists
 * for unasserted — and asserted on the RENDERED form rather than on a class-name
 * constant, so a component that stops using the constant is still caught.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const params = vi.hoisted(() => ({ current: new URLSearchParams() }));
const routerReplace = vi.hoisted(() => vi.fn());
const loginFn = vi.hoisted(() => vi.fn());
const authed = vi.hoisted(() => ({ current: false }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: routerReplace, push: vi.fn() }),
  useSearchParams: () => params.current,
}));
vi.mock("@/lib/api/auth", () => ({ login: loginFn }));
vi.mock("@/lib/stores/auth-store", () => ({ useIsAuthenticated: () => authed.current }));

import { LoginForm } from "./login-form";

beforeEach(() => {
  params.current = new URLSearchParams();
  authed.current = false;
  loginFn.mockReset();
  loginFn.mockResolvedValue(undefined);
  routerReplace.mockReset();
});
afterEach(cleanup);

/**
 * The form's own inputs, by name.
 *
 * NOT `getByLabelText(/password/i)` — that also matches the reveal button's
 * accessible name, so the change lands on a <button> and the field stays empty.
 * The symptom is a silent validation failure, which reads as "submit is broken".
 */
function fillCredentials(
  container: HTMLElement,
  email = "pat@acme.com",
  password = "hunter2", // pragma: allowlist secret — an invented value for a fake form
) {
  const emailInput = container.querySelector<HTMLInputElement>('input[name="email"]');
  const passwordInput = container.querySelector<HTMLInputElement>('input[name="password"]');
  if (!emailInput || !passwordInput) throw new Error("the login form lost a credential field");
  fireEvent.change(emailInput, { target: { value: email } });
  fireEvent.change(passwordInput, { target: { value: password } });
}

/**
 * Which lucide icon this is — `lucide-triangle-alert`, not its whole class list.
 *
 * Comparing the full `class` attribute is what a first version did, and it
 * compares the COLOUR too: two notices wearing the same glyph in different tones
 * have different class strings, so the assertion passed on exactly the state it
 * exists to forbid.
 */
function glyphName(svg: Element | null): string {
  const match = /\blucide-([a-z-]+)\b/.exec(svg?.getAttribute("class") ?? "");
  return match?.[1] ?? "";
}

/** A notice is a rail when it carries a 2px left border and NO tinted fill. */
function expectRail(el: HTMLElement, tone: "warning" | "destructive") {
  const classes = el.className;
  expect(classes, "a rail is a 2px left border").toContain("border-l-2");
  expect(classes, `the rail carries the ${tone} tone`).toContain(`border-l-${tone}`);
  // SPEC rule 5: state goes on the rail and the glyph, never on a background
  // fill. Fills stack badly and cost text contrast — that is the change this
  // ticket made, and the thing a later "let's make the error stand out" would
  // quietly undo.
  expect(classes, "a fill is what the rail replaced").not.toMatch(
    /\bbg-(warning|destructive|danger|success|info)\b/,
  );
}

describe("LoginForm notices", () => {
  it("shows the expired-session notice as a rail, not a filled box", () => {
    params.current = new URLSearchParams("reason=session_expired");
    render(<LoginForm />);
    expectRail(screen.getByText(/session expired/i).closest("output") as HTMLElement, "warning");
  });

  it("shows a failed sign-in as a rail, not a filled box", async () => {
    loginFn.mockRejectedValue(new Error("nope"));
    const { container } = render(<LoginForm />);
    fillCredentials(container);
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    const alert = await screen.findByRole("alert");
    expectRail(alert, "destructive");
  });

  it("keeps the live-region semantics the visual change did not touch", () => {
    // The rail is a paint change; `output` (an implicit polite status) and
    // role="alert" are what a screen reader actually reads, and they are
    // unchanged. Pinned because "make it quieter" is a visual instinct that
    // reaches for the markup.
    params.current = new URLSearchParams("reason=session_expired");
    render(<LoginForm />);
    expect(screen.getByText(/session expired/i).closest("output")).not.toBeNull();
  });

  it("gives the two notices DIFFERENT glyph shapes, not just different colours", async () => {
    // Both notices used AlertCircle before this ticket, so colour alone told
    // them apart — which SPEC rule 4 forbids and roughly 1 in 12 men cannot use.
    // The ticket fixed it without naming it; this is what keeps it fixed.
    params.current = new URLSearchParams("reason=session_expired");
    const { container } = render(<LoginForm />);
    const expiredGlyph = glyphName(container.querySelector("output svg"));

    cleanup();
    params.current = new URLSearchParams();
    loginFn.mockRejectedValue(new Error("nope"));
    const second = render(<LoginForm />);
    fillCredentials(second.container);
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));
    await screen.findByRole("alert");
    const errorGlyph = glyphName(second.container.querySelector('[role="alert"] svg'));

    expect(expiredGlyph).not.toBe("");
    expect(errorGlyph).not.toBe("");
    expect(expiredGlyph, "same glyph would leave colour as the only channel").not.toBe(errorGlyph);
  });
});

describe("LoginForm submission", () => {
  it("signs in with the entered credentials", async () => {
    // The flow the rewrite never exercised: the page was verified by rendering
    // it, not by submitting through it.
    const { container } = render(<LoginForm />);
    fillCredentials(container);
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() =>
      // Two positional arguments, which is the real signature.
      expect(loginFn).toHaveBeenCalledWith("pat@acme.com", "hunter2"),
    );
  });

  it("does not enumerate accounts on a 401", async () => {
    const { isAxiosError } = await import("axios");
    void isAxiosError;
    loginFn.mockRejectedValue(
      Object.assign(new Error("Request failed"), {
        isAxiosError: true,
        response: { status: 401 },
      }),
    );
    const { container } = render(<LoginForm />);
    fillCredentials(container);
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Invalid email or password.");
    expect(alert.textContent).not.toMatch(/no such (user|account)|not registered/i);
  });
});
