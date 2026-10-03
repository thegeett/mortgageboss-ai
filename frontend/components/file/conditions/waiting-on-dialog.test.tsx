// @vitest-environment jsdom
/** LP-956 — "Waiting on Processor" is never offered: her own task asks who it waits on instead. */
import type { Condition } from "@/lib/types/conditions";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { WAITING_ON_CHOICES, WaitingOnDialog, waitingOnFor } from "./waiting-on-dialog";

afterEach(cleanup);

describe("waiting on", () => {
  it("never offers the processor, and offers every other owner", () => {
    expect(WAITING_ON_CHOICES).not.toContain("processor");
    expect(WAITING_ON_CHOICES).toContain("borrower");
    expect(WAITING_ON_CHOICES).toContain("lender");
  });

  it("asks only when the owner is the processor", () => {
    expect(waitingOnFor({ effective_owner: "processor" } as Condition)).toBeNull();
    expect(waitingOnFor({ effective_owner: "title" } as Condition)).toBe("title");
  });

  it("sends the owner she chooses", () => {
    const chosen: string[] = [];
    render(
      <WaitingOnDialog
        condition={{ lender_code: "0006" } as Condition}
        open
        onOpenChange={() => undefined}
        onChoose={(owner) => chosen.push(owner)}
        refusal={null}
        pending={false}
      />,
    );
    expect(screen.getByText("Who is 0006 waiting on?")).toBeTruthy();
    const options = Array.from((screen.getByLabelText("Waiting on") as HTMLSelectElement).options);
    expect(options.map((o) => o.value)).not.toContain("processor");
    fireEvent.change(screen.getByLabelText("Waiting on"), { target: { value: "broker" } });
    fireEvent.click(screen.getByRole("button", { name: "Move to Waiting" }));
    expect(chosen).toEqual(["broker"]);
  });
});
