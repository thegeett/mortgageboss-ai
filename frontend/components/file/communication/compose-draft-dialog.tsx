"use client";

/**
 * Compose — a draft about nothing (LP-856). Screen 8.
 *
 * A MESSAGE WITH NO NEEDS BEHIND IT. A processor telling a borrower "your file went to underwriting"
 * is answering nothing and requesting nothing, and until LP-818 had no way to record that it
 * happened. This is the way in to that draft.
 *
 * NOT A SECOND KIND OF OBJECT. What this creates is an ordinary `Communication` with `template_key`
 * null: same list row, same modal, same buttons, an empty "What it asks for" block. A free draft
 * that needed its own list, its own modal or its own send path would double every future change to
 * drafts — so this dialog collects three fields and hands them to the same place everything else
 * goes.
 *
 * THE RECIPIENT IS TYPED, NOT DERIVED. There is no party to look up an address for. It defaults to
 * the borrower because that is who almost every message is to, and **nothing is written back to the
 * file's party addresses from here** — an address typed for one message is not a fact about the
 * file, and `party_requests` is where facts about the file live.
 */

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { useLoanFileBorrowers } from "@/lib/api/loan-files";
import { useComposeDraft } from "@/lib/api/messages";
import { getErrorMessage } from "@/lib/errors/api-error";
import { notifyError, notifySuccess } from "@/lib/toast";
import { useState } from "react";

export function ComposeDraftDialog({
  fileId,
  open,
  onOpenChange,
  suggestedRecipient = "",
}: {
  fileId: string;
  open: boolean;
  onOpenChange: (next: boolean) => void;
  /** The borrower's address, where the file has one. Editable — it is a default, not a rule. */
  suggestedRecipient?: string;
}) {
  const compose = useComposeDraft(fileId);
  const [recipient, setRecipient] = useState(suggestedRecipient);
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");

  // THE SUBJECT IS REQUIRED AND NOT DEFAULTED. `create_compose_draft` refuses an empty one, and the
  // reason is in its own docstring: a subject a system invented is one a borrower cannot recognise.
  // The request path never has this problem because its template supplies one.
  const ready = recipient.trim() !== "" && subject.trim() !== "" && body.trim() !== "";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="text-base">Write a message</DialogTitle>
          <DialogDescription className="text-xs">
            A draft with no documents attached. It joins this file&apos;s drafts, where you can edit
            it and send it like any other.
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-3">
          {/* `htmlFor`/`id` RATHER THAN WRAPPING. `Input` is a forwarded ref, so the implicit
              association a wrapping label would give is invisible to the linter and, more to the
              point, to anything reading the rendered tree — the explicit pair is what a screen
              reader follows. */}
          <label htmlFor="compose-to" className="flex flex-col gap-1 text-sm">
            <span className="font-medium text-foreground">To</span>
            <Input
              id="compose-to"
              type="email"
              value={recipient}
              onChange={(event) => setRecipient(event.target.value)}
              placeholder="borrower@example.com"
            />
          </label>
          <label htmlFor="compose-subject" className="flex flex-col gap-1 text-sm">
            <span className="font-medium text-foreground">Subject</span>
            <Input
              id="compose-subject"
              type="text"
              value={subject}
              onChange={(event) => setSubject(event.target.value)}
              placeholder="An update on your file"
            />
          </label>
          <label htmlFor="compose-body" className="flex flex-col gap-1 text-sm">
            <span className="font-medium text-foreground">Message</span>
            {/* A PLAIN BOX HERE, AND THE RICH EDITOR IN THE MODAL. The draft opens in the same
                dialog as every other one the moment it is created, and that is where LP-854's
                toolbar and ✦ polish live. Loading ProseMirror twice — once to create and once to
                edit — would pay LP-854's 55 kB on a screen that is three fields. */}
            <textarea
              id="compose-body"
              className="min-h-32 rounded-md border border-input bg-background px-3 py-2 text-sm"
              value={body}
              onChange={(event) => setBody(event.target.value)}
              placeholder="Write the message…"
              aria-label="Message"
            />
          </label>
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-border pt-3">
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            type="button"
            disabled={!ready || compose.isPending}
            onClick={() =>
              compose.mutate(
                { recipient: recipient.trim(), subject: subject.trim(), body },
                {
                  onSuccess: () => {
                    notifySuccess({
                      // LP-852's rule — a toast names who it is to. There is no party here, so it
                      // names the address the processor typed, which is the only "who" there is.
                      title: `Draft to ${recipient.trim()}`,
                      consequence:
                        "No documents attached. It is in this file's drafts — open it to edit and send.",
                    });
                    setSubject("");
                    setBody("");
                    onOpenChange(false);
                  },
                  onError: (error) =>
                    notifyError({
                      title: "Couldn’t start the draft",
                      whatToDo: getErrorMessage(error),
                    }),
                },
              )
            }
          >
            {compose.isPending ? "Starting…" : "Start the draft"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

/**
 * The button. Screen 1 puts it beside "Request documents", as the outline to its primary.
 *
 * Mounted only while open, like the catalog dialog: the needs query behind the borrower's address
 * should not run on every visit to the Communication page.
 */
export function ComposeDraftButton({ fileId }: { fileId: string }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button
        type="button"
        size="sm"
        variant="outline"
        className="gap-2"
        onClick={() => setOpen(true)}
      >
        Compose
      </Button>
      {open ? (
        <ComposeDraftDialogWithBorrower fileId={fileId} open={open} onOpenChange={setOpen} />
      ) : null}
    </>
  );
}

/**
 * Seeds To from the file's primary borrower, which is who almost every message is to.
 *
 * FROM THE BORROWERS ENDPOINT, not from the loan file. The loan-file payload's `BorrowerPublic` is
 * the "safe borrower view" its own docstring describes and carries no email; `/borrowers` returns
 * `BorrowerDetail`, which does. A co-borrower, a corrected address and a borrower who asked to be
 * written to elsewhere are all ordinary, which is why the field stays editable: a default, not a
 * rule.
 *
 * AN EMPTY STRING IS A FINE ANSWER. `borrowers.email` is nullable, so a file can have a borrower and
 * no address; the box is then empty and the processor types one, rather than being shown a claim.
 */
function ComposeDraftDialogWithBorrower({
  fileId,
  open,
  onOpenChange,
}: {
  fileId: string;
  open: boolean;
  onOpenChange: (next: boolean) => void;
}) {
  // `useLoanFileBorrowers`, NOT the loan-file detail. That payload's `BorrowerPublic` deliberately
  // carries no email — its docstring calls it the safe borrower view — and widening it would put a
  // borrower's address into a response every file screen loads, to supply a default value. The
  // borrowers endpoint already serves it, and it is fetched only while this dialog is mounted.
  const borrowers = useLoanFileBorrowers(fileId).data ?? [];
  const primary = borrowers.find((borrower) => borrower.is_primary) ?? borrowers[0];
  return (
    <ComposeDraftDialog
      fileId={fileId}
      open={open}
      onOpenChange={onOpenChange}
      suggestedRecipient={primary?.email ?? ""}
    />
  );
}
