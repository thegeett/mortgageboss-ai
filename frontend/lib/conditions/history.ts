/**
 * One condition's history, in the processor's words — S2-03's History section (LP-916).
 *
 * A SECOND VOCABULARY, AND THE DUPLICATION IS ONLY APPARENT. `round-details-sheet.tsx` already turns
 * a `ConditionEvent` into a sentence, and at first glance this is that function again. It is not:
 * the two have different SUBJECTS. On S1-09 the reader is looking at a round, so
 * `condition_seen_again` reads "A condition was seen again" — one of thirty such lines. Here the
 * reader is looking at one condition, and the same event must read "Seen again in round 2". A single
 * function cannot say both, and making one say the other would be wrong on one of the two screens.
 *
 * THIS ONE IS EXHAUSTIVE AND THAT ONE IS NOT, WHICH IS THE OTHER REAL DIFFERENCE. `historyLine` ends
 * in a `default:` arm — correct there, because a browser may run against a backend one deploy ahead
 * and "Something happened to this round" is an honest degradation. LP-916's Done-when is stricter:
 * *every* event kind has a plain sentence, with a test that fails if a new kind has none. So the
 * switch below is exhaustive over the union and the `never` check makes a new kind a BUILD error
 * rather than a sentence somebody remembers to add.
 *
 * WHAT THESE SENTENCES MAY NOT SAY. `ConditionEventPublic` projects named scalars and never `detail`,
 * because that column is NPI — the lender's wording. One design line is therefore poorer than the
 * mockup, and it is a recorded decision:
 *
 *   * S2-03 draws `Underwriter note added in round 1: “8/28 Not in Upload”`. The quote is the
 *     lender's text and does not travel; the line keeps everything else.
 *
 * (A second line, `Imported from round 1 (PDF upload, printed 08/28)`, was first dropped on the same
 * grounds. LP-916's review restored it: neither fact is NPI, and both come from the ROUND the detail
 * read already returns, so nothing is projected out of `detail`. See `importedFrom`.)
 *
 * THE STATUS WORDS COME FROM `lib/status.ts`, never retyped here. "Waiting on someone" and "Came
 * back" are the words the controls, the refusal sentences and the chips already use; a second copy
 * is how a history line ends up calling something by a name no control offers.
 */
import { waitingLabel } from "@/lib/conditions/next-step";
import { OPTION_LABEL } from "@/lib/conditions/plan-words";
import { CONDITION_LENDER_STATUS, CONDITION_PREP_STATUS } from "@/lib/status";
import type {
  ConditionEvent,
  ConditionRoundAppearance,
  ConditionSourceKind,
  DraftRecipient,
} from "@/lib/types/conditions";

/** How a round arrived, in the words S2-03 uses ("PDF upload"). */
const ARRIVAL_LABEL: Record<ConditionSourceKind, string> = {
  pdf_upload: "PDF upload",
  email: "email",
  paste: "paste",
  manual: "added by hand",
};

/** `2026-09-12` → `09/12`, the short form the history lines use beside a status. */
function shortDate(iso: string | null): string | null {
  if (!iso) return null;
  const [, month, day] = iso.split("-");
  return month && day ? `${month}/${day}` : iso;
}

/**
 * "(PDF upload, printed 08/28)" for the round an import came from, or nothing.
 *
 * FROM THE ROUND, NOT FROM THE EVENT (LP-916 review). `condition_created` stores neither fact, but
 * the detail read already carries each round's arrival kind and printed date, and neither is NPI.
 */
function importedFrom(event: ConditionEvent, rounds: ConditionRoundAppearance[]): string {
  const round = rounds.find((r) => r.round_number === event.round_number);
  if (!round) return "";
  const parts = [
    round.arrived_as ? ARRIVAL_LABEL[round.arrived_as] : null,
    round.date_printed ? `printed ${shortDate(round.date_printed)}` : null,
  ].filter((part): part is string => part !== null);
  return parts.length > 0 ? ` (${parts.join(", ")})` : "";
}

/** "in round 2", or nothing when the event names no round. */
function inRound(event: ConditionEvent): string {
  return event.round_number === null ? "" : ` in round ${event.round_number}`;
}

/** " — Priya Raman", or nothing for a system event. Never a placeholder: "—" reads as a name. */
/** How a history line names a draft email (LP-922). */
const EMAIL_NAME: Record<DraftRecipient, string> = {
  borrower: "borrower email",
  title_attorney: "title email",
  lo: "LO email",
  insurance: "insurance email",
  hoa: "HOA email",
  employer: "employer email",
  other_party: "email to the other party",
  underwriter: "question to the underwriter",
  lender: "email to the lender",
};

