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
  const autoSelected = narrow || closed ? null : (openDrafts[0]?.id ?? null);
  const selected = chosen ?? autoSelected;

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
              onClose={() => {
                setChosen(null);
                // CLOSING MEANS CLOSED, and the auto-selection must not immediately undo it. Rule 2
                // picks the newest open draft on LOAD; without this the ✕ would re-open the same
                // draft on the next render and the pane could never be dismissed.
                setClosed(true);
              }}
            />
          ) : (
            // §2.1 rule 4's second half: sent history with nothing open carries the same empty
            // state INSIDE the right pane.
            <div className="flex flex-col items-center justify-center gap-3 py-16 text-center">
              <h2 className="text-base font-semibold text-foreground">No drafts on this file</h2>
              <p className="text-sm text-muted-foreground">
                Request documents from a finding, or write a message.
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
