import {
  EMPTY_STATE,
  carriesSearchTerm,
  isFiltered,
  readPipelineUrl,
  writePipelineUrl,
} from "@/lib/loan-files/view-url";
import { LOAN_FILE_STATUS } from "@/lib/status";
import { describe, expect, it } from "vitest";

describe("pipeline URL state (LP-UI-014)", () => {
  it("round-trips a full filter state", () => {
    const state = {
      statuses: ["in_processing", "draft"] as const,
      viewId: "abc-123",
    };
    const url = writePipelineUrl({ ...state, statuses: [...state.statuses] });
    expect(readPipelineUrl(new URLSearchParams(url))).toEqual({
      statuses: ["in_processing", "draft"],
      viewId: "abc-123",
    });
  });

  it("omits empty values rather than writing blanks", () => {
    expect(writePipelineUrl(EMPTY_STATE)).toBe("");
  });

  it("reads an empty query as no filter", () => {
    expect(readPipelineUrl(new URLSearchParams(""))).toEqual(EMPTY_STATE);
  });

  it("ignores keys it does not own", () => {
    const state = readPipelineUrl(new URLSearchParams("?page=3&sort=whatever"));
    expect(state).toEqual({ statuses: [], viewId: null });
  });

  it("keeps every repeated status, in order", () => {
    const url = writePipelineUrl({
      statuses: ["draft", "submitted", "closed"],
      viewId: null,
    });
    expect(url).toBe("?status=draft&status=submitted&status=closed");
    expect(readPipelineUrl(new URLSearchParams(url)).statuses).toEqual([
      "draft",
      "submitted",
      "closed",
    ]);
  });

  it("does not count a selected view as a filter", () => {
    // Selecting a view named "Everything" filters nothing; the empty state
    // message should say "no files yet", not "no matches".
    expect(isFiltered({ statuses: [], viewId: "abc" })).toBe(false);
    expect(isFiltered({ statuses: ["draft"], viewId: null })).toBe(true);
  });

  it("counts the search as a filter although it is not in the URL", () => {
    // LP-933: the search lives in the per-tab store, so it is passed in.
    // Without it "All files" would be marked current while a search narrowed
    // the list.
    expect(isFiltered({ statuses: [], viewId: null }, "smith")).toBe(true);
    expect(isFiltered({ statuses: [], viewId: null }, "   ")).toBe(false);
  });
});

describe("the search never reaches the pipeline URL (LP-933, ADR-405)", () => {
  // It matches borrower NAMES. A copied pipeline link carried one as `?q=`
  // until LP-933; the rule is that a filter matching NPI stays out of the
  // shareable URL.
  it("does not read `q`", () => {
    const state = readPipelineUrl(new URLSearchParams("status=draft&q=ellis&view=abc"));
    expect(state).toEqual({ statuses: ["draft"], viewId: "abc" });
    expect(JSON.stringify(state)).not.toContain("ellis");
  });

  it("drops `q` from a link that still carries one when it is rewritten", () => {
    const state = readPipelineUrl(new URLSearchParams("status=draft&q=ellis&view=abc"));
    const url = writePipelineUrl(state);
    expect(url).toBe("?status=draft&view=abc");
    expect(url).not.toContain("q=");
  });

  it("recognises a link that still carries a term, so the dashboard can strip it", () => {
    expect(carriesSearchTerm(new URLSearchParams("q=ellis"))).toBe(true);
    // An EMPTY `q` still counts: it is the parameter in the address bar that is
    // stripped, and `?q=` left behind invites the next writer to fill it.
    expect(carriesSearchTerm(new URLSearchParams("q="))).toBe(true);
    expect(carriesSearchTerm(new URLSearchParams("status=draft"))).toBe(false);
  });
});

describe("readPipelineUrl rejects a status this build does not know", () => {
  // The endpoint types `status` as `list[LoanFileStatus]`, so FastAPI answers an
  // unknown one with a 422 and the dashboard renders its error state. A URL is a
  // paste-able, bookmarkable artifact: a typo in one should drop the filter, not
  // break the page — and the day a status is retired, every saved view carrying
  // it should widen rather than start failing.
  it("drops an unknown status and keeps the known ones", () => {
    const state = readPipelineUrl(
      new URLSearchParams("status=draft&status=nonsense&status=closed"),
    );
    expect(state.statuses).toEqual(["draft", "closed"]);
  });

  it("drops them all rather than sending one through", () => {
    expect(readPipelineUrl(new URLSearchParams("status=nope&status=alsonope")).statuses).toEqual(
      [],
    );
  });

  it("still accepts every status the app defines", () => {
    const all = Object.keys(LOAN_FILE_STATUS);
    const params = new URLSearchParams(all.map((s) => ["status", s]));
    expect(readPipelineUrl(params).statuses).toEqual(all);
  });

  it("round-trips through writePipelineUrl", () => {
    const state = readPipelineUrl(new URLSearchParams("status=draft&q=smith&view=abc"));
    expect(readPipelineUrl(new URLSearchParams(writePipelineUrl(state)))).toEqual(state);
  });
});
