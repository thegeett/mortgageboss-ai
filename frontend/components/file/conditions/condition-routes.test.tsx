// @vitest-environment jsdom
/** LP-955 — the ways a condition gets done at its lender, offered as a choice. */
import type { Condition } from "@/lib/types/conditions";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const calls = vi.hoisted(() => ({ choose: [] as unknown[] }));
vi.mock("@/lib/api/conditions", () => ({
  useChooseRoute: () => ({ isPending: false, mutate: (b: unknown) => calls.choose.push(b) }),
}));

import { ConditionRoutes } from "./condition-routes";

afterEach(() => {
  cleanup();
  calls.choose = [];
});

const ROUTES = [
  { key: "lender_system", label: "Pulled in UWM's system", hint: "UWM has the invoice." },
  { key: "our_vendor", label: "Our vendor", hint: "Your task: upload the vendor's invoice." },
];

describe("ConditionRoutes", () => {
  it("offers each route, marks the chosen one, and sends her choice", () => {
    const condition = { id: "c1", routes: ROUTES, chosen_route: "lender_system" } as Condition;
    render(<ConditionRoutes fileId="f1" condition={condition} />);
    const system = screen.getByRole("button", { name: /Pulled in UWM's system/ });
    expect(system.getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(screen.getByRole("button", { name: /Our vendor/ }));
    expect(calls.choose).toEqual([{ conditionId: "c1", route: "our_vendor" }]);
  });

  it("renders nothing for a condition with no routes", () => {
    const condition = { id: "c1", routes: [], chosen_route: null } as unknown as Condition;
    const { container } = render(<ConditionRoutes fileId="f1" condition={condition} />);
    expect(container.innerHTML).toBe("");
  });
});
