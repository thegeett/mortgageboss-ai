"use client";

import { Button } from "@/components/ui/button";
import { PERFORMER_LABEL } from "@/lib/conditions/plan-words";
import type { Performer, PlanOption } from "@/lib/types/conditions";
import { Plus } from "lucide-react";
import { useId, useState } from "react";

/**
 * LP-969 — "Add a step" (the owner, 2026-10-08: "we have to provide a free way to processor, because
 * what if it require upload thing, write draft, or something else"). The agreed design is the "Add a
 * step" menu of the "The plan as a path" board.
 *
 * EVERY BLOCK IS SOMETHING THE SERVER ALREADY DOES; none is a new kind of step. Each one adds a task
 * (`add_item`) or sets the condition's own step (`set_next_step`), so it lands on the timeline and in the
 * history (`item_added`, `next_step`) like any other change:
 * - **Email someone**: a task asking that person. `sync_round_drafts` puts every OPEN ask in its
 *   recipient's draft, so it joins the email to them this round — that is "we still send the emails".
 * - **Ask the borrower to upload**: the same, to the borrower. The borrower's email carries a secure
 *   upload link, minted once the plan is confirmed (LP-968 review); nobody else's does.
 * - **Upload it myself**, **Check a document on the file**, **Something else**: a task for her. Its
 *   first step offers Add document (upload, or link one from the file), and a linked document's checks
 *   run (LP-953); "Check a document" opens the link dialog at once.
 * - **Ask the underwriter**, **Push back**: the condition's OWN step, because the server reads the two
 *   questions from the condition only (`condition_drafts._QUESTIONS`; a task cannot carry one since the
 *   LP-966 review). This is what closes that gap: any condition can now be given one.
 */
export type AddedStep =
  | { kind: "task"; name: string; performers: Performer[]; option: PlanOption; link?: boolean }
  | { kind: "own_step"; option: "ask_underwriter" | "push_back" };

type BlockKey =
  | "email"
  | "upload_ask"
  | "upload_mine"
  | "check"
  | "underwriter"
  | "push_back"
  | "todo";

interface Block {
  key: BlockKey;
  label: string;
  hint: string;
  /** What her words are for; null when the block takes none. */
  prompt: string | null;
  placeholder?: string;
}

const BLOCKS: Block[] = [
  {
    key: "email",
    label: "Email someone",
    hint: "We add it to the email to them this round. You review it before it’s sent.",
    prompt: "What should they send or do?",
    placeholder: "e.g. the final seller CD",
  },
  {
    key: "upload_ask",
    label: "Ask the borrower to upload",
    // SAYS NOTHING ABOUT WHEN (LP-969 review). This read "…once you confirm the plan", which tells her
    // to do something she may have done an hour ago: adding a step to an ALREADY-confirmed round is a
    // normal flow since LP-968, and the link then exists at once. The path's own send step already
    // carries the confirm nuance ("Review the email, and send it once the plan is confirmed"), so the
    // hint does not need to, and a hint that describes one state is wrong in the other.
    hint: "It goes in the borrower’s email, with a secure upload link.",
    prompt: "What should the borrower upload?",
    placeholder: "e.g. the signed letter of explanation",
  },
  {
    key: "upload_mine",
    label: "Upload it myself",
    hint: "A task for you. Upload the document to it, and we check it.",
    prompt: "What will you upload?",
    placeholder: "e.g. the inspection invoice",
  },
  {
    key: "check",
    label: "Check a document on the file",
    hint: "Pick the document from the file, and we check it against this condition.",
    prompt: "What is the document?",
    placeholder: "e.g. the HOA certificate",
  },
  {
    key: "underwriter",
    label: "Ask the underwriter",
    hint: "We draft a question to the underwriter on this condition. Edit it to ask what you need, then send it.",
    prompt: null,
  },
  {
    key: "push_back",
    label: "Push back to the underwriter",
    // THE DRAFT ARGUES ONLY ONE CASE ITSELF (`render_question`): the HOI dates against Must Not Close
    // Before. Any other push back gets the general question, so the hint says she writes the reason.
    hint: "We draft a note to the underwriter on this condition. Edit it to say why it shouldn’t apply, then send it.",
    prompt: null,
  },
  {
    key: "todo",
    label: "Something else",
    hint: "A to-do in your own words, with Mark done.",
    prompt: "What will you do?",
    placeholder: "e.g. call the LO about the fee",
  },
];

/**
 * Who she can email. DERIVED FROM THE PERFORMERS, minus three named exclusions, so a performer added to
 * the vocabulary is offered here without anyone remembering this list: herself (an email to herself is
 * a to-do), the appraiser (appraisal requests go through the lender — `_RECIPIENT` sends the appraiser's
 * asks to the lender, which is already listed), and the ATTORNEY.
 *
 * THE ATTORNEY IS NOT A SECOND DESTINATION (LP-969 review). `condition_plan._RECIPIENT` maps both
 * `title` and `attorney` to the one `title_attorney` email ("Title and attorney share one email",
 * S3-05), so offering both put two labels on one draft: picking Attorney and picking Title produce the
 * same email, and nothing on the screen said so. `item-links.tsx`'s `ASK_WHO` excludes it for this
 * reason already (LP-955 review), and two lists answering "who can I ask?" differently is the thing
 * that invites the next divergence.
 *
 * The LENDER stays, and that IS a deliberate difference from `ASK_WHO`: a free email to the lender is
 * something she does, while delegating a TASK to the lender is not — LP-942 routes an appraiser's or
 * lender's ask into the lender's own draft rather than making it hers.
 */