function by(event: ConditionEvent): string {
  return event.actor_name ? ` — ${event.actor_name}` : "";
}

/**
 * Where the lender said it, as the tail of a verdict line.
 *
 * TWO SHAPES, BECAUSE TWO KINDS OF SOURCE ARE NOT THE SAME CLAIM. The app DERIVES
 * `round_comparison` and `underwriter_note` from a sheet, so the line names the sheet ("from the
 * round 2 comparison"). A person picks portal, email or phone, so the line names the place and the
 * lender's date ("(portal, 09/12)"). Rendering a derived source as "(round_comparison, 09/10)" would
 * make an inference look like something somebody was told.
 */
function fromSource(event: ConditionEvent): string {
  const when = shortDate(event.verdict_source_date);
  switch (event.verdict_source_kind) {
    case "round_comparison":
      return event.round_number === null
        ? " from the round comparison"
        : ` from the round ${event.round_number} comparison`;
    case "underwriter_note":
      return when ? ` from the lender’s ${when} note` : " from the lender’s note";
    case "portal":
    case "email":
    case "phone":
      return when ? ` (${event.verdict_source_kind}, ${when})` : ` (${event.verdict_source_kind})`;
    default:
      return "";
  }
}

/**
 * What a `not_cleared` verdict or a came-back did to OUR track, as a trailing clause.
 *
 * THE MOVE MUST NOT BE SILENT, which is the whole reason the from→to pair is on the event. A
 * processor records "the underwriter phoned and refused it" and the row jumps to *To do*; without
 * this clause the screen changes their work with no explanation. S2-08 already draws the sentence for
 * the note-driven route — "our status moved from Sent to lender back to To do" — and this is the same
 * sentence for the manual one, because one status with two explanations is what the review objected to.
 */
function ourTrackMoved(event: ConditionEvent): string {
  const from = event.prep_status_from;
  const to = event.prep_status_to;
  if (!from || !to || from === to) return "";
  return ` · our status moved from ${CONDITION_PREP_STATUS[from].label} back to ${CONDITION_PREP_STATUS[to].label}`;
}

/**
 * One line of a condition's history (S2-03).
 *
 * Exhaustive over `ConditionEventKind`: the `never` assignment below is a compile error the moment
 * the union grows, which is LP-916's "a test that fails if a new kind has none" enforced by `tsc`
 * rather than at runtime. `lib/conditions/history.test.ts` pins the same property from the other
 * side, for the case where someone satisfies the compiler with an empty string.
 */
