import type { Condition, ConditionItem, PlanOption } from "@/lib/types/conditions";
import { describe, expect, it } from "vitest";
import {
  addedPlaces,
  askedWho,
  conditionPath,
  endingPath,
  firstMoves,
  nextOf,
  ownStepPath,
  previewPath,
  taskPath,
} from "./plan-path";

function item(overrides: Partial<ConditionItem>): ConditionItem {
  return {
    id: "i1",
    key: "k",
    name: "Thing",
    acceptable: "The thing itself",
    performer: "title",
    performers: ["title"],
    option: "ask_third_party",
    status: "open",
    origin: "reading",
    need_id: null,
    need_title: null,
    shared_with_codes: [],
    document_id: null,
    document_name: null,
    document_page: null,
    waits_on_condition_id: null,
    waits_on_code: null,
    due_date: null,
    specifics: {} as ConditionItem["specifics"],
    task: null,
    draft: null,
    // A library task with checks beyond its type, so "We check" keeps its general sentence; the
    // LP-971 follow-up tests below take it away.
    has_checks: true,
    ...overrides,
  };
}

const texts = (option: PlanOption, overrides: Partial<ConditionItem> = {}) =>
  taskPath(item({ option, ...overrides })).map((step) => step.text);

describe("plan path", () => {
  it("an ask: we draft on confirm, you send, they send it back, you link, we check", () => {
    const steps = taskPath(item({}));
    expect(steps.map((s) => [s.who, s.text])).toEqual([
      ["we", "We draft the email to Title / escrow when you confirm the plan"],
      ["you", "Review the email, and send it once the plan is confirmed"],
      ["them", "Title / escrow sends it back"],
      ["you", "Link it to this task"],
      ["we", "We check it against what was asked"],
    ]);
    expect(steps[0]?.detail).toBe(
      "It goes in the title email, with anything else asked of Title / escrow this round.",
    );
    expect(steps[4]?.detail).toBe("It should be: The thing itself.");
  });

  it("LP-968: a drafted ask says it is drafted and carries the draft to open", () => {
    const drafted = taskPath(
      item({ draft: { id: "d1", status: "draft", sent_on: null } as ConditionItem["draft"] }),
    );
    expect(drafted[0]).toMatchObject({
      text: "We drafted the email to Title / escrow",
      draftId: "d1",
    });
    // A reading that still needs her is kept out of the drafts, and the path says why.
    expect(taskPath(item({}), { needsConfirmation: true })[0]?.text).toBe(
      "We draft the email to Title / escrow once you confirm how we read this condition",
    );
    // A task she dropped has no path left.
    expect(taskPath(item({ status: "not_needed" }))).toEqual([]);
  });

  it("an ask names the server's recipient: an LO relay goes to the LO", () => {
    const relay = item({ performer: "borrower", performers: ["borrower", "lo"] });
    expect(askedWho(relay)).toBe("the LO");
    expect(taskPath(relay)[2]?.text).toBe("The LO sends it back");
  });

  it("a generic task promises no 'should be' line", () => {
    expect(taskPath(item({ generic: true }))[4]?.detail).toBeUndefined();
  });

  it("her own task names the library's task, then upload or mark done, then our check", () => {
    expect(texts("i_will_do_it", { task: "order the final inspection" })).toEqual([
      "Order the final inspection",
      "Upload what you get to this task, or mark the task done",
      "We check what you upload",
    ]);
    expect(texts("i_will_do_it", { name: "Inspection invoice" })[0]).toBe(
      "Do it: Inspection invoice",
    );
  });

  it("a task that waits on another condition starts there", () => {
    const steps = taskPath(item({ option: "i_will_do_it", waits_on_code: "1228" }));
    expect(steps[0]).toMatchObject({ who: "them", whoLabel: "Waiting on 1228" });
  });

  it("already in the file names the document and asks her to check it", () => {
    expect(
      texts("already_in_file", { document_name: "HR Loan Processing invoice", document_page: 1 }),
    ).toEqual([
      "We found HR Loan Processing invoice, page 1 on the file",
      "Check it’s the right document",
    ]);
  });

  it("a question on a single task says it does nothing there (LP-966 review)", () => {
    expect(texts("push_back")).toEqual(["This step does nothing on a single task"]);
  });

  it("a question is drafted when the plan is ready, and sent after confirm (LP-969)", () => {
    // `sync_round_drafts` makes the underwriter draft in the same pass as the others since LP-968;
    // "when you confirm" was left behind. Only the SEND waits for confirm.
    for (const own of ["ask_underwriter", "push_back"] as const) {
      const [drafted, send] = ownStepPath(own);
      expect(drafted?.text).not.toMatch(/when you confirm/);
      expect(drafted?.detail).toMatch(/^It is drafted once the plan is ready/);
      expect(send?.text).toMatch(/send it once the plan is confirmed$/);
    }
    // The push back cannot promise the argument: `render_question` writes only the HOI-date case.
    expect(ownStepPath("push_back")[1]?.text).toContain("say why it shouldn’t apply");
  });

  it("the condition's own question drafts to the underwriter; its own ask emails nothing itself", () => {
    expect(ownStepPath("push_back").map((s) => s.who)).toEqual(["we", "you", "lender"]);
    expect(ownStepPath("ask_borrower")[0]?.detail).toBe(
      "The tasks below set to ask are what go in the email.",
    );
  });

  it("every condition ends at the package and the lender, except information only", () => {
    const condition = { next_step: null } as Condition;
    expect(endingPath(condition).map((s) => s.who)).toEqual(["we", "lender"]);
    expect(endingPath({ next_step: "information_only" } as Condition)).toEqual([]);
  });

  it("a task's path starts where the task is, not at the beginning (LP-967 review)", () => {
    // The path is "every step from NOW", and it began at "We draft the email" however far along the
    // task was — so a task whose ask had gone, or whose document was already linked, described work
    // behind her as though it were ahead.
    const open = taskPath(item({ status: "open" })).map((s) => s.text);
    expect(open[0]).toBe("We draft the email to Title / escrow when you confirm the plan");

    // `requested`: the draft and the send have happened (`mark_sent`).
    const requested = taskPath(item({ status: "requested" })).map((s) => s.text);
    expect(requested[0]).toBe("Title / escrow sends it back");
    expect(requested).not.toContain("Review the email and send it");

    // `received`: a document is linked but has not passed its checks — a hand link is RECEIVED until
    // `check_link` (LP-953), so the check is the only step left.
    expect(taskPath(item({ status: "received" })).map((s) => s.text)).toEqual([
      "We check it against what was asked",
    ]);

    // `done`: nothing left, and an empty card would say nothing.
    expect(taskPath(item({ status: "done" })).map((s) => s.text)).toEqual([
      "This task is done — nothing left on it",
    ]);
    expect(
      taskPath(item({ option: "i_will_do_it", status: "received" })).map((s) => s.text),
    ).toEqual(["We check what you upload"]);

    // A WAITS-ON PREFIX SURVIVES THE TRIM, because it is not one of the task's own steps.
    const waiting = taskPath(item({ status: "requested", waits_on_code: "1228" }));
    expect(waiting[0]?.text).toBe("Starts once 1228 is done");
    expect(waiting[1]?.text).toBe("Title / escrow sends it back");

    // THE CONTROL: "Already in the file" is DONE by construction (`build_plan` sets both together),
    // so trimming it on `done` would empty the one card she most wants to read.
    expect(
      taskPath(item({ option: "already_in_file", status: "done" })).map((s) => s.text),
    ).toEqual(["We found it on the file", "Check it’s the right document"]);
  });

  it("does not promise this recipient when the condition asks two people (LP-967 review)", () => {
    // `_wait_on_first_asked` says it outright: "NOT whoever was emailed first" — the owner is the
    // recipient of the condition's FIRST live ask whose email has gone, "whichever email she happened
    // to mark sent first", its own example being 0132's LO disclosure before title's wire
    // instructions. So this step cannot promise its own recipient.
    const detail = taskPath(item({}))[1]?.detail ?? "";
    expect(detail).toContain("waiting on Title / escrow");
    // LP-973 review: "first" is the first whose email has GONE — `first_asked_owner` skips an ask
    // whose email has not been sent — not the first on the list.
    expect(detail).toContain("the first of them whose email you have sent");
  });

  it("the ending only promises the package where the tasks can settle it (LP-967 review)", () => {
    // `ready_because` returns None for ANY condition-level step that is not "Already in the file" or
    // "I'll do it", so finishing the tasks does not make such a condition Ready and it never reaches
    // `_goes_in`'s package that way. Only `information_only` was excluded.
    for (const own of [
      "lender_doing_it",
      "ask_underwriter",
      "push_back",
      "ask_borrower",
    ] as const) {
      const steps = endingPath({ next_step: own } as Condition);
      expect(steps.map((s) => s.who)).toEqual(["lender"]);
      expect(steps[0]?.text).toBe("The lender clears it");
    }
    // THE CONTROL: the three the tasks CAN settle still promise the package.
    for (const own of [null, "i_will_do_it", "already_in_file"] as const) {
      expect(endingPath({ next_step: own } as Condition).map((s) => s.who)).toEqual([
        "we",
        "lender",
      ]);
    }
    expect(endingPath({ next_step: "information_only" } as Condition)).toEqual([]);
  });

  it("first moves count what she does now, what waits, who we wait on, and what is handled", () => {
    // LP-967 REVIEW: `next_step: null` and, beside `already_in_file`, `status: "done"` — that is the
    // pair `build_plan` writes. The fixture said option-only with the default `open` status, which no
    // writer on the server produces, and `handled` was keyed on the option to match it.
    const rows = [
      { lender_code: "0006", next_step: null, items: [item({ option: "i_will_do_it" })] },
      {
        lender_code: "0007",
        next_step: null,
        items: [item({ option: "i_will_do_it", waits_on_code: "1228" })],
      },
      { lender_code: "1947", next_step: null, items: [item({}), item({ id: "i2" })] },
      {
        lender_code: "1582",
        next_step: null,
        items: [item({ option: "already_in_file", status: "done" })],
      },
      // Half in the file, half still asked: not handled.
      {
        lender_code: "6637",
        next_step: null,
        items: [
          item({ option: "already_in_file", status: "done" }),
          item({ id: "i9", performer: "borrower", performers: ["borrower"] }),
        ],
      },
      // ALL in the file but one document still being read: a hand link is RECEIVED until `check_link`
      // passes it (LP-953), so confirm will NOT mark this ready — and the box must not say it is
      // handled while the confirm summary leaves it out. Both read `willBeReady` now.
      {
        lender_code: "7086",
        next_step: null,
        items: [
          item({ option: "already_in_file", status: "done" }),
          item({ id: "i7", option: "already_in_file", status: "received" }),
        ],
      },
      {
        lender_code: "9999",
        next_step: null,
        items: [item({ option: "i_will_do_it", status: "not_needed" })],
      },
    ] as Condition[];
    expect(firstMoves(rows, [{ codes: ["1947"] }])).toEqual({
      emails: 1,
      tasksNow: 1,
      tasksLater: 1,
      waitingOn: ["Title / escrow", "the borrower"],
      handled: ["1582"],
    });
  });

  it("LP-974: one timeline per condition — its own step, each task's steps, then the ending", () => {
    const mine = item({ id: "m", option: "i_will_do_it", task: "upload the invoice" });
    const asked = item({ id: "a" });
    const entries = conditionPath({
      next_step: "i_will_do_it",
      items: [mine, asked],
    } as Condition);
    expect(entries.map((e) => [e.item?.id ?? null, e.leads, e.step.text])).toEqual([
      [null, true, "Do it, then mark each task below done"],
      ["m", true, "Upload the invoice"],
      ["m", false, "Upload what you get to this task, or mark the task done"],
      ["m", false, "We check what you upload"],
      ["a", true, "We draft the email to Title / escrow when you confirm the plan"],
      ["a", false, "Review the email, and send it once the plan is confirmed"],
      ["a", false, "Title / escrow sends it back"],
      ["a", false, "Link it to this task"],
      ["a", false, "We check it against what was asked"],
      [
        null,
        false,
        "When every task is done, the condition is ready and goes in the package for the lender",
      ],
      [null, false, "The lender clears it"],
    ]);
  });

  it("LP-974: a dropped task keeps one entry with her reason; with nothing live, no ending", () => {
    const dropped = item({ status: "not_needed", plan_note: "no fee charged" });
    const alone = conditionPath({ next_step: null, items: [dropped] } as Condition);
    expect(alone).toEqual([
      {
        step: { who: "you", whoLabel: "Not needed", text: "Thing", detail: "no fee charged" },
        item: dropped,
        leads: true,
      },
    ]);
    // THE CONTROL: beside a live task, the ending is back.
    const beside = conditionPath({
      next_step: null,
      items: [dropped, item({ id: "i2" })],
    } as Condition);
    expect(beside.at(-1)?.step.text).toBe("The lender clears it");
    // Nothing worked out at all: no entries.
    expect(conditionPath({ next_step: null, items: [] } as unknown as Condition)).toEqual([]);
  });

  it("LP-974: Next is the first step still ahead, past a dropped or finished task", () => {
    const entries = conditionPath({
      next_step: null,
      items: [
        item({ id: "x", status: "not_needed" }),
        item({ id: "y", option: "i_will_do_it", status: "done" }),
        item({ id: "z", status: "requested" }),
      ],
    } as Condition);
    expect(nextOf(entries)?.text).toBe("Title / escrow sends it back");
    // Every task finished: the ending is what comes next, and of the ending, the LENDER's step (LP-979:
    // the app's packaging is its own work, not someone's next move).
    const done = conditionPath({
      next_step: null,
      items: [item({ option: "i_will_do_it", status: "done" })],
    } as Condition);
    expect(nextOf(done)?.text).toBe("The lender clears it");
  });

  it("LP-972: a wait is someone else's next move, with the reminder date, then her upload and our check", () => {
    const wait = item({
      option: "i_will_do_it",
      performer: "title",
      performers: ["title"],
      name: "the payoff letter",
      waiting: true,
      due_date: "2026-10-15",
    });
    const steps = taskPath(wait);
    expect(steps.map((s) => [s.who, s.text])).toEqual([
      ["them", "Title / escrow sends the payoff letter"],
      ["you", "When it comes, upload or link it here, or mark the task done"],
      ["we", "We check what you upload"],
    ]);
    expect(steps[0]?.detail).toBe("If it hasn’t come by 10/15, it shows on your Reminders page.");
    // Received: it came and is being checked; only the check is left.
    expect(taskPath({ ...wait, status: "received" }).map((s) => s.text)).toEqual([
      "We check what you upload",
    ]);
    // In first moves it is someone to wait on, not a task she does now.
    const moves = firstMoves(
      [{ lender_code: "1947", next_step: null, items: [wait] } as Condition],
      [],
    );
    expect(moves).toMatchObject({ tasksNow: 0, waitingOn: ["Title / escrow"] });
  });

  it("LP-979: the app's steps say what kind of step they are, as the mock does", () => {
    const ask = taskPath(item({}));
    expect(ask[0]?.whoLabel).toBe("We prepare it"); // the draft
    expect(ask[4]?.whoLabel).toBe("We check it"); // the check
    expect(taskPath(item({ option: "already_in_file" }))[0]?.whoLabel).toBe("We found it");
    expect(taskPath(item({ option: "information_only" }))[0]?.whoLabel).toBe("Nothing to do");
    expect(endingPath({ next_step: null } as Condition)[0]?.whoLabel).toBe("We prepare it");
  });

  it("LP-979: with the file's lender, the ending names it and the condition", () => {
    const steps = endingPath({ next_step: null, lender_code: "1228" } as Condition, {
      lenderName: "UWM",
    });
    expect(steps.map((s) => [s.whoLabel, s.text])).toEqual([
      [
        "We prepare it",
        "When every task is done, the condition is ready and goes in the package for UWM",
      ],
      ["UWM", "UWM clears 1228"],
    ]);
    // A condition-level step the tasks cannot settle ends at the lender too, named.
    expect(
      endingPath({ next_step: "lender_doing_it", lender_code: "1228" } as Condition, {
        lenderName: "UWM",
      }).map((s) => s.text),
    ).toEqual(["UWM clears 1228"]);
    // THE CONTROL: no lender on the file, the words stay general.
    expect(endingPath({ next_step: null, lender_code: "1228" } as Condition).at(-1)?.text).toBe(
      "The lender clears it",
    );
    // And it reaches the timeline through `conditionPath`'s context.
    const entries = conditionPath(
      { next_step: null, lender_code: "1228", items: [item({})] } as unknown as Condition,
      { lenderName: "UWM" },
    );
    expect(entries.at(-1)?.step.text).toBe("UWM clears 1228");
  });

  it("LP-979: Next falls back to the app's step only when every step ahead is the app's", () => {
    // A finished-and-received task leaves only "We check what you upload": nothing a person does yet.
    const entries = conditionPath({
      next_step: "information_only",
      items: [item({ option: "i_will_do_it", status: "received" })],
    } as Condition);
    expect(nextOf(entries)?.text).toBe("Nothing to do: the lender is only telling you something");
  });

  describe("LP-971 follow-up — We check says what is checked", () => {
    const last = (steps: ReturnType<typeof taskPath>) => steps[steps.length - 1];

    it("a type alone is named; checks beyond it keep the general sentence", () => {
      const typed = { has_checks: false, document_kinds: ["service invoice"] };
      expect(last(taskPath(item({ option: "i_will_do_it", ...typed })))?.text).toBe(
        "We check it’s a service invoice",
      );
      expect(last(taskPath(item({ ...typed })))?.text).toBe("We check it’s a service invoice");
      const asset = { has_checks: false, document_kinds: ["asset statement"] };
      expect(last(taskPath(item({ option: "i_will_do_it", ...asset })))?.text).toBe(
        "We check it’s an asset statement",
      );
      // THE CONTROL: with checks, the general sentence.
      expect(last(taskPath(item({ option: "i_will_do_it" })))?.text).toBe(
        "We check what you upload",
      );
    });

    it("with nothing to check, there is no We check step: not on a task, an ask or a wait", () => {
      const bare = { has_checks: false, document_kinds: [] };
      for (const overrides of [
        { option: "i_will_do_it" as const },
        { option: "ask_third_party" as const },
        { option: "i_will_do_it" as const, waiting: true, due_date: "2026-10-15" },
      ]) {
        const steps = taskPath(item({ ...overrides, ...bare }));
        expect(steps.length).toBeGreaterThan(0);
        expect(steps.some((step) => step.whoLabel === "We check it")).toBe(false);
      }
    });

    it("previews a step's rows through the path itself", () => {
      const email = {
        name: "Please provide invoice for credit report",
        option: "ask_third_party" as const,
        performer: "other_party" as const,
      };
      const checked = previewPath({ ...email, documentKinds: ["service invoice"] });
      expect(checked.map((step) => step.text)).toEqual([
        "We draft the email to Other party when you confirm the plan",
        "Review the email, and send it once the plan is confirmed",
        "Other party sends it back",
        "Link it to this task",
        "We check it’s a service invoice",
      ]);
      expect(previewPath({ ...email, documentKinds: [] })).toHaveLength(4);
    });

    it("numbers what was just added as the timeline does, and leaves out what is not on it", () => {
      const own = item({ id: "a", option: "i_will_do_it" });
      const asked = item({ id: "b" });
      const entries = conditionPath({
        id: "c1",
        next_step: null,
        items: [own, asked],
      } as Condition);
      const places = addedPlaces(entries, ["b", "missing"]);
      expect(places.map((place) => [place.item.id, place.first, place.last])).toEqual([
        ["b", 4, 8],
      ]);
      expect(entries[3]?.item?.id).toBe("b");
    });
  });
});

