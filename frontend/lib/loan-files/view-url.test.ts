import {
  EMPTY_STATE,
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
      search: "smith",
      viewId: "abc-123",
    };
    const url = writePipelineUrl({ ...state, statuses: [...state.statuses] });
    expect(readPipelineUrl(new URLSearchParams(url))).toEqual({
      statuses: ["in_processing", "draft"],
      search: "smith",
      viewId: "abc-123",
    });
  });

  it("omits empty values rather than writing blanks", () => {
    // `?q=` and no `q` mean the same thing; only one survives a paste unchanged.
    expect(writePipelineUrl(EMPTY_STATE)).toBe("");
    expect(writePipelineUrl({ ...EMPTY_STATE, search: "   " })).toBe("");
  });

  it("reads an empty query as no filter", () => {
    expect(readPipelineUrl(new URLSearchParams(""))).toEqual(EMPTY_STATE);
  });

  it("ignores keys it does not own", () => {
    const state = readPipelineUrl(new URLSearchParams("?page=3&sort=whatever&q=ellis"));
    expect(state).toEqual({ statuses: [], search: "ellis", viewId: null });
  });

  it("keeps every repeated status, in order", () => {
    const url = writePipelineUrl({
      statuses: ["draft", "submitted", "closed"],
      search: "",
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
    expect(isFiltered({ statuses: [], search: "", viewId: "abc" })).toBe(false);
    expect(isFiltered({ statuses: ["draft"], search: "", viewId: null })).toBe(true);
    expect(isFiltered({ statuses: [], search: "smith", viewId: null })).toBe(true);
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
