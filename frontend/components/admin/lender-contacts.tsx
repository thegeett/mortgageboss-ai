"use client";

/**
 * The people at one lender (LP-813) — the admin surface behind the file's underwriter picker.
 *
 * WHY THIS EXISTS BESIDE THE OVERLAY EDITOR. An overlay is where a lender deviates from the
 * investor default; a contact is who you talk to there. Both are lender configuration an admin
 * sets up once, and splitting them across two screens would mean adding an underwriter took a
 * different route from everything else about that lender.
 *
 * AN EMAIL HERE IS NOT COSMETIC. It is what puts the underwriter on the file's participant list,
 * which is what lets their reply be recognised rather than sent to triage — so the form says so
 * rather than presenting it as an optional detail.
 */

import { Button } from "@/components/ui/button";
import { InlineErrorState } from "@/components/ui/error-state";
import { Input } from "@/components/ui/input";
import { SkeletonText } from "@/components/ui/skeleton";
import {
  useCreateLenderContact,
  useDeleteLenderContact,
  useLenderContacts,
} from "@/lib/api/lenders";
import { getErrorMessage } from "@/lib/errors/api-error";
import { notifyError, notifySuccess } from "@/lib/toast";
import type { LenderContactRole } from "@/lib/types/lender";
import { Trash2 } from "lucide-react";
import { useState } from "react";

const ROLE_LABEL: Record<LenderContactRole, string> = {
  underwriter: "Underwriter",
  account_executive: "Account executive",
  closer: "Closer",
  other: "Other",
};

const CAPTION = "text-[11px] font-semibold uppercase tracking-wide text-muted-foreground";

export function LenderContacts({ lenderId }: { lenderId: string }) {
  const { data: contacts, isPending, isError, refetch } = useLenderContacts(lenderId);
  const create = useCreateLenderContact(lenderId);
  const remove = useDeleteLenderContact(lenderId);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<LenderContactRole>("underwriter");

  function add() {
    create.mutate(
      { name: name.trim(), email: email.trim() || null, role },
      {
        onSuccess: () => {
          setName("");
          setEmail("");
          notifySuccess({
            title: "Contact added",
            consequence: "They can now be assigned as the underwriter on a file at this lender.",
          });
        },
        onError: (error) =>
          notifyError({ title: "Couldn’t add the contact", whatToDo: getErrorMessage(error) }),
      },
    );
  }

  return (
    <section className="flex flex-col gap-3">
      <header className="flex flex-col gap-1">
        <h2 className="text-base font-semibold text-foreground">Contacts</h2>
        <p className="text-sm text-muted-foreground">
          The people your processors work with here. Recording an email address is what lets their
          replies be matched to the loan file instead of landing in triage.
        </p>
      </header>

      {isPending ? (
        <SkeletonText lines={3} />
      ) : isError ? (
        <InlineErrorState message="Couldn't load this lender's contacts." onRetry={refetch} />
      ) : contacts.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No contacts yet. Until one is added, a file at this lender cannot name an underwriter.
        </p>
      ) : (
        <ul className="flex flex-col">
          {contacts.map((contact) => (
            <li
              key={contact.id}
              className="flex items-center justify-between gap-3 border-t border-border py-2 text-sm first:border-t-0"
            >
              <div className="flex min-w-0 flex-col">
                <span className="truncate font-medium text-foreground">{contact.name}</span>
                <span className="truncate text-xs text-muted-foreground">
                  {ROLE_LABEL[contact.role]}
                  {contact.email ? ` · ${contact.email}` : " · no email recorded"}
                </span>
              </div>
              <Button
                size="sm"
                variant="ghost"
                disabled={remove.isPending}
                onClick={() =>
                  remove.mutate(contact.id, {
                    onSuccess: () =>
                      notifySuccess({
                        title: "Contact removed",
                        // Says what a removal does NOT do. A file that named them keeps the record
                        // of who its underwriter was; it simply stops offering them.
                        consequence:
                          "Files that named them keep that record; new files will not offer them.",
                      }),
                    onError: (error) =>
                      notifyError({
                        title: "Couldn’t remove the contact",
                        whatToDo: getErrorMessage(error),
                      }),
                  })
                }
                aria-label={`Remove ${contact.name}`}
              >
                <Trash2 className="h-3.5 w-3.5" aria-hidden />
              </Button>
            </li>
          ))}
        </ul>
      )}

      <div className="flex flex-wrap items-end gap-2 border-t border-border pt-3">
        <div className="flex flex-col gap-1">
          <label className={CAPTION} htmlFor="contact-name">
            Name
          </label>
          <Input
            id="contact-name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Dana Reed"
            className="w-44"
          />
        </div>
        <div className="flex flex-col gap-1">
          <label className={CAPTION} htmlFor="contact-email">
            Email
          </label>
          <Input
            id="contact-email"
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            placeholder="dana.reed@lender.com"
            className="w-64"
          />
        </div>
        <div className="flex flex-col gap-1">
          <label className={CAPTION} htmlFor="contact-role">
            Role
          </label>
          <select
            id="contact-role"
            className="h-7 rounded border border-input bg-background px-2 text-sm"
            value={role}
            onChange={(event) => setRole(event.target.value as LenderContactRole)}
          >
            {(Object.keys(ROLE_LABEL) as LenderContactRole[]).map((value) => (
              <option key={value} value={value}>
                {ROLE_LABEL[value]}
              </option>
            ))}
          </select>
        </div>
        <Button onClick={add} disabled={!name.trim() || create.isPending}>
          Add contact
        </Button>
      </div>
    </section>
  );
}
