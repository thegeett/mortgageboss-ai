/**
 * LP-852 — every toast names the party and the count.
 *
 * ACCEPTANCE 2 IS WRITTEN AS A GREP ("`Draft prepared` returns nothing"), and a grep is the weaker
 * half of it: it proves a string is gone and says nothing about what replaced it on a screen. So
 * the scan below is paired with the behaviour — here, and in each dialog's own suite, where the
 * title actually handed to `notifySuccess` is asserted.
 */
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { draftToastTitle, requestToastTitle } from "./request-consequence";

describe("draftToastTitle", () => {
  it("names the party and the count", () => {
    expect(draftToastTitle([{ party: "title", count: 1 }])).toBe(
      "Draft to the title company — 1 document",
    );
    expect(draftToastTitle([{ party: "borrower", count: 3 }])).toBe(
      "Draft to the borrower — 3 documents",
    );
  });

  it("names every party rather than summarising them", () => {
    // "2 drafts prepared" is "Draft prepared" with a number on it: it still does not say WHO, which
    // is the only thing this title is for.
    expect(
      draftToastTitle([
        { party: "borrower", count: 2 },
        { party: "lender", count: 1 },
      ]),
    ).toBe("Draft to the borrower — 2 documents · Draft to the lender — 1 document");
  });

  it("leaves out a party that got nothing", () => {
    expect(
      draftToastTitle([
        { party: "borrower", count: 2 },
        { party: "title", count: 0 },
      ]),
    ).toBe("Draft to the borrower — 2 documents");
  });

  it("claims no draft when nothing was added", () => {
    // A second click on a row already requested. LP-826's review found the consequence claiming
    // membership of an email that does not exist; the title must not reintroduce it.
    expect(draftToastTitle([{ party: "borrower", count: 0 }])).toBe("Nothing new to request");
    expect(draftToastTitle([])).toBe("Nothing new to request");
  });

  it("renders a party the vocabulary does not know as itself", () => {
    expect(draftToastTitle([{ party: "escrow", count: 1 }])).toBe(
      "Draft to the escrow — 1 document",
    );
  });
});

describe("requestToastTitle", () => {
  it("reads the server's own outcome", () => {
    expect(
      requestToastTitle({
        document_request: { added_to_draft: 2, routed_elsewhere: { title: 1 } },
      } as never),
    ).toBe("Draft to the borrower — 2 documents · Draft to the title company — 1 document");
  });

  it("falls back rather than throwing when the server said nothing", () => {
    // This runs inside two mutation handlers, and a toast that throws takes the confirmation with
    // it — leaving a processor with a request that worked and no sign that it did.
    expect(requestToastTitle(undefined)).toBe("Documents requested");
    expect(requestToastTitle({} as never)).toBe("Documents requested");
  });
});

describe("acceptance 2 — the old title is gone", () => {
  it('no source file contains "Draft prepared" as a string', () => {
    // THE GREP HALF, scoped to STRING LITERALS. The plain grep the ticket asks for now matches only
    // the comments that explain the change, which would make it fail forever for the wrong reason —
    // and a criterion that can only fail for the wrong reason gets deleted rather than fixed.
    const offenders: string[] = [];
    const walk = (dir: string) => {
      for (const entry of readdirSync(dir, { withFileTypes: true })) {
        const full = join(dir, entry.name);
        if (entry.isDirectory()) {
          if (entry.name === "node_modules" || entry.name === ".next") continue;
          walk(full);
          continue;
        }
        // PRODUCT CODE ONLY. A test may legitimately contain the string — this file plants it two
        // cases down to prove the matcher matches — and the criterion is about what a processor
        // sees, which no test file is.
        if (!/\.tsx?$/.test(entry.name) || /\.test\.tsx?$/.test(entry.name)) continue;
        const source = readFileSync(full, "utf8");
        // Comments out first, so an explanation of the removal is not mistaken for the removal
        // having been undone.
        const code = source
          .replace(/\/\*[\s\S]*?\*\//g, "")
          .split("\n")
          .filter((line) => !line.trim().startsWith("//"))
          .join("\n");
        if (/["'`]Draft prepared["'`]/.test(code)) offenders.push(entry.name);
      }
    };
    for (const root of ["components", "app", "lib"]) walk(join(process.cwd(), root));

    expect(offenders).toEqual([]);
  });

  it("would notice it coming back", () => {
    // The scan above is a not-in over a tree that happens to be clean. Planted, so the matcher is
    // shown to match.
    const planted = 'notifySuccess({ title: "Draft prepared" });';
    expect(/["'`]Draft prepared["'`]/.test(planted)).toBe(true);
  });
});
