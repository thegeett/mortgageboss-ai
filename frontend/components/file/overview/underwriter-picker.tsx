"use client";

/**
 * Who this file's underwriter is (LP-813).
 *
 * SEPARATE FROM THE LOAN EDITOR, and not because it was easier. The other fields on that row are
 * columns the server writes as given; this one is a cross-ownership pointer with its own refusals —
 * the contact must belong to this company AND be at this file's lender — and its own endpoint. Put
 * in the same save, a refusal would fail the whole edit and the processor would be told their loan
 * amount could not be saved.
 *
 * THE OPTIONS DEPEND ON THE LENDER, which is the other half of that. Before a lender is chosen
 * there is no list to offer, and the control says so rather than showing an empty dropdown — an
 * empty dropdown reads as "this lender has no underwriters", which is a different and wrong fact.
 */

import { Button } from "@/components/ui/button";
import { useLenderContacts, useSetUnderwriter } from "@/lib/api/lenders";
import { getErrorMessage } from "@/lib/errors/api-error";
import { notifyError, notifySuccess } from "@/lib/toast";
import type { LoanFileDetail } from "@/lib/types/loan-file";
import { useState } from "react";

/** The card's own row geometry, so this sits in the list rather than beside it. */
const ROW = "flex items-start justify-between gap-3 border-t border-border py-1.5 text-sm";
const LABEL = "shrink-0 text-muted-foreground";

/**
 * Only the three fields this reads.
 *
 * NARROWER THAN `LoanFileDetail` ON PURPOSE. It states what the component actually depends on, and
 * it keeps the test's fixture honest without a cast — a partial passed as the full type needs an
 * `any`, and an `any` in a fixture is how a component quietly starts reading a fourth field that
 * nothing in the test provides.
 */
export type UnderwriterFile = Pick<LoanFileDetail, "id" | "lender_id" | "underwriter_contact_id">;

export function UnderwriterPicker({ file }: { file: UnderwriterFile }) {
  const contacts = useLenderContacts(file.lender_id);
  const assign = useSetUnderwriter(file.id);
  const [editing, setEditing] = useState(false);

  const assigned =
    (contacts.data ?? []).find((contact) => contact.id === file.underwriter_contact_id) ?? null;

  if (!file.lender_id) {
    return (
      <div className={ROW}>
        <span className={LABEL}>Underwriter</span>
        <span className="max-w-[62%] text-right text-muted-foreground">
          Choose a target lender first — an underwriter works for one of them.
        </span>
      </div>
    );
  }

  function save(contactId: string | null) {
    assign.mutate(contactId, {
      onSuccess: () => {
        setEditing(false);
        notifySuccess({
          title: contactId ? "Underwriter assigned" : "Underwriter cleared",
          consequence: contactId
            ? "Their replies to this file will be recognised rather than sent to triage."
            : "This file no longer names anyone at the lender.",
        });
      },
      onError: (error) =>
        notifyError({
          title: "Couldn’t set the underwriter",
          whatToDo: getErrorMessage(error),
        }),
    });
  }

  if (!editing) {
    return (
      <div className={ROW}>
        <span className={LABEL}>Underwriter</span>
        <div className="flex max-w-[62%] items-center justify-end gap-2">
          <p className="truncate font-medium text-foreground">
            {assigned ? (
              <>
                {assigned.name}
                {assigned.email ? (
                  <span className="text-muted-foreground"> · {assigned.email}</span>
                ) : null}
              </>
            ) : file.underwriter_contact_id ? (
              // The file names someone this lender's active contact list does not contain — they
              // have been removed since. Saying "not assigned" would be false, and saying their
              // name is impossible, so say what is actually known.
              <span className="text-muted-foreground">
                No longer at this lender — choose someone else
              </span>
            ) : (
              <span className="text-muted-foreground">Not assigned</span>
            )}
          </p>
          <Button size="sm" variant="ghost" onClick={() => setEditing(true)}>
            {assigned ? "Change" : "Assign"}
          </Button>
        </div>
      </div>
    );
  }

  const options = (contacts.data ?? []).filter((contact) => contact.is_active);

  return (
    <div className={ROW}>
      <span className={LABEL}>Underwriter</span>
      {contacts.isPending ? (
        <span className="text-muted-foreground">Loading this lender’s contacts…</span>
      ) : options.length === 0 ? (
        <span className="max-w-[62%] text-right text-muted-foreground">
          No contacts are set up for this lender yet. An administrator adds them under
          Administration → Lenders.
        </span>
      ) : (
        <div className="flex items-center gap-2">
          <label className="sr-only" htmlFor="underwriter-select">
            Underwriter
          </label>
          <select
            id="underwriter-select"
            className="h-7 rounded border border-input bg-background px-2 text-sm"
            defaultValue={file.underwriter_contact_id ?? ""}
            disabled={assign.isPending}
            onChange={(event) => save(event.target.value || null)}
          >
            <option value="">Not assigned</option>
            {options.map((contact) => (
              <option key={contact.id} value={contact.id}>
                {contact.name}
                {contact.role !== "underwriter" ? ` (${contact.role.replace("_", " ")})` : ""}
              </option>
            ))}
          </select>
          <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>
            Cancel
          </Button>
        </div>
      )}
    </div>
  );
}
