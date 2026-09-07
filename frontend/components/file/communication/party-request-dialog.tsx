"use client";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { useAddPartyAddress, useBuildPartyDraft, usePartyRequests } from "@/lib/api/party-requests";
import { getErrorMessage } from "@/lib/errors/api-error";
import { notifyError, notifySuccess } from "@/lib/toast";
import type { PartyRequest, ResponsibleParty } from "@/lib/types/party-request";
import { useState } from "react";

/** What a processor calls each party. The enum value is an internal identifier. */
export const PARTY_LABEL: Record<ResponsibleParty, string> = {
  borrower: "Borrower",
  lender: "Lender",
  title: "Title company",
  employer: "Employer",
  cpa: "Accountant",
  agent: "Estate agent",
  insurer: "Insurer",
};

/**
 * Writing to somebody who is not the borrower (LP-835).
 *
 * WHAT THIS CLOSES IS A DEFECT, NOT A GAP. `party_requests` has built drafts for the title company,
 * the agent, the lender, the CPA, the insurer and the employer since LP-820 — and until LP-831 no
 * screen could send one, because `get_open_draft` filters on the BORROWER's template key. The panel
 * this replaces said, on success: *"Send it from the document request above."* The draft above is
 * the borrower's. A processor following that instruction emailed the borrower believing they had
 * contacted the title company.
 *
 * So the sentence is the fix as much as the button is. A party draft now joins the file's drafts
 * list and is sent from the same modal, through the same guards, as any other message.
 *
 * ADDRESS FIRST, DOCUMENTS SECOND, and that order is the measurement LP-820 made rather than a
 * preference: of 166 document types, 13 across title, agent, CPA, insurer and employer had NO
 * address anywhere in the schema. The blocker was never "no way to compose" — it was "nobody to send
 * to", so the modal leads with who.
 *
 * WHAT A PARTY IS OWED IS DERIVED, NEVER TYPED. `open_requests` groups the file's outstanding needs
 * by LP-800's responsible party, so a processor does not have to know that a verification of deposit
 * goes to the bank. A party with nothing outstanding is not offered, because there would be nothing
 * to ask for.
 */
export function PartyRequestDialog({
  fileId,
  open,
  onOpenChange,
}: {
  fileId: string;
  open: boolean;
  onOpenChange: (next: boolean) => void;
}) {
  const { data: requests, isPending } = usePartyRequests(fileId);
  // THE BORROWER IS NOT ANOTHER PARTY. Their requests are the file's own draft, which the mailbox
  // already carries; offering them here would be a second route to the same email. `processor` is
  // not in the enum at all — LP-820 left it out deliberately, because "we order it ourselves" is not
  // a message to anybody.
  const parties = (requests ?? []).filter((request) => request.party !== "borrower");

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle className="text-base">Write to another party</DialogTitle>
          <DialogDescription className="text-xs">
            Title companies, agents, lenders, accountants, insurers and employers. What each is owed
            comes from the file&apos;s outstanding needs.
          </DialogDescription>
        </DialogHeader>

        {isPending ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : parties.length === 0 ? (
          // NOT AN ERROR AND NOT A BLANK BOX. Nothing is outstanding for anybody but the borrower,
          // which is the ordinary state of a file in good order.
          <p className="text-sm text-muted-foreground">
            Nothing on this file is waiting on anybody but the borrower.
          </p>
        ) : (
          <ul className="flex flex-col gap-3">
            {parties.map((request) => (
              <PartyRow
                key={request.party}
                fileId={fileId}
                request={request}
                onDrafted={() => onOpenChange(false)}
              />
            ))}
          </ul>
        )}
      </DialogContent>
    </Dialog>
  );
}

function PartyRow({
  fileId,
  request,
  onDrafted,
}: {
  fileId: string;
  request: PartyRequest;
  onDrafted: () => void;
}) {
  const build = useBuildPartyDraft(fileId);
  const addAddress = useAddPartyAddress(fileId);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const label = PARTY_LABEL[request.party] ?? request.party;

  return (
    <li className="flex flex-col gap-2 rounded-lg border border-input bg-card p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="flex min-w-0 flex-col">
          <span className="text-sm font-medium text-foreground">{label}</span>
          <span className="text-xs text-muted-foreground">
            {request.reachable ? (
              <>
                {request.name ? `${request.name} · ` : null}
                {request.address}
              </>
            ) : (
              // NOT "no address on file" as a shrug. It names what is stuck and what unsticks it.
              <span className="text-warning">
                No address yet — these cannot be requested until there is one
              </span>
            )}
          </span>
        </div>
        {request.reachable ? (
          <Button
            size="sm"
            disabled={build.isPending}
            onClick={() =>
              build.mutate(request.party, {
                onSuccess: (draft) => {
                  notifySuccess({
                    title: "Draft prepared",
                    // LP-835 — THE SENTENCE THAT MAILED THE WRONG PERSON. This said "Send it from
                    // the document request above", and the draft above is the BORROWER's. It now
                    // names where the draft actually is, which since LP-831 is the file's drafts
                    // list — where every draft is reachable and sendable regardless of template.
                    consequence: `${draft.needs_count} document(s) for ${label}. It is in this file's drafts — open it to review and send.`,
                  });
                  onDrafted();
                },
                onError: (error) =>
                  notifyError({
                    title: "Couldn’t prepare the request",
                    whatToDo: getErrorMessage(error),
                  }),
              })
            }
          >
            Create draft
          </Button>
        ) : null}
      </div>

      <ul className="flex flex-wrap gap-1">
        {request.needs.map((need) => (
          <li
            key={need.id}
            className="max-w-full truncate rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground"
          >
            {need.title}
          </li>
        ))}
      </ul>

      {request.reachable ? null : (
        <div className="flex flex-wrap items-end gap-2 border-t border-border pt-2">
          <div className="flex flex-col gap-1">
            <label
              className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground"
              htmlFor={`name-${request.party}`}
            >
              Who they are (optional)
            </label>
            <Input
              id={`name-${request.party}`}
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Acme Title"
              className="w-48"
            />
          </div>
          <div className="flex flex-col gap-1">
            <label
              className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground"
              htmlFor={`addr-${request.party}`}
            >
              {label}&apos;s email
            </label>
            <Input
              id={`addr-${request.party}`}
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="closings@titleco.com"
              className="w-64"
            />
          </div>
          <Button
            size="sm"
            variant="outline"
            disabled={addAddress.isPending || email.trim().length === 0}
            onClick={() =>
              addAddress.mutate(
                { role: request.party, email: email.trim(), name: name.trim() || undefined },
                {
                  onError: (error) =>
                    notifyError({
                      title: "Couldn’t save the address",
                      whatToDo: getErrorMessage(error),
                    }),
                },
              )
            }
          >
            Save address
          </Button>
        </div>
      )}
    </li>
  );
}