export function conditionHistoryLine(
  event: ConditionEvent,
  rounds: ConditionRoundAppearance[] = [],
): string {
  switch (event.kind) {
    // --- this condition ---------------------------------------------------- //
    case "condition_created":
      // A hand-typed condition was not "imported from" anywhere — it was filed INTO a round, and
      // S1-12's whole point is that the two stay distinguishable.
      return event.round_number === null
        ? "Added to this file"
        : `Imported from round ${event.round_number}${importedFrom(event, rounds)}`;
    case "condition_seen_again":
      return `Seen again${inRound(event)}`;
    case "condition_note_added": {
      const count = event.notes_added ?? 1;
      return `Underwriter note${count === 1 ? "" : "s"} added${inRound(event)}`;
    }
    case "condition_edited":
      return `The wording was edited${by(event)}`;
    case "condition_prep_moved": {
      const to = event.prep_status_to;
      // "Moved to Waiting on Borrower" (S2-03) names the owner. `unknown` keeps the generic label:
      // "Waiting on Owner not known" would read worse than "Waiting on someone".
      // THE SEND MOVED IT (LP-922): "Moved to Waiting on Borrower (borrower email marked sent)".
      const sent = event.draft_recipient
        ? ` (${EMAIL_NAME[event.draft_recipient]} marked sent)`
        : "";
      if (to === "waiting" && event.waiting_on && event.waiting_on !== "unknown") {
        // "Waiting on LO", as the status select says it (LP-934 M5).
        return `Moved to Waiting on ${waitingLabel(event.waiting_on)}${sent}${by(event)}`;
      }
      // THE PLAN MOVED IT (LP-921), SO THE LINE SAYS WHICH STEP: "Moved to Ready to send (Already in
      // the file)". Without it the line reads as though she picked the status herself.
      const step = event.plan_option ? ` (${OPTION_LABEL[event.plan_option]})` : "";
      return to
        ? `Moved to ${CONDITION_PREP_STATUS[to].label}${step}${by(event)}`
        : `Moved${by(event)}`;
    }
    case "condition_verdict_recorded": {
      const to = event.lender_status_to;
      // "Marked Cleared (portal, 09/12) — Priya Raman", and the tail says where it came from because
      // NOTHING MAY SHOW "Cleared" WITHOUT SAYING WHO SAID SO (ADR-404).
      const what = to ? CONDITION_LENDER_STATUS[to].label : "the lender’s answer";
      return `Marked ${what}${fromSource(event)}${by(event)}${ourTrackMoved(event)}`;
    }
    case "condition_came_back":
      // The one line the app writes with nobody clicking, so it names the note that caused it.
      return `Came back${fromSource(event)}${ourTrackMoved(event)}`;
    case "condition_reopened":
      return `Reopened${by(event)}`;
    case "condition_owner_changed":
      return `Owner changed${by(event)}`;
    case "condition_superseded":
      return `Replaced by a later condition${by(event)}`;
    case "condition_read":
      return "Read into items";
    case "condition_reading_confirmed":
      return `The reading was confirmed${by(event)}`;
    case "condition_planned":
      return "Plan proposed";
    case "condition_plan_changed":
      return `The plan was changed${by(event)}`;
    case "condition_draft_polished":
      return event.draft_recipient
        ? `The ${EMAIL_NAME[event.draft_recipient]} was polished by AI${by(event)}`
        : `A draft email was polished by AI${by(event)}`;
    // LP-923. NO FIGURE, NO REASON: the detail carries counts, and her reason stays on the evidence
    // row (the sheet shows it) rather than travelling in the history's allow-list.
    case "condition_evidence_checked":
      return "A document arrived and was checked by code";
    case "condition_evidence_accepted":
      return `A failed check was accepted${by(event)}`;
    case "condition_finding_answered":
      return `A finding on the evidence was answered${by(event)}`;
    // LP-941 — THE REASON IS SHOWN, by the owner's decision (LP-940 left it out). It is the one
    // free-text field the server projects, and only on this kind; after an Undo this line stays, so
    // she can still see why, and the Undo adds its own line below it.
    case "condition_withdrawn":
      return event.withdrawal_reason
        ? `Withdrawn as entered in error — “${event.withdrawal_reason}”${by(event)}`
        : `Withdrawn as entered in error${by(event)}`;
    case "condition_restored":
      return `Withdrawal undone${by(event)}`;
    // LP-949 — the file's lender was set, or a code was confirmed, and this untyped condition took its
    // type from the lender's code map. The label is the library's, from a closed vocabulary.
    case "condition_typed":
      return event.typed_as
        ? `Matched to the library: ${event.typed_as}${by(event)}`
        : `Matched to the library${by(event)}`;
    case "condition_drafted":
      return event.draft_recipient
        ? `Added to the ${EMAIL_NAME[event.draft_recipient]}`
        : "Added to a draft email";

    // --- the round it sits on ---------------------------------------------- //
    //
    // THESE DO NOT NORMALLY APPEAR HERE. `events_for_condition` selects rows with this condition's
    // id, and round-level events carry `condition_id = NULL` — a round's history is the other
    // screen's question. They are answered anyway because the union includes them and this switch is
    // exhaustive by design: a sentence that cannot render beats a build that cannot compile.
    case "round_lender_declined":
      return `The lender the sheet named was marked not this file’s${by(event)}`;
    case "round_received":
      return "The lender’s sheet arrived";
    case "round_parsed":
      return "The sheet was read";
    case "round_parse_failed":
      return "The sheet could not be read";
    case "round_reparse_requested":
      return "The sheet was read again";
    case "round_imported":
      return event.round_number === null
        ? "The round was imported"
        : `Round ${event.round_number} was imported`;
    case "round_discarded":
      return "The round was discarded";
    case "round_enriched":
      return "The lender’s PDF was attached to the round";
    case "round_compared":
      return event.round_number === null
        ? "Compared with the round before it"
        : `Compared with round ${event.round_number}`;
    case "round_completeness_changed":
      return "The round’s completeness was changed";
    case "round_plan_confirmed":
      return "The round’s plan was confirmed";
    default: {
      // EXHAUSTIVENESS, CHECKED BY THE COMPILER. If `ConditionEventKind` grows a member, `kind` is no
      // longer `never` here and `tsc` fails — which is LP-916's Done-when, enforced at build time
      // rather than by anyone remembering to add a sentence.
      const unreachable: never = event.kind;
      return unreachable;
    }
  }
}
