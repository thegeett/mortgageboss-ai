"use client";

/**
 * Requests to somebody who is not the borrower (LP-820).
 *
 * THE UNREACHABLE ROWS ARE THE POINT. LP-800 sorts 166 document types to eight parties and, until
 * this ticket, only the borrower could be written to — so needs belonging to a title company, an
 * employer, a CPA, an agent or an insurer, in the build plan's words, *"sit at PENDING forever,
 * never get `requested_at`, and are invisible to LP-814."*
 *
 * A panel that showed only what it could send would render a file with five outstanding title
 * documents as having nothing to do. So a party with no address gets a row saying so and a field to
 * fix it, rather than being dropped.
 *
 * AND "BUILD REQUEST" DOES NOT SEND. It prepares the accumulating draft, which goes out through the
 * same path as the borrower's — same rate limit, same suppression check, and the same call that
 * starts the reminder clock. The button says "Build request" for that reason: a "Send" here would
 * be the one outbound message in the product that skipped the send gate.
 */

import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import { useAddPartyAddress, useBuildPartyDraft, usePartyRequests } from "@/lib/api/party-requests";
import { getErrorMessage } from "@/lib/errors/api-error";
import { notifyError, notifySuccess } from "@/lib/toast";
import type { PartyRequest, ResponsibleParty } from "@/lib/types/party-request";
import { useState } from "react";

/** What a processor calls each party. The enum value is an internal identifier. */
const PARTY_LABEL: Record<ResponsibleParty, string> = {
  borrower: "Borrower",
  lender: "Lender",
  title: "Title company",
  employer: "Employer",
  cpa: "Accountant",
  agent: "Estate agent",
  insurer: "Insurer",
};

function PartyRow({ fileId, request }: { fileId: string; request: PartyRequest }) {
  const addAddress = useAddPartyAddress(fileId);
  const build = useBuildPartyDraft(fileId);
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
                onSuccess: (draft) =>
                  notifySuccess({
                    title: "Request prepared",
                    consequence: `${draft.needs_count} document(s) for ${label}. Send it from the document request above.`,
                  }),
                onError: (error) =>
                  notifyError({
                    title: "Couldn’t prepare the request",
                    whatToDo: getErrorMessage(error),
                  }),
              })
            }
          >
            Build request
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
            disabled={!email.trim() || addAddress.isPending}
            onClick={() =>
              addAddress.mutate(
                { role: request.role, email: email.trim() },
                {
                  onSuccess: () => {
                    setEmail("");
                    notifySuccess({
                      title: "Address saved",
                      consequence:
                        "You can now prepare a request. Mail from this address is still reviewed before anything is filed.",
                    });
                  },
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

export function PartyRequestsPanel({ fileId }: { fileId: string }) {
  const { data, isPending, isError } = usePartyRequests(fileId);

  if (isPending) {
    return <p className="text-sm text-muted-foreground">Loading who needs to be asked…</p>;
  }
  if (isError) {
    return (
      <p className="text-sm text-danger">
        Outstanding requests could not be loaded. Refresh to try again.
      </p>
    );
  }

  // The borrower has its own panel above this one; repeating it here would be two places to press
  // send from, and the accumulating request is the one that carries the borrower's guidance.
  const others = data.filter((request) => request.party !== "borrower");

  return (
    <section className="flex flex-col gap-3">
      <header className="flex flex-col gap-1">
        <h2 className="text-base font-semibold text-foreground">Other parties</h2>
        <p className="text-sm text-muted-foreground">
          Documents this file needs from someone other than the borrower. Each party gets its own
          request, and nothing is sent until you send it.
        </p>
      </header>

      {others.length === 0 ? (
        // "structural": nothing outstanding for another party is the CORRECT state on most files,
        // and offering an action would imply a processor should go and find one.
        <EmptyState kind="structural" title="Nothing is needed from anyone else">
          Documents held by a title company, an employer, an accountant or an insurer appear here.
        </EmptyState>
      ) : (
        <ul className="flex flex-col gap-2">
          {others.map((request) => (
            <PartyRow key={request.party} fileId={fileId} request={request} />
          ))}
        </ul>
      )}
    </section>
  );
}