const NOT_EMAILED: readonly Performer[] = ["processor", "appraiser", "attorney"];
export const EMAIL_WHO: Performer[] = (Object.keys(PERFORMER_LABEL) as Performer[]).filter(
  (who) => !NOT_EMAILED.includes(who),
);

export function AddStep({
  ownStep,
  pending,
  onAdd,
}: {
  /** The condition's own step, so a question block says what it replaces. */
  ownStep: PlanOption | null;
  pending: boolean;
  onAdd: (step: AddedStep) => void;
}) {
  const [open, setOpen] = useState(false);
  const [chosen, setChosen] = useState<Block | null>(null);
  const [words, setWords] = useState("");
  const [who, setWho] = useState<Performer>("borrower");
  const menuId = useId();
  const wordsId = useId();
  const whoId = useId();

  const reset = () => {
    setChosen(null);
    setWords("");
    setOpen(false);
  };
  const add = (block: Block) => {
    const name = words.trim();
    switch (block.key) {
      case "email":
        onAdd({
          kind: "task",
          name,
          performers: [who],
          option: who === "borrower" ? "ask_borrower" : "ask_third_party",
        });
        break;
      case "upload_ask":
        onAdd({ kind: "task", name, performers: ["borrower"], option: "ask_borrower" });
        break;
      case "upload_mine":
      case "todo":
        onAdd({ kind: "task", name, performers: ["processor"], option: "i_will_do_it" });
        break;
      case "check":
        onAdd({
          kind: "task",
          name: `Check ${name}`,
          performers: ["processor"],
          option: "i_will_do_it",
          link: true,
        });
        break;
      case "underwriter":
        onAdd({ kind: "own_step", option: "ask_underwriter" });
        break;
      case "push_back":
        onAdd({ kind: "own_step", option: "push_back" });
        break;
    }
    reset();
  };

  return (
    <div className="flex gap-3">
      <div className="flex w-7 shrink-0 justify-center">
        <span
          aria-hidden
          className="flex h-[26px] w-[26px] items-center justify-center rounded-full border-[1.5px] border-dashed border-primary text-primary"
        >
          <Plus className="h-3.5 w-3.5" />
        </span>
      </div>
      <div className="flex min-w-0 flex-1 flex-col gap-2">
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="self-start"
          aria-expanded={open}
          aria-controls={menuId}
          onClick={() => (open ? reset() : setOpen(true))}
        >
          Add a step
        </Button>
        {open && chosen === null ? (
          <ul
            id={menuId}
            className="grid gap-2 rounded-[var(--radius-container)] border border-border bg-card p-2.5 sm:grid-cols-2"
          >
            {BLOCKS.map((block) => {
              const replaces =
                (block.key === "underwriter" || block.key === "push_back") &&
                ownStep !== null &&
                ownStep !== (block.key === "underwriter" ? "ask_underwriter" : "push_back");
              return (
                <li key={block.key}>
                  <button
                    type="button"
                    onClick={() => (block.prompt === null ? add(block) : setChosen(block))}
                    disabled={pending}
                    className="flex w-full flex-col gap-0.5 rounded-md border border-border px-3 py-2 text-left hover:border-primary/50 hover:bg-primary/5 disabled:opacity-50"
                  >
                    <span className="text-sm font-semibold text-foreground">{block.label}</span>
                    <span className="text-xs text-foreground-2">
                      {block.hint}
                      {replaces ? " It replaces this condition’s own step." : ""}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        ) : null}
        {open && chosen !== null ? (
          <form
            id={menuId}
            className="flex flex-col gap-2 rounded-[var(--radius-container)] border border-border bg-card p-3"
            onSubmit={(event) => {
              event.preventDefault();
              if (words.trim()) add(chosen);
            }}
          >
            <p className="text-sm font-semibold text-foreground">{chosen.label}</p>
            <p className="text-xs text-foreground-2">{chosen.hint}</p>
            {chosen.key === "email" ? (
              <div className="flex flex-col gap-1">
                <label htmlFor={whoId} className="text-xs font-medium text-foreground-2">
                  To
                </label>
                <select
                  id={whoId}
                  value={who}
                  onChange={(event) => setWho(event.target.value as Performer)}
                  className="h-8 w-auto self-start rounded-md border border-input bg-card px-1.5 text-sm"
                >
                  {EMAIL_WHO.map((each) => (
                    <option key={each} value={each}>
                      {PERFORMER_LABEL[each]}
                    </option>
                  ))}
                </select>
              </div>
            ) : null}
            <div className="flex flex-col gap-1">
              <label htmlFor={wordsId} className="text-xs font-medium text-foreground-2">
                {chosen.prompt}
              </label>
              <input
                id={wordsId}
                type="text"
                value={words}
                maxLength={190}
                placeholder={chosen.placeholder}
                onChange={(event) => setWords(event.target.value)}
                className="h-8 rounded-md border border-input bg-card px-2 text-sm text-foreground"
              />
            </div>
            <div className="flex gap-2">
              <Button type="submit" size="sm" disabled={pending || !words.trim()}>
                Add the step
              </Button>
              <Button type="button" size="sm" variant="ghost" onClick={reset}>
                Cancel
              </Button>
            </div>
          </form>
        ) : null}
      </div>
    </div>
  );
}
