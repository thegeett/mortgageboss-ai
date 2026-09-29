/**
 * The conditions list's URL contract (LP-913).
 *
 * THE ASSERTION THIS FILE EXISTS FOR IS THAT `q` IS NEVER IN THE URL. Every other case here is an
 * ordinary round-trip; that one is a privacy boundary recorded as an ADR-405 amendment, and a comment
 * saying "we don't put it there" is worth nothing the day someone adds the obvious line.
 */
import { describe, expect, it } from "vitest";
import type { ConditionListUrlState } from "./list-url";
import {
  EMPTY_LIST_URL_STATE,
  describeConditionFilters,
  isConditionListFiltered,
  readConditionListUrl,
  writeConditionListUrl,
} from "./list-url";

const read = (query: string) => readConditionListUrl(new URLSearchParams(query));

describe("the search term never reaches the URL", () => {
  it("has no field for it, so no state can carry it there", () => {
    // `q` SEARCHES `verbatim_text` — the lender's words about a borrower's file. A shared link
    // carrying it would put "earnest money deposit in the amount of $2,850.00", or an employer's
    // name, into whatever the recipient pastes it into and into their history (ADR-405 as amended).
    //
    // Asserted over a FULLY POPULATED state, so this cannot pass merely because the fixture is empty.
    const url = writeConditionListUrl({
      roundNumber: 2,
      lenderStatus: ["cleared", "not_cleared"],
      prepStatus: ["waiting"],
      owner: ["title"],
      bucketKind: ["prior_to_docs"],
      step: ["i_will_do_it"],
      groupBy: "owner",
    });

    expect(url).not.toContain("q=");
    expect(url).not.toContain("search");
    // And the shape a reader would expect IS there, so the absence above is about `q` and not about
    // the serialiser having quietly stopped working.
    expect(url).toContain("round=2");
    expect(url).toContain("lender_status=cleared");
    expect(url).toContain("group=owner");
  });

  it("ignores a q that someone pasted in by hand", () => {
    // A URL is an artifact people edit. If a `q` arrives from somewhere, it must not become state
    // that the next `writeConditionListUrl` faithfully puts back.
    const state = read("owner=title&q=earnest+money");

    expect(state.owner).toEqual(["title"]);
    expect(writeConditionListUrl(state)).not.toContain("q=");
  });
});

describe("reading is forgiving, because a URL is pasted and edited", () => {
  it("drops values this build does not know rather than casting them", () => {
    // The endpoint types these as enums, so an unrecognised one is a 422 and a blank screen. A typo
    // should drop that filter and show MORE, and a retired enum member should widen every bookmark
    // carrying it rather than break it.
    const state = read("prep_status=waiting&prep_status=on_fire&owner=title&owner=the_cat");

    expect(state.prepStatus).toEqual(["waiting"]);
    expect(state.owner).toEqual(["title"]);
  });

  it("takes a round only when it is a positive whole number", () => {
    // `Number("")` is 0 and `Number("two")` is NaN. Either becoming a filter for round 0 would match
    // no sheet and silently empty the list — a filter nobody set and nobody can see.
    expect(read("round=2").roundNumber).toBe(2);
    expect(read("round=0").roundNumber).toBeNull();
    expect(read("round=-1").roundNumber).toBeNull();
    expect(read("round=two").roundNumber).toBeNull();
    expect(read("round=").roundNumber).toBeNull();
    expect(read("round=1.5").roundNumber).toBeNull();
  });

  it("falls back to the default grouping for anything unrecognised", () => {
    expect(read("group=owner").groupBy).toBe("owner");
    expect(read("group=sideways").groupBy).toBe("heading");
    expect(read("").groupBy).toBe("heading");
  });
});

describe("writing", () => {
  it("round-trips a populated state", () => {
    // NOT `as const`: that makes every array `readonly`, which does not satisfy the interface's
    // mutable arrays. The test wants a value that round-trips, not literal types.
    const state: ConditionListUrlState = {
      roundNumber: 3,
      lenderStatus: ["cleared"],
      prepStatus: ["waiting", "ready"],
      owner: ["title", "borrower"],
      bucketKind: ["prior_to_funding"],
      step: ["i_will_do_it", "ask_borrower"],
      groupBy: "prep_status",
    };

    expect(read(writeConditionListUrl(state).slice(1))).toEqual(state);
  });

  it("omits empties and the default grouping", () => {
    // `?group=heading` and no `group` mean the same thing, and only one of them survives a
    // copy-paste looking like what the processor actually did.
    expect(writeConditionListUrl(EMPTY_LIST_URL_STATE)).toBe("");
    expect(writeConditionListUrl({ ...EMPTY_LIST_URL_STATE, groupBy: "heading" })).toBe("");
    expect(writeConditionListUrl({ ...EMPTY_LIST_URL_STATE, groupBy: "owner" })).toBe(
      "?group=owner",
    );
  });
});

describe("what counts as filtered", () => {
  it("does not count grouping", () => {
    // Regrouping hides nothing. A list that is empty while grouped by owner is empty for some other
    // reason, and offering "Clear filters" there points a processor at the wrong control.
    expect(isConditionListFiltered({ ...EMPTY_LIST_URL_STATE, groupBy: "owner" })).toBe(false);
  });

  it("counts the search term even though it is not in the URL", () => {
    // The empty state must say "nothing matches invoice" when the search box is the ONLY active
    // filter. A helper reading the URL alone would call that state "nothing yet".
    expect(isConditionListFiltered(EMPTY_LIST_URL_STATE, "invoice")).toBe(true);
    expect(isConditionListFiltered(EMPTY_LIST_URL_STATE, "   ")).toBe(false);
  });

  it("counts every URL filter", () => {
    expect(isConditionListFiltered({ ...EMPTY_LIST_URL_STATE, roundNumber: 2 })).toBe(true);
    expect(isConditionListFiltered({ ...EMPTY_LIST_URL_STATE, owner: ["title"] })).toBe(true);
  });
});

describe("naming the filters for the empty state", () => {
  it("names them in the words the controls use", () => {
    // S2-09: "No open condition is waiting on Insurance". `EmptyState kind="filtered"` requires the
    // filter NAMED — "No results" tells a processor nothing about what to undo.
    const parts = describeConditionFilters(
      {
        ...EMPTY_LIST_URL_STATE,
        owner: ["insurance"],
        prepStatus: ["waiting"],
      },
      "",
    );

    expect(parts).toContain("Owner: Insurance");
    expect(parts).toContain("Our status: Waiting on someone");
  });

  it("says an absent owner once, not twice", () => {
    // The shared label is "Not known" (what S2-01/02/03 draw, under an "Owner" column heading), but
    // this phrase stands alone in a sentence — "Owner: Not known" reads as a lookup, and a bare
    // "Not known" does not say what is unknown. So the filter description says it in full, once.
    const parts = describeConditionFilters({ ...EMPTY_LIST_URL_STATE, owner: ["unknown"] });

    expect(parts).toEqual(["Owner not known"]);
  });

  it("quotes the search term, which is safe on the page even though not in the URL", () => {
    const parts = describeConditionFilters(EMPTY_LIST_URL_STATE, "invoice");

    expect(parts).toEqual(["matching “invoice”"]);
  });
});
