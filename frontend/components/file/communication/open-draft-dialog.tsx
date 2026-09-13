"use client";

/**
 * "There is already an open draft" — one dialog, three callers (LP-851). Screens 3, 4 and 5.
 *
 * ONE COMPONENT BECAUSE THERE IS ONE DECISION. The individual request on a finding, "Request all N"
 * and the catalog's Generate all hit the same 409 from LP-850 and send back the same single
 * `on_conflict` value. Nothing here decides anything: it renders a refusal and returns an answer.
 *
 * NEVER TWO DIALOGS IN SEQUENCE. A request spanning two parties gets a row per party in THIS
 * dialog. A processor who has just confirmed five documents and is then asked a second question
 * clicks the primary without reading it, which is exactly how the wrong draft gets chosen.
 *
 * A PARTY WITH NOTHING OPEN STILL GETS A ROW, with no buttons. It needs no decision, and the
 * processor must leave knowing a second message exists — LP-852's rule, appearing here because this
 * is where the second message is created.
 */

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { ConflictChoice, ConflictNeed, DraftConflict } from "@/lib/api/draft-conflict";
import { partyNoun } from "@/lib/api/draft-conflict";
import { messageTimeFull } from "@/lib/message-time";

/** The document names, as the chips Screen 3 shows. */
function Chips({ needs, prefix = "" }: { needs: ConflictNeed[]; prefix?: string }) {
  if (needs.length === 0) return null;
  return (
    <ul className="flex flex-wrap gap-1">
      {needs.map((need) => (
        <li
          key={need.id}
          className="rounded border border-border bg-muted px-1.5 py-0.5 text-xs text-foreground-2"
        >
          {prefix}
          {need.title}
        </li>
      ))}
    </ul>
  );
}

/**
 * "You have edited this draft" — Screen 5.
 *
 * IT QUOTES THEIR OWN SENTENCE. "Your changes will be lost" is abstract and gets dismissed; their
 * own words do not. The quote is rendered as TEXT — React escapes it, and it is the one place in
 * this feature where a fragment of authored prose travels outside the body column, so it must not
 * be treated as markup anywhere on the way.
 *
 * NOT IN PLEX SERIF ITALIC, and that was the first thing written here. AMENDMENTS A18 reserves that
 * face for "text quoted verbatim from a DOCUMENT" and says so exceptionlessly — "nothing decorative
 * may borrow it" — because its whole value is that it reads as the document speaking without a
 * label. A processor's own sentence is not a document, and borrowing the face here would spend that
 * meaning on the one screen where the reader is the author. Quotation marks carry it instead.
 */
function EditedWarning({ excerpt }: { excerpt: string | null }) {
  return (
    <div className="border-l-2 border-warning bg-warning/5 px-3 py-2 text-xs text-foreground-2">
      <span className="font-medium text-foreground">You have edited this draft.</span> Adding a
      document rewrites the message from the template, and your changes
      {excerpt ? (
        <>
          {" — including "}
          <span className="text-foreground">“{excerpt}”</span>
          {" — "}
        </>
      ) : (
        " "
      )}
      will be lost. Copy anything you want to keep first.
    </div>
  );
}

/** One party whose draft is already open — the block Screen 4 describes. */
function DecisionBlock({
  party,
  openedAt,
  carrying,
  adding,
  bodyEdited,
  excerpt,
  multiple,
  pending,
  onChoose,
}: {
  party: string;
  openedAt: string;
  carrying: ConflictNeed[];
  adding: ConflictNeed[];
  bodyEdited: boolean;
  excerpt: string | null;
  multiple: boolean;
  pending: boolean;
  onChoose: (choice: ConflictChoice) => void;
}) {
  const noun = partyNoun(party);
  return (
    <div className={multiple ? "border border-border p-3" : ""}>
      {multiple ? (
        <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-primary">
          {noun} · a draft is already open
        </p>
      ) : null}

      <div className="flex flex-col gap-2 text-sm text-foreground-2">
        <Chips needs={adding} prefix="+ " />
        <p className="text-xs text-muted-foreground">
          {/* Screen 4 renders this as "Tue 14:02". `messageTimeFull` is the formatter this
              feature already has, and it is unambiguous past a week — which a draft left open over
              a weekend is. A third date format for one sentence is how two screens start
              disagreeing about when something happened. */}
          Open since {messageTimeFull(openedAt)}, asking for {carrying.length} document
          {carrying.length === 1 ? "" : "s"}.
        </p>
        {!multiple ? <Chips needs={carrying} /> : null}
      </div>

      {bodyEdited ? (
        <div className="mt-3">
          <EditedWarning excerpt={excerpt} />
        </div>
      ) : null}

      {/* LP-851 REVIEW — NO BUTTONS ON A PARTY ROW, because a party row cannot be answered on its
          own. `on_conflict` is ONE value for the whole request: LP-850 plans every party and
          applies the single answer to all of them. These buttons called the same global `onChoose`
          as the footer, so pressing "Mark sent, start new" inside the BORROWER's block marked the
          LENDER's draft sent too — stamping `requested_at`, writing an evidence row and moving its
          needs to REQUESTED for a draft the processor never looked at.

          The comment on the footer said "the per-party buttons above answer for one party each",
          which is what made this invisible: the belief was in the file and the behaviour was not.
          A row is now informational in the multi-party case, which is the same shape a
          `would_create` row already has, and the whole request is answered once at the bottom. */}
    </div>
  );
}

