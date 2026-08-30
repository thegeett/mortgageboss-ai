import {
  EMPTY_STATE,
  isFiltered,
  readPipelineUrl,
  writePipelineUrl,
} from "@/lib/loan-files/view-url";
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