describe("LP-971 follow-up review — the trim and the dropped check row", () => {
  /**
   * `alreadyBehind` returns fixed counts (2 for a sent ask, 4 for one that came back, 2 for her own
   * received task) which assumed every path ended in a "We check it" row. Dropping that row where
   * nothing is checked made those counts one too many, and a RECEIVED task with nothing to check
   * trimmed to NOTHING: no steps on its card, and no entry for `nextOf`, so the condition's "Next:"
   * skipped the task and named the lender's ending while she still had to accept the document.
   */
  const unchecked = (over: Partial<ConditionItem>) =>
    item({ document_kinds: [], has_checks: false, ...over });

  it("leaves her the step she still owes when nothing is checked", () => {
    expect(
      taskPath(unchecked({ option: "i_will_do_it", status: "received" })).map((s) => s.text),
    ).toEqual(["Upload what you get to this task, or mark the task done"]);
    // THE CONTROL: with something to check, the trim is unchanged — the check row is what is left.
    // (The helper's default is `has_checks: true`, so the row is the general sentence.)
    expect(
      taskPath(item({ option: "i_will_do_it", status: "received" })).map((s) => s.text),
    ).toEqual(["We check what you upload"]);
    expect(
      taskPath(
        item({
          option: "i_will_do_it",
          status: "received",
          has_checks: false,
          document_kinds: ["service invoice"],
        }),
      ).map((s) => s.text),
    ).toEqual(["We check it’s a service invoice"]);
  });

  it("leaves an ask that came back visible, and names what is still open", () => {
    const steps = taskPath(unchecked({ status: "received" })).map((s) => s.text);
    expect(steps.length).toBeGreaterThan(0);
    // LP-980 review — the step says "or mark the task done", because with nothing to check that is
    // the only thing left on a document she has already linked.
    expect(steps).toEqual(["Link it to this task, or mark the task done"]);
    // THE CONTROL: with something to check, linking is the whole step and the check is what remains.
    expect(taskPath(item({ status: "received" })).map((s) => s.text)).toEqual([
      "We check it against what was asked",
    ]);
  });

  it("ticks nothing it has not done, in the working view (LP-980 review)", () => {
    // `keepDone` marks the first `alreadyBehind` steps done. For an ask that came back with nothing
    // to check, the path's last step IS the linking that happened, so the view ticked three steps,
    // left "Link it to this task" unticked, and `nextOf` named it as the next thing to do on a
    // document already linked. The step now names her acceptance, so leaving it open is true.
    const ticks = taskPath(unchecked({ status: "received" }), { keepDone: true }).map(
      (step) => `${step.done ? "x" : " "} ${step.text}`,
    );
    expect(ticks).toEqual([
      "x We draft the email to Title / escrow when you confirm the plan",
      "x Review the email, and send it once the plan is confirmed",
      "x Title / escrow sends it back",
      "  Link it to this task, or mark the task done",
    ]);
    // And with a check row the ticks are unchanged: linking is done, the check is what is left.
    expect(
      taskPath(item({ status: "received" }), { keepDone: true })
        .filter((step) => !step.done)
        .map((step) => step.text),
    ).toEqual(["We check it against what was asked"]);
  });

  it("still empties nothing that was not already empty (the controls)", () => {
    // A done task keeps its own sentence, and an open one keeps its whole path.
    expect(taskPath(unchecked({ status: "done" })).map((s) => s.text)).toEqual([
      "This task is done — nothing left on it",
    ]);
    expect(taskPath(unchecked({ status: "open" })).length).toBeGreaterThan(1);
    // A sent ask trims the two that happened, as before.
    expect(taskPath(unchecked({ status: "requested" }))[0]?.text).toBe(
      "Title / escrow sends it back",
    );
  });

  describe("LP-980 — the confirmed plan keeps its done steps", () => {
    const sent = item({
      status: "requested",
      draft: { id: "d1", status: "sent", sent_on: "2026-10-13" },
    });

    it("keeps the steps already done, marked done, and says when it was sent", () => {
      const kept = taskPath(sent, { keepDone: true });
      expect(kept.map((step) => [step.text, step.done === true])).toEqual([
        ["We drafted the email to Title / escrow", true],
        ["Sent 10/13", true],
        ["Title / escrow sends it back", false],
        ["Link it to this task", false],
        ["We check it against what was asked", false],
      ]);
      // THE CONTROL: without keepDone the path starts where the task is, as before.
      expect(taskPath(sent).map((step) => step.text)[0]).toBe("Title / escrow sends it back");
    });

    it("Now passes over what is done", () => {
      const entries = conditionPath({ id: "c1", next_step: null, items: [sent] } as Condition, {
        keepDone: true,
      });
      expect(nextOf(entries)?.text).toBe("Title / escrow sends it back");
    });
  });
});
