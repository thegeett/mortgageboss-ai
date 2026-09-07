// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ExtractionView } from "@/components/file/documents/extraction-view";

/**
 * That the catch-all renderer actually masks (LP-UI-032 review).
 *
 * Separate from the unit tests on `catchAllIsSensitive`, and NOT redundant with them:
 * those pass in full while the renderer passes `field.value` straight through, which is
 * the defect this fixes and precisely what a unit test on the helper cannot see. Removing
 * the call from the JSX has to fail HERE.
 */
describe("the catch-all section", () => {
  afterEach(cleanup);

  const data = {
    additional_sections: [
      {
        section: "Employer",
        fields: [
          { label: "b Employer's social security number", value: "123456789", source: null },
          { label: "Social Security - YTD", value: "$4,200.00", source: null },
        ],
      },
    ],
  };

  it("never puts a nine-digit tax id on the screen", () => {
    render(<ExtractionView data={data} />);
    expect(screen.queryByText("123456789")).toBeNull();
    expect(screen.getByText("•••-••-6789")).toBeTruthy();
  });

  it("still shows the withholding amount in full", () => {
    render(<ExtractionView data={data} />);
    expect(screen.getByText("$4,200.00")).toBeTruthy();
  });
});
