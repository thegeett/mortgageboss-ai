import type { ConditionEvent, ConditionEventKind } from "@/lib/types/conditions";
/**
 * LP-916's Done-when, enforced two ways: "every event kind has a plain sentence (with a test that
 * fails if a new kind has none)".
 *
 * TWO MECHANISMS, BECAUSE EITHER ALONE IS SATISFIABLE WITHOUT DOING THE WORK.
 *
 *   * `conditionHistoryLine`'s `never` arm makes a NEW kind a compile error — but it is satisfied by
 *     `return ""`, which compiles and renders a blank line.
 *   * The runtime sweep below refuses a blank or whitespace sentence — but a sweep over a hand-typed
 *     list only covers the kinds somebody remembered to type.
 *
 * So `ALL_KINDS` is checked AGAINST THE UNION at the type level too: a kind the backend adds and the
 * mirror propagates into `ConditionEventKind` makes `Missing` non-never and fails `tsc`, which is
 * what stops this file quietly testing eighteen of nineteen.
 */
import { describe, expect, it } from "vitest";
import { conditionHistoryLine } from "./history";

const ALL_KINDS = [
  "round_received",
  "round_parsed",
  "round_parse_failed",
  "round_reparse_requested",
  "round_imported",
  "round_discarded",
  "round_enriched",
  "condition_created",
  "condition_seen_again",
  "condition_note_added",
  "condition_edited",
  "condition_prep_moved",
  "condition_verdict_recorded",
  "condition_reopened",
  "condition_came_back",
  "condition_owner_changed",
  "condition_superseded",
  "round_compared",
  "round_completeness_changed",
  "condition_read",
  "condition_reading_confirmed",
  "condition_planned",
  "condition_plan_changed",
  "round_plan_confirmed",
  "condition_drafted",
  "condition_draft_polished",
  "condition_evidence_checked",
  "condition_evidence_accepted",
  "condition_finding_answered",
  "condition_withdrawn",
  "condition_restored",
  "condition_typed",
  "round_lender_declined",
  "round_wrong_file_confirmed",
  "condition_evidence_linked",
  "condition_evidence_unlinked",
] as const satisfies readonly ConditionEventKind[];

/**
 * THE HALF THAT CANNOT BE FAKED. If `ConditionEventKind` grows a member that `ALL_KINDS` omits,
 * `Missing` stops being `never` and this assignment fails to compile — so the sweep below can never
 * silently cover less than the whole union.
 */
type Missing = Exclude<ConditionEventKind, (typeof ALL_KINDS)[number]>;
const _everyKindIsListed: Missing extends never ? true : false = true;

function makeEvent(overrides: Partial<ConditionEvent> = {}): ConditionEvent {
  return {
    kind: "condition_created",
    occurred_at: "2026-09-12T16:31:00Z",
    actor_user_id: null,
    source_kind: null,
    reader: null,
    rows: null,
    round_number: null,
    created: null,
    seen_again: null,
    from_status: null,
    filled_header: null,
    filled_expiry: null,
    matched: null,
    prep_status_from: null,
    prep_status_to: null,
    waiting_on: null,
    plan_option: null,
    draft_recipient: null,
    lender_status_from: null,
    lender_status_to: null,
    verdict_source_kind: null,
    verdict_source_date: null,
    notes_added: null,
    actor_name: null,
    ...overrides,
  };
}

describe("every event kind has a sentence", () => {
  it.each(ALL_KINDS)("%s renders a non-empty line", (kind) => {
    const line = conditionHistoryLine(makeEvent({ kind }));

    expect(line.trim()).not.toBe("");
    // AND IT IS A SENTENCE, NOT THE RAW VALUE. Returning `kind` would satisfy "non-empty" while
    // putting `condition_prep_moved` in front of a processor — the unrecognised-value rendering the
    // whole vocabulary exists to prevent.
    expect(line).not.toContain("_");
  });

  it("is exhaustive over the union, checked by the compiler", () => {
    expect(_everyKindIsListed).toBe(true);
    expect(ALL_KINDS).toHaveLength(36);
  });
});

describe("a verdict line says who said so and where", () => {
  it("names the place and the lender's date for a source a person picked", () => {
    const line = conditionHistoryLine(
      makeEvent({
        kind: "condition_verdict_recorded",
        lender_status_to: "cleared",
        verdict_source_kind: "portal",
        verdict_source_date: "2026-09-12",
        actor_name: "Priya Raman",
      }),
    );

    expect(line).toBe("Marked Cleared (portal, 09/12) — Priya Raman");
  });

  it("names the sheet for a source the app derived", () => {
    // NOT "(round_comparison, 09/10)" — that would make an inference read as something a person was
    // told. The two shapes are the point of `fromSource`.
    const line = conditionHistoryLine(
      makeEvent({
        kind: "condition_verdict_recorded",
        lender_status_to: "cleared",
        verdict_source_kind: "round_comparison",
        verdict_source_date: "2026-09-10",
        round_number: 2,
        actor_name: "Priya Raman",
      }),
    );

    expect(line).toBe("Marked Cleared from the round 2 comparison — Priya Raman");
  });

  it("says nothing about an actor when there was none", () => {
    // A system event names nobody. "—" in an audit trail reads as a name nobody checked.
    const line = conditionHistoryLine(
      makeEvent({ kind: "condition_verdict_recorded", lender_status_to: "waived" }),
    );

    expect(line).toBe("Marked Waived");
    expect(line).not.toContain("—");
  });
});

