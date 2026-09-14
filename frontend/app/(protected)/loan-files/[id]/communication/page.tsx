"use client";

import { ComposeRequestButton } from "@/components/file/communication/compose-request-button";
import { InboundMessagesPanel } from "@/components/file/communication/inbound-messages-panel";
import { DraftPane } from "@/components/file/communication/message-dialog";
import { TimelinePanel } from "@/components/file/communication/timeline-panel";
import { UploadLinkPanel } from "@/components/file/communication/upload-link-panel";
import { Button } from "@/components/ui/button";
import { useCapabilities } from "@/lib/api/capabilities";
import { useComposeDraft } from "@/lib/api/messages";
import { useTimeline } from "@/lib/api/timeline";
import { getErrorMessage } from "@/lib/errors/api-error";
import { notifyError } from "@/lib/toast";
import { useParams, useSearchParams } from "next/navigation";
import { useState } from "react";

/**
 * Communication — the file's mailbox.
 *
 * LP-858 §2 — TWO PANES, AND THE SPLIT IS THE LANDING STATE. List left at a fixed 300px, the
 * selected draft right. It is not something a click produces: a list that opened full-width and
 * collapsed on selection is a layout jump on every click, and this list is per loan file, so it
 * holds one to three rows rather than an inbox's worth.
 *
 * NOTHING HERE IS A MODAL any more except the two genuine interruptions — the mail-client question
 * and the delete confirm — which overlay the right pane and leave it visible. Reading a draft was a
 * `Dialog`, so it came with a scrim and closed the list behind it; comparing two drafts meant
 * closing one to see the other.
 *
 * LP-857 — THE PAGE DOES NOT OFFER WHAT THE VERSION CANNOT DO. *"No receiving, sending, secure
 * upload link, reply email and all."* A processor cannot tell a feature that is broken from one
 * that was never wired.
 */