/** A party with nothing open — no decision, and they must still know it exists. */
function NewDraftBlock({
  party,
  address,
  needs,
}: {
  party: string;
  address: string | null;
  needs: ConflictNeed[];
}) {
  return (
    <div className="border border-border p-3">
      <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
        {partyNoun(party)} · a new draft
      </p>
      <Chips needs={needs} prefix="+ " />
      <p className="mt-2 text-xs text-muted-foreground">
        {address
          ? `Nothing open — this creates a draft to ${address}.`
          : "Nothing open — this creates a draft, with no address on file yet."}
      </p>
    </div>
  );
}

/**
 * The party blocks, without a dialog around them (LP-851, Screen 6).
 *
 * EXPORTED BECAUSE "REQUEST ALL N" ALREADY HAS A DIALOG. Its confirm keeps its own title and
 * document list and GAINS these blocks when a draft is open — never a second dialog after the
 * first, because a processor who has just confirmed five documents and is then asked another
 * question clicks the primary without reading it. One set of blocks, rendered in two places, so the
 * two cannot drift into describing the same refusal differently.
 */
export function ConflictBlocks({
  conflict,
  multiple,
  pending,
  onChoose,
}: {
  conflict: DraftConflict;
  multiple: boolean;
  pending: boolean;
  onChoose: (choice: ConflictChoice) => void;
}) {
  return (
    <div className="flex flex-col gap-3">
      {conflict.decisions_required.map((decision) => (
        <DecisionBlock
          key={decision.party}
          party={decision.party}
          openedAt={decision.open_draft.created_at}
          carrying={decision.open_draft.needs}
          adding={decision.adding}
          bodyEdited={decision.open_draft.body_edited}
          excerpt={decision.open_draft.edited_excerpt}
          multiple={multiple}
          pending={pending}
          onChoose={onChoose}
        />
      ))}
      {conflict.would_create.map((plan) => (
        <NewDraftBlock
          key={plan.party}
          party={plan.party}
          address={plan.address}
          needs={plan.needs}
        />
      ))}
    </div>
  );
}

/** Whether this refusal needs the several-party layout. */
export function isMultiParty(conflict: DraftConflict): boolean {
  return conflict.decisions_required.length + conflict.would_create.length > 1;
}

/** Whether any open draft in this refusal carries a processor's own words. */
export function isEdited(conflict: DraftConflict): boolean {
  return conflict.decisions_required.some((decision) => decision.open_draft.body_edited);
}

export function OpenDraftDialog({
  conflict,
  pending = false,
  onCancel,
  onChoose,
}: {
  /** LP-850's refusal, or null when there is nothing to decide. */
  conflict: DraftConflict | null;
  pending?: boolean;
  onCancel: () => void;
  onChoose: (choice: ConflictChoice) => void;
}) {
  const open = conflict !== null;
  const decisions = conflict?.decisions_required ?? [];
  const creating = conflict?.would_create ?? [];
  // SEVERAL BLOCKS WHEN THE REQUEST TOUCHES SEVERAL PARTIES — one of them being a party that needs
  // no decision. Screen 4's shape, and the reason a `would_create` row alone still widens the
  // dialog: the processor has to leave knowing that message exists.
  const multiple = conflict !== null && isMultiParty(conflict);
  const single = decisions[0];
  const edited = conflict !== null && isEdited(conflict);

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onCancel()}>
      <DialogContent className={multiple ? "sm:max-w-[34rem]" : "sm:max-w-lg"}>
        <DialogHeader>
          <DialogTitle className="text-base">
            {multiple
              ? `This request goes to ${decisions.length + creating.length} people`
              : `There is already an open draft to the ${partyNoun(single?.party ?? "borrower")}`}
          </DialogTitle>
          {!multiple && single ? (
            <DialogDescription className="text-xs">
              Add{" "}
              <span className="text-foreground">
                {single.adding.map((need) => need.title).join(", ")}
              </span>{" "}
              to it — or, if you have already sent that draft from your mail client, mark it sent
              and start a new one.
            </DialogDescription>
          ) : null}
        </DialogHeader>

        {conflict ? (
          <ConflictBlocks
            conflict={conflict}
            multiple={multiple}
            pending={pending}
            onChoose={onChoose}
          />
        ) : null}

        <div className="flex flex-wrap justify-end gap-2 border-t border-border pt-3">
          <Button variant="ghost" disabled={pending} onClick={onCancel}>
            Cancel
          </Button>
          {multiple ? (
            // ONE ANSWER FOR THE WHOLE REQUEST, and both readings of it. `on_conflict` travels once
            // per request, so this is the only place either choice can be made — and a multi-party
            // refusal that offered only `append` would leave a processor who HAS sent those drafts
            // with no way to say so except cancelling.
            <>
              <Button
                variant="outline"
                disabled={pending}
                onClick={() => onChoose("mark_sent_and_new")}
              >
                I&apos;ve sent them — mark all sent, start new
              </Button>
              <Button disabled={pending} onClick={() => onChoose("append")}>
                Do both
              </Button>
            </>
          ) : (
            <>
              <Button
                variant="outline"
                disabled={pending}
                // "I'VE SENT IT", NOT "MARK AS SENT". Nothing here observed a send — the record it
                // writes reads `Marked sent by Priya · Tue 16:41`. A neutral label invites pressing
                // it to dismiss the dialog, which is how `requested_at` ends up stamped on a message
                // that never went out.
                onClick={() => onChoose("mark_sent_and_new")}
              >
                I&apos;ve sent it — mark sent, start new
              </Button>
              <Button disabled={pending} onClick={() => onChoose("append")}>
                {edited ? "Add anyway" : "Add to the open draft"}
              </Button>
            </>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