describe("a move the app made is never silent", () => {
  it("says what a refusal did to our track", () => {
    // THE REVIEW'S POINT, AND THE REASON THE FROM-TO PAIR IS ON THE EVENT. A processor records
    // "underwriter phoned, refused it", the row jumps to To do, and without this clause nothing on
    // screen explains why. S2-08 draws this sentence for the note route; this is the manual one.
    const line = conditionHistoryLine(
      makeEvent({
        kind: "condition_verdict_recorded",
        lender_status_to: "not_cleared",
        verdict_source_kind: "phone",
        verdict_source_date: "2026-09-18",
        prep_status_from: "with_underwriter",
        prep_status_to: "to_do",
      }),
    );

    expect(line).toContain("our status moved from Sent to lender back to To do");
  });

  it("says how and when the round was printed on an import, as S2-03 draws it", () => {
    const line = conditionHistoryLine(makeEvent({ kind: "condition_created", round_number: 1 }), [
      {
        round_id: "r1",
        round_number: 1,
        round_date: "2026-08-28",
        date_printed: "2026-08-28",
        completeness: "full",
        arrived_as: "pdf_upload",
        on_sheet: true,
        notes: [],
      },
    ]);

    expect(line).toBe("Imported from round 1 (PDF upload, printed 08/28)");
  });

  it("names who a move to waiting is waiting on, as S2-03 draws it", () => {
    const line = conditionHistoryLine(
      makeEvent({
        kind: "condition_prep_moved",
        prep_status_from: "to_do",
        prep_status_to: "waiting",
        waiting_on: "borrower",
        actor_name: "Priya Raman",
      }),
    );

    expect(line).toBe("Moved to Waiting on Borrower — Priya Raman");
  });

  it("says nothing when our track did not move", () => {
    const line = conditionHistoryLine(
      makeEvent({
        kind: "condition_verdict_recorded",
        lender_status_to: "cleared",
        verdict_source_kind: "portal",
        prep_status_from: "waiting",
        prep_status_to: "waiting",
      }),
    );

    expect(line).not.toContain("our status moved");
  });

  it("names the lender's note on a came-back", () => {
    const line = conditionHistoryLine(
      makeEvent({
        kind: "condition_came_back",
        verdict_source_kind: "underwriter_note",
        verdict_source_date: "2026-09-18",
        prep_status_from: "ready",
        prep_status_to: "to_do",
      }),
    );

    expect(line).toBe(
      "Came back from the lender’s 09/18 note · our status moved from Ready to send back to To do",
    );
  });
});

describe("the lines that carry a round", () => {
  it("distinguishes a condition imported from a sheet from one typed by hand", () => {
    expect(conditionHistoryLine(makeEvent({ kind: "condition_created", round_number: 1 }))).toBe(
      "Imported from round 1",
    );
    // S1-12's hand-typed condition was filed INTO a round, not printed on one.
    expect(conditionHistoryLine(makeEvent({ kind: "condition_created" }))).toBe(
      "Added to this file",
    );
  });

  it("counts notes without quoting them", () => {
    // THE QUOTE IS THE LENDER'S WORDS AND DOES NOT TRAVEL (rule 7). S2-03 draws
    // `Underwriter note added in round 1: “8/28 Not in Upload”`; the count is what reaches the client.
    const one = conditionHistoryLine(
      makeEvent({ kind: "condition_note_added", notes_added: 1, round_number: 1 }),
    );
    const many = conditionHistoryLine(
      makeEvent({ kind: "condition_note_added", notes_added: 3, round_number: 2 }),
    );

    expect(one).toBe("Underwriter note added in round 1");
    expect(many).toBe("Underwriter notes added in round 2");
  });

  it("says seen again with the round it was seen on", () => {
    expect(conditionHistoryLine(makeEvent({ kind: "condition_seen_again", round_number: 2 }))).toBe(
      "Seen again in round 2",
    );
  });
});

describe("LP-922's lines", () => {
  it("names the email a condition was put into", () => {
    expect(
      conditionHistoryLine(makeEvent({ kind: "condition_drafted", draft_recipient: "borrower" })),
    ).toBe("Added to the borrower email");
  });

  it("says which send moved it", () => {
    expect(
      conditionHistoryLine(
        makeEvent({
          kind: "condition_prep_moved",
          prep_status_to: "waiting",
          waiting_on: "broker",
          draft_recipient: "lo",
          actor_name: "Priya Raman",
        }),
      ),
    ).toBe("Moved to Waiting on LO (LO email marked sent) — Priya Raman");
  });

  it("shows why a condition was withdrawn, and says when it was undone (LP-941)", () => {
    expect(
      conditionHistoryLine(
        makeEvent({
          kind: "condition_withdrawn",
          withdrawal_reason: "Added twice by mistake",
          actor_name: "Priya Raman",
        }),
      ),
    ).toBe("Withdrawn as entered in error — “Added twice by mistake” — Priya Raman");
    expect(
      conditionHistoryLine(makeEvent({ kind: "condition_restored", actor_name: "Priya Raman" })),
    ).toBe("Withdrawal undone — Priya Raman");
  });
});

describe("LP-949's lines", () => {
  it("names the library type a condition was matched to, and says so without one", () => {
    expect(
      conditionHistoryLine(
        makeEvent({
          kind: "condition_typed",
          typed_as: "Final inspection",
          actor_name: "Priya Raman",
        }),
      ),
    ).toBe("Matched to the library: Final inspection — Priya Raman");
    expect(conditionHistoryLine(makeEvent({ kind: "condition_typed", typed_as: null }))).toBe(
      "Matched to the library",
    );
  });
});
