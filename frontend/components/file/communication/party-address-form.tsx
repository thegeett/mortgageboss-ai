"use client";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useAddPartyAddress } from "@/lib/api/party-requests";
import { getErrorMessage } from "@/lib/errors/api-error";
import { notifyError } from "@/lib/toast";
import type { ResponsibleParty } from "@/lib/types/party-request";
import { useState } from "react";

/**
 * What a processor calls each party. The enum value is an internal identifier.
 *
 * LIFTED OUT OF `party-request-dialog` (LP-857), which is where it lived until that dialog went.
 * The timeline keeps its own abbreviated map — "Title co.", "Agent" — because a fixed-width column
 * has a different constraint from a sentence, and that predates this ticket.
 */
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
 * Where to write to a party, asked at the moment it blocks somebody (LP-857).
 *
 * THIS IS THE IMPROVEMENT HIDDEN INSIDE REMOVING A BUTTON. The form is not new — it sat inside
 * "Write to another party", a standalone dialog on the Communication page, which is a panel a
 * processor visits only if they already know they need it. LP-820 measured the problem it answers:
 * of 166 document types, 13 across title, agent, CPA, insurer and employer had **no address
 * anywhere in the schema**, and the blocker was never "no way to compose" — it was "nobody to send
 * to".
 *
 * So the draft is still created with no address (LP-841: *"the message is the part a processor
 * wants"*), it says so on the list, and the question is asked HERE — in front of the person who
 * knows the answer, at the moment it is stopping them.
 *
 * SAVED TO THE FILE, NOT TO THIS MESSAGE. `add_party_address` writes a participant, which is what
 * makes the sentence under the button true: every future message to this party uses it. Typing an
 * address into "Send to" would send this one email and lose it — which is the right behaviour for
 * LP-856's free draft, where the address is a one-off, and the wrong one here.
 */
export function PartyAddressForm({
  fileId,
  party,
  onSaved,
}: {
  fileId: string;
  party: ResponsibleParty;
  /** The saved address, so the draft becomes sendable without being reopened. */
  onSaved: (email: string) => void;
}) {
  const addAddress = useAddPartyAddress(fileId);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const label = PARTY_LABEL[party] ?? party;

  return (
    <div className="flex flex-col gap-2 border border-warning/40 bg-warning/5 p-3">
      <div className="flex flex-col gap-0.5">
        {/* COLOUR AND GLYPH AND WORD — the Ledger's rule. The word is what survives a processor who
            does not read colour, and "No address on file" names the state rather than the feeling.
            The question under it is the one they can answer. */}
        <span className="text-sm font-medium text-warning">
          No address on file for the {label.toLowerCase()}
        </span>
        <span className="text-xs text-muted-foreground">Who are they, and where do we write?</span>
      </div>
      <div className="flex flex-wrap items-end gap-2">
        <div className="flex flex-col gap-1">
          <label
            className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground"
            htmlFor={`party-name-${party}`}
          >
            Who they are (optional)
          </label>
          <Input
            id={`party-name-${party}`}
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Acme Title"
            className="w-48"
          />
        </div>
        <div className="flex flex-col gap-1">
          <label
            className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground"
            htmlFor={`party-email-${party}`}
          >
            {label}&apos;s email
          </label>
          <Input
            id={`party-email-${party}`}
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            placeholder="closings@titleco.com"
            className="w-64"
          />
        </div>
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={addAddress.isPending || email.trim().length === 0}
          onClick={() =>
            addAddress.mutate(
              { role: party, email: email.trim(), name: name.trim() || undefined },
              {
                // THE DRAFT BECOMES SENDABLE WITHOUT BEING REOPENED — acceptance 3. The server has
                // the address either way (`suggested_recipient` resolves it on the next read), and
                // this is what stops the processor having to close the modal to see the effect of
                // the thing they just did inside it.
                onSuccess: () => onSaved(email.trim()),
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
      <span className="text-xs text-muted-foreground">
        Saved to the file — used for every future message to this party.
      </span>
    </div>
  );
}
