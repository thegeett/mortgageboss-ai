// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { CitationNote } from "./reviewer-fields";

afterEach(cleanup);

const NONE = { cited: true, citationWrong: false, relocated: false, located: true };

describe("CitationNote", () => {
  it("says nothing for a field found where it was cited", () => {
    const { container } = render(<CitationNote {...NONE} />);
    expect(container.innerHTML).toBe("");
  });

  it("says nothing for a field the extraction never filled", () => {
    // No citation is not a failed lookup. "Not locatable" here would read as one.
    const { container } = render(<CitationNote {...NONE} cited={false} located={false} />);
    expect(container.innerHTML).toBe("");
  });

  it("says the citation was wrong rather than quietly showing a better page", () => {
    render(<CitationNote {...NONE} citationWrong relocated />);
    const note = screen.getByText(/cited a page this document does not have/);
    expect(note.textContent).toContain("shown where it actually appears");
  });

  it("still names the bad citation when the text is nowhere in the document", () => {
    render(<CitationNote {...NONE} citationWrong located={false} />);
    expect(screen.getByText(/cited a page this document does not have\./)).toBeTruthy();
    // And does not also claim it could not be located — the citation is the finding.
    expect(screen.queryByText(/Not locatable/)).toBeNull();
  });

  it("reports a page the extraction got wrong but that exists", () => {
    render(<CitationNote {...NONE} relocated />);
    expect(screen.getByText("Found on a different page than the one cited.")).toBeTruthy();
  });

  it("says a cited field simply could not be located", () => {
    render(<CitationNote {...NONE} located={false} />);
    expect(screen.getByText(/Not locatable on the page/)).toBeTruthy();
  });
});