export default function CommunicationPage() {
  const { id } = useParams<{ id: string }>();
  const receiving = useCapabilities().data?.receiving ?? false;

  // THE FILE'S OWN TRUTH, not the rail's view of it. The list has status pills, so what it is
  // showing depends on which one is pressed — and "does this file have any drafts", which decides
  // whether there is a split at all, must not change when a processor clicks "Sent".
  const { data: timeline, isPending } = useTimeline(id, "all");
  const entries = timeline?.entries ?? [];
  const openDrafts = entries.filter(
    (entry) =>
      entry.kind === "message" && entry.direction === "outbound" && entry.status === "draft",
  );

  // LP-858 §2.1 rule 1 — A DRAFT NAMED IN THE URL WINS. Selection is URL-driven so a toast can link
  // straight to a draft and a reload keeps the same one open.
  //
  // OPTIONAL, because `useSearchParams()` is null outside a router context — not only a test
  // artefact, it is also the value during a static render.
  const searchParams = useSearchParams();
  const linkedDraft = searchParams?.get("draft") ?? null;
  // SEEDED FROM THE URL, not merely watched. Starting at `null` and only reacting to a CHANGE means
  // the parameter loses on the very render it is supposed to win: on mount `seededFromUrl` already
  // equals it, so the comparison below never fires and the newest draft is auto-selected instead.
  // That is the one render a deep link exists for.
  const [chosen, setChosen] = useState<string | null>(linkedDraft);
  // Tracked rather than compared against `chosen`: after a processor CLOSES the linked draft the
  // parameter is still in the URL, and re-selecting it on the next render would make the pane
  // impossible to dismiss.
  const [seededFromUrl, setSeededFromUrl] = useState<string | null>(linkedDraft);
  const [closed, setClosed] = useState(false);
  // Rows deleted during THIS visit. Held because the timeline refetch is not instant: for the frame
  // between the 204 and the new list arriving, the deleted row is still in `entries` and rule 6's
  // "select the next newest" would land straight back on it.
  const [deletedIds, setDeletedIds] = useState<Set<string>>(() => new Set());
  if (linkedDraft !== seededFromUrl) {
    setSeededFromUrl(linkedDraft);
    setChosen(linkedDraft);
    setClosed(false);
  }

  // LP-858 §2.1 rule 5 — STACKED LAYOUT SELECTS NOTHING. The panes are vertical below ~720px, so
  // auto-selecting pushes the list off-screen and hides the thing that orients the processor. The
  // list is the screen there; tapping a row opens the draft.
  //
  // Read once on mount rather than subscribed: this decides a DEFAULT, and a processor who resizes
  // mid-session has already chosen a row or has the list in front of them either way. Guarded for
  // the server render, where there is no window.
  // GUARDED, not assumed. `matchMedia` is absent during the server render and absent in jsdom, and
  // an unguarded call throws before anything renders — the whole tab, gone, because of a default.
  // Absent means "not narrow", which selects a draft: the desktop behaviour, and the safe way round
  // if the answer is unavailable.
  const [narrow] = useState(
    () =>
      typeof window !== "undefined" &&
      typeof window.matchMedia === "function" &&
      window.matchMedia("(max-width: 720px)").matches,
  );

  // §2.1 rule 2 — otherwise the NEWEST OPEN DRAFT, and rule 3 — never a sent message. The right
  // pane is never a dead panel on a file that has work outstanding, and a read-only record is not
  // what the processor came for. Safe because opening a draft has no side effect: autosave is
  // guarded by `dirtyRef` and only marks dirty when the html differs from what the pane opened
  // with, so selecting one cannot write to it.
  // §2.1 rule 6 — NEVER LEAVE THE PANE SHOWING A DELETED ROW. `chosen` is not validated against the
  // list in general — a stale `?draft=` parameter renders "this message could not be loaded", which
  // is the honest answer for a link to something that is gone. A DELETE is different: the processor
  // just did it on purpose, and an error message for their own successful action is the one case
  // where that answer is wrong.
  // LP-859 REVIEW — NAMED FOR WHAT IT HOLDS. This was `deleted`, and it holds the opposite: the
  // chosen id when it is still LIVE, and null once the processor has deleted it. `selected =
  // deleted ?? autoSelected` therefore read as "the deleted one, or the auto-selected one" in the
  // one expression that decides whether the pane can show a row that is gone.
  //
  // It stays separate from `liveDrafts` deliberately: `chosen` can be a SENT message, which is not
  // in `openDrafts` at all, so testing membership of the live drafts would drop a sent row out of
  // the pane the moment a processor clicked one.
  const chosenIfLive = deletedIds.has(chosen ?? "") ? null : chosen;
  // LP-859 §4 — ONE LIST OF WHAT IS STILL SELECTABLE, derived once.
  //
  // The timeline refetch is not instant, so for the frame between the 204 and the new list a
  // deleted row is still in `entries`. Two places need to know what is left — which draft to select,
  // and which of the two empty states the pane shows — and deriving it twice is how they disagree:
  // the first version of §4's branch tested `openDrafts.length` and showed the third empty state
  // after the LAST draft was deleted, over a rail about to have nothing to select.
  const liveDrafts = openDrafts.filter((draft) => !deletedIds.has(draft.id));
  const autoSelected = narrow || closed ? null : (liveDrafts[0]?.id ?? null);
  const selected = chosenIfLive ?? autoSelected;

  const compose = useComposeDraft(id);
  function startCompose() {
    // §8 — THE ROW IS CREATED WHEN COMPOSE IS PRESSED, not on the first keystroke. It appears in
    // the list immediately as "New message" / "Nothing written yet". The abandoned-empty-draft case
    // — browser closed rather than ✕ pressed — is accepted knowingly; no sweep is built for it.
    compose.mutate(
      {},
      {
        onSuccess: (draft) => {
          setChosen(draft.id);
          setClosed(false);
        },
        onError: (error) =>
          notifyError({ title: "Couldn’t start the draft", whatToDo: getErrorMessage(error) }),
      },
    );
  }

  const composeButton = (
    <Button
      type="button"
      size="sm"
      variant="outline"
      disabled={compose.isPending}
      onClick={startCompose}
    >
      + Compose
    </Button>
  );

  // §2.1 rule 4 — NO DRAFTS AND NO HISTORY IS ONE FULL-WIDTH EMPTY STATE. Do not render an empty
  // rail beside an empty pane: a 300px column of nothing next to a larger area of nothing is two
  // pieces of furniture for a file with no work on it.
  //
  // SENT MESSAGES BUT NO OPEN DRAFTS IS DIFFERENT and the split still renders — history is worth
  // seeing, an empty file is not worth a rail. That distinction is why this tests `entries`, not
  // `openDrafts`.
  if (!isPending && entries.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 py-16 text-center">
        <h2 className="text-base font-semibold text-foreground">No drafts on this file</h2>
        <p className="text-sm text-muted-foreground">
          Request documents from a finding, or write a message.
        </p>
        <div className="flex flex-wrap items-center justify-center gap-2">
          <ComposeRequestButton fileId={id} />
          {composeButton}
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-8">
      {/* BELOW ~720px THE PANES STACK, list first, draft under it — `flex-col` until `md`. Above it
          the rail is a fixed 300px: wide enough for party, subject preview, document count and
          time. A narrower rail that can only hold a name and a timestamp is what makes a full-width
          list tempting, and the fix is the width rather than the pattern. */}
      <div className="flex flex-col gap-6 md:flex-row md:items-start">
        <div className="flex w-full shrink-0 flex-col gap-2 md:w-[300px]">
          <div className="flex items-center justify-end">
            {/* LP-833 — asking for a document no rule flagged. LP-856 — a draft with no documents
                behind it, outline to "Request documents"' primary. */}
            <ComposeRequestButton fileId={id} />
            {composeButton}
          </div>
          <TimelinePanel fileId={id} selectedId={selected} onSelect={setChosen} />
        </div>
        <div className="min-w-0 flex-1">
          {selected ? (
            <DraftPane
              fileId={id}
              messageId={selected}
              onDeleted={(draftId) => {
                // §2.1 rule 6 — the next newest open draft, or the empty state. `closed` stays
                // false HERE, because a delete is not a close: the processor is still working, and
                // the next draft is what they want in front of them.
                //
                // LP-859 §4 — AND THAT IS TRUE OF ONE OF THE TWO CALLERS, which this comment used
                // to claim of both. `removeDraft` (the Delete button) calls `onDeleted` alone, so
                // the next draft is selected. The ✕-discard path in `close()` calls `onDeleted` AND
                // `onClose`, so `closed` becomes true and nothing is selected — which is RIGHT, and
                // is why the Delete button never showed §4's false sentence while ✕ always did.
                // The processor pressed ✕: they closed. Left as it is, and the empty state below
                // now says which of the two happened rather than claiming the file has no drafts.
                setDeletedIds((seen) => new Set(seen).add(draftId));
                setChosen(null);
              }}
              onClose={() => {
                setChosen(null);
                // CLOSING MEANS CLOSED, and the auto-selection must not immediately undo it. Rule 2
                // picks the newest open draft on LOAD; without this the ✕ would re-open the same
                // draft on the next render and the pane could never be dismissed.
                setClosed(true);
              }}
            />
          ) : isPending ? (
            // LP-859 REVIEW — NEITHER EMPTY STATE IS TRUE BEFORE THE LIST ARRIVES.
            //
            // `isPending` gates only the full-width branch above, so a file that HAS drafts fell
            // through here on every visit with `entries` still empty, and the pane rendered "No
            // drafts on this file" for a frame — the exact sentence this section exists to stop it
            // saying, arriving by the one route the section did not look at. Measured, not
            // inferred: rendering the page with `isPending: true` finds that heading in the
            // document.
            //
            // SO IT SAYS NOTHING IT DOES NOT KNOW. Both branches below are claims about a list
            // that has not loaded; the honest answer for that frame is the one the rail is already
            // giving — that it is still arriving.
            <p className="py-16 text-center text-sm text-muted-foreground">Loading this file…</p>
          ) : liveDrafts.length === 0 ? (
            // §2.1 rule 4's second half: sent history with nothing open carries the same empty
            // state INSIDE the right pane. THIS ONE IS TRUE — there really are no drafts, and it
            // is reached only once the list has actually arrived (see the branch above).
            <div className="flex flex-col items-center justify-center gap-3 py-16 text-center">
              <h2 className="text-base font-semibold text-foreground">No drafts on this file</h2>
              <p className="text-sm text-muted-foreground">
                Request documents from a finding, or write a message.
              </p>
            </div>
          ) : (
            // LP-859 §4 — THE THIRD STATE, which was borrowing the second one's words.
            //
            // Reported from `04-empty-state-over-a-full-rail.png`: a rail listing two BORROWER
            // drafts, an EMPLOYER draft, a LENDER draft and a sent message, beside a pane claiming
            // the file had none. The screen contradicted itself, and the half that was wrong had
            // the larger type.
            //
            // THE STRING IS NOT QUOTED IN THIS COMMENT, deliberately. §4's acceptance command
            // counts it in this file and expects exactly the two branches that render it; a comment
            // repeating it makes the count unreadable. Three tickets running have had an acceptance
            // command defeated by the fix's own prose — this is the half of that which is mine.
            //
            // One empty state was doing two jobs. Closing the pane sets `closed`, `autoSelected`
            // goes null for the rest of the mount — CORRECT and deliberate, the pane must stay
            // dismissed — and what got rendered in its place was a sentence about a file with no
            // drafts. Nothing distinguished "this file has none" from "you closed the one you were
            // reading".
            //
            // THE BEHAVIOUR IS UNCHANGED. It would be easy to "fix" this by re-selecting a draft on
            // close, which trades a false sentence for a pane that cannot be dismissed. The fix is
            // the words.
            <div className="flex flex-col items-center justify-center gap-3 py-16 text-center">
              <h2 className="text-base font-semibold text-foreground">No draft selected</h2>
              <p className="text-sm text-muted-foreground">
                Pick one from the list, or start a new message.
              </p>
            </div>
          )}
        </div>
      </div>
      {/* LP-857 — FLAGGED OUT, NOT DELETED. LP-815 and LP-807 are written, reviewed and tested, and
          they return in the phase that brings sending and receiving back. Their tests still run — a
          flag that rots is a deletion with extra steps. */}
      {receiving ? (
        <>
          <UploadLinkPanel fileId={id} />
          <InboundMessagesPanel fileId={id} />
        </>
      ) : null}
    </div>
  );
}
