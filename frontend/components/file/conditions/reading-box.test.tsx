import type { Condition, ConditionReading } from "@/lib/types/conditions";
// @vitest-environment jsdom
/**
 * "How we read it" (S3-01, LP-919): what is labelled as the AI's, what as code's, and when she is asked.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ReadingBox, ReadingItems } from "./reading-box";

afterEach(cleanup);

const reading = (over: Partial<ConditionReading> = {}): ConditionReading => ({
  source: "ai",
  type_id: "AS-04",
  summary: "Earnest money $2,850: source, receipt, clearance",
  explanation: "The lender wants proof of where the $2,850 earnest money came from.",
  information_only: false,
  lender_doing_it: false,
  note_meaning: null,
  items: [
    {
      key: "source",
      name: "Source of the $2,850.00",
      acceptable: "Statement showing the funds before the check was written",
      performers: ["borrower"],
      option: "ask_borrower",
      documents: ["bank_statement"],
      checks: ["all_pages"],
      specifics: {
        amounts: [],
        account_bank: "Capital One",
        account_last4: "9912",
        month: "2026-07",
        names: [],
      },
    },
    {
      key: "receipt",
      name: "Receipt of the deposit",
      acceptable: "Copy of the canceled check",
      performers: ["title"],
      option: "ask_third_party",
      documents: [],
      checks: [],
      specifics: { amounts: [], account_bank: null, account_last4: null, month: null, names: [] },
    },
  ],
  figures: { shortfall: null },
  push_back: null,
  confidence: 0.93,
  ...over,
});

const condition = (over: Partial<Condition> = {}): Condition =>
  ({
    id: "c1",
    lender_code: "6637",
    reading: reading(),
    reading_status: "ready",
    reading_confidence: 0.93,
    library_type: {
      id: "AS-04",
      name: "Earnest money",
      label: "AS-04 Earnest money",
      rule_label: "Fannie Mae B3-4.3-09",
      rule_note: "Receipt by a copy of the canceled check.",
    },
    ...over,
  }) as Condition;

describe("ReadingBox", () => {
  it("labels an AI reading violet with its confidence, and the library type and rule", () => {
    render(<ReadingBox condition={condition()} />);
    expect(screen.getByText("Read by AI · 0.93")).toBeDefined();
    expect(screen.getByText("Library: AS-04 Earnest money")).toBeDefined();
    expect(screen.getByText(/Rule: Fannie Mae B3-4\.3-09 — receipt by a copy/)).toBeDefined();
  });

  it("asks her to confirm below the bar, and says nothing is drafted until she does", () => {
    const onConfirm = vi.fn();
    render(
      <ReadingBox
        condition={condition({ reading_status: "needs_confirmation", reading_confidence: 0.64 })}
        onConfirm={onConfirm}
      />,
    );
    expect(screen.getByText("0.64 · confirm")).toBeDefined();
    expect(screen.queryByText(/Read by AI/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Confirm the reading" }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("never calls a library reading the AI's", () => {
    render(
      <ReadingBox
        condition={condition({
          reading: reading({ source: "library", confidence: null }),
          reading_status: "needs_confirmation",
          reading_confidence: null,
        })}
      />,
    );
    expect(screen.getByText("Library · confirm")).toBeDefined();
    expect(screen.queryByText(/Read by AI/)).toBeNull();
  });

  it("marks a computed figure as code's, formatted without a float", () => {
    render(
      <ReadingBox
        condition={condition({
          reading: reading({
            figures: {
              shortfall: { required: "38210.40", verified: "11062.18", amount: "27148.22" },
            },
          }),
        })}
      />,
    );
    expect(
      screen.getByText(
        "Shortfall $27,148.22 (required $38,210.40, verified $11,062.18) · computed by code",
      ),
    ).toBeDefined();
  });
});

describe("ReadingItems", () => {
  it("lists each item with who acts, the option, and the account as last four only", () => {
    render(<ReadingItems items={reading().items} />);
    expect(screen.getByText("Items · 2")).toBeDefined();
    expect(
      screen.getByText(
        "Statement showing the funds before the check was written · Capital One ··9912 · Jul 2026",
      ),
    ).toBeDefined();
    expect(screen.getByText("Title / escrow")).toBeDefined();
    expect(screen.getByText("Ask a third party")).toBeDefined();
  });
});
