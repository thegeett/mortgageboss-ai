"use client";

import { DeactivateDialog } from "@/components/admin/deactivate-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { auditTimeLabel, shortDate, signInLabel } from "@/lib/admin-time";
import { useAuditLog } from "@/lib/api/audit-log";
import { reassignLoans } from "@/lib/api/loan-teams";
import { useSetActive, useSetRoles, useUpdatePerson } from "@/lib/api/users";
import { getErrorMessage } from "@/lib/errors/api-error";
import {
  type Person,
  type PersonDetailsUpdate,
  ROLES,
  ROLE_LABEL,
  type Role,
  US_STATE_CODES,
} from "@/lib/types/users";
import { useQueryClient } from "@tanstack/react-query";
import { X } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

/**
 * Edit one person (LP-MB-Admin-03, mockups 04 and 05).
 *
 * The server enforces the rules; this sheet explains them. A control the admin may not use is
 * disabled with the reason as a tooltip (and in text for a screen reader), in the server's own words:
 *
 * - their own row: every role box and Deactivate;
 * - the owner's row: Deactivate and the Admin box.
 *
 * Save sends only the details that changed (PATCH), then the role set if it changed (PUT, the full
 * set). A refusal the server still makes (a 409 or 422) is shown at the top, in its words.
 */

const SELF_ROLES = "You can't change your own roles";
const SELF_DEACTIVATE = "You can't deactivate yourself";
const OWNER = "This is the account owner. Contact MortgageBoss to change their access.";

const ROLE_HINT: Record<Role, string> = {
  admin: "Manages people, lenders, email and settings. Any admin can give or remove this.",
  loan_officer: "Owns loan files and invites borrowers.",
  processor: "Works the company's loan files.",
};

type Details = Required<PersonDetailsUpdate>;

function detailsOf(person: Person): Details {
  return {
    first_name: person.first_name,
    last_name: person.last_name,
    phone: person.phone,
    title: person.title,
    nmls_id: person.nmls_id,
    licensed_states: person.licensed_states,
    sees_all_loans: person.sees_all_loans,
  };
}

/** The fields whose value differs. An emptied text field is sent as null, which clears it. */
function changedDetails(before: Details, after: Details): PersonDetailsUpdate {
  const patch: Record<string, unknown> = {};
  for (const key of Object.keys(after) as (keyof Details)[]) {
    const a = after[key];
    const b = before[key];
    if (JSON.stringify(a) !== JSON.stringify(b)) patch[key] = a;
  }
  return patch as PersonDetailsUpdate;
}

function Blocked({ reason, children }: { reason: string | null; children: React.ReactNode }) {
  if (reason === null) return <>{children}</>;
  return (
    <TooltipProvider delayDuration={200}>
      <Tooltip>
        {/* A span, not the control: a disabled control fires no pointer events to open it. */}
        <TooltipTrigger asChild>
          <span className="inline-flex">
            {children}
            <span className="sr-only">{reason}</span>
          </span>
        </TooltipTrigger>
        <TooltipContent>{reason}</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

export function PersonSheet({
  person,
  currentUserId,
  onClose,
}: {
  person: Person | null;
  currentUserId: string | undefined;
  onClose: () => void;
}) {
  return (
    <Sheet open={person !== null} onOpenChange={(open) => (open ? null : onClose())}>
      <SheetContent className="overflow-y-auto sm:max-w-xl">
        {person ? (
          // Keyed so a different person starts from their own values, not the last one's edits.
          <PersonForm
            key={person.id}
            person={person}
            isSelf={person.id === currentUserId}
            onClose={onClose}
          />
        ) : null}
      </SheetContent>
    </Sheet>
  );
}

function PersonForm({
  person,
  isSelf,
  onClose,
}: {
  person: Person;
  isSelf: boolean;
  onClose: () => void;
}) {
  const [details, setDetails] = useState<Details>(() => detailsOf(person));
  const [roles, setRoles] = useState<Role[]>(person.roles);
  const [stateDraft, setStateDraft] = useState("");
  const [stateError, setStateError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [moving, setMoving] = useState(false);
  const queryClient = useQueryClient();
  const update = useUpdatePerson(person.id);
  const setRoleSet = useSetRoles(person.id);
  const setActive = useSetActive(person.id);
  const history = useAuditLog({ target_type: "user", target_id: person.id }, 5);

  const name = `${person.first_name} ${person.last_name}`;
  const patch = changedDetails(detailsOf(person), details);
  const rolesChanged = [...roles].sort().join() !== [...person.roles].sort().join();
  const dirty = Object.keys(patch).length > 0 || rolesChanged;
  const saving = update.isPending || setRoleSet.isPending;
  const isLoanOfficer = roles.includes("loan_officer");

  function roleBlock(role: Role): string | null {
    if (isSelf) return SELF_ROLES;
    if (person.is_owner && role === "admin") return OWNER;
    return null;
  }
  const deactivateBlock = isSelf ? SELF_DEACTIVATE : person.is_owner ? OWNER : null;

  const text = (key: "first_name" | "last_name" | "phone" | "title" | "nmls_id") => ({
    value: details[key] ?? "",
    onChange: (event: React.ChangeEvent<HTMLInputElement>) => {
      const value = event.target.value;
      // A name is required; the optional fields clear to null rather than "".
      const optional = key !== "first_name" && key !== "last_name";
      setDetails({ ...details, [key]: optional && value.trim() === "" ? null : value });
    },
  });

  function addState() {
    const code = stateDraft.trim().toUpperCase();
    if (code === "") return;
    if (!US_STATE_CODES.has(code)) {
      // Kept in the box with the reason, so it can be corrected; nothing is added.
      setStateError(`${code} is not a US state code.`);
      return;
    }
    if (!details.licensed_states.includes(code)) {
      setDetails({ ...details, licensed_states: [...details.licensed_states, code].sort() });
    }
    setStateDraft("");
    setStateError(null);
  }

  async function save() {
    setError(null);
    try {
      if (Object.keys(patch).length > 0) await update.mutateAsync(patch);
      if (rolesChanged) await setRoleSet.mutateAsync(roles);
      onClose();
    } catch (failure) {
      setError(getErrorMessage(failure));
    }
  }

  async function changeActive(active: boolean, moveTo: string | null = null) {
    setError(null);
    try {
      // Hand the files over FIRST (LP-MB-Admin-05): a refused move leaves the person active, so
      // nobody ends up deactivated with files that were meant to move.
      if (moveTo) {
        setMoving(true);
        await reassignLoans(person.id, moveTo);
        void queryClient.invalidateQueries({ queryKey: ["loan-files"] });
        void queryClient.invalidateQueries({ queryKey: ["assignable"] });
      }
      await setActive.mutateAsync(active);
      setMoving(false);
      setConfirming(false);
    } catch (failure) {
      setMoving(false);
      setConfirming(false);
      setError(getErrorMessage(failure));
    }
  }

  return (
    <div className="flex min-h-full flex-col">
      <div className="border-b border-border p-5 pr-12">
        <SheetTitle>{name}</SheetTitle>
        <SheetDescription>
          {person.email} · joined {shortDate(person.created_at)} · last sign-in{" "}
          {signInLabel(person.last_login_at).toLowerCase()}
          {person.is_active ? "" : " · inactive"}
        </SheetDescription>
      </div>

      <div className="flex-1 space-y-6 p-5">
        {error ? (
          <p
            role="alert"
            className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive"
          >
            {error}
          </p>
        ) : null}

        <section className="space-y-3">
          <h3 className="text-label uppercase text-muted-foreground">Details</h3>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label htmlFor="person-first">First name</Label>
              <Input id="person-first" {...text("first_name")} />
            </div>
            <div className="space-y-1">
              <Label htmlFor="person-last">Last name</Label>
              <Input id="person-last" {...text("last_name")} />
            </div>
            <div className="space-y-1">
              <Label htmlFor="person-title">Title</Label>
              <Input id="person-title" {...text("title")} />
            </div>
            <div className="space-y-1">
              <Label htmlFor="person-phone">Phone</Label>
              <Input id="person-phone" placeholder="Optional" {...text("phone")} />
            </div>
          </div>
          <div className="space-y-1">
            <Label htmlFor="person-email">Email</Label>
            <Input id="person-email" value={person.email} readOnly disabled />
            <p className="text-xs text-muted-foreground">
              The sign-in identity. Cannot be changed here.
            </p>
          </div>
        </section>

        <section className="space-y-3">
          <h3 className="text-label uppercase text-muted-foreground">Roles</h3>
          {ROLES.map((role) => {
            const blocked = roleBlock(role);
            return (
              <div key={role} className="flex items-start gap-3">
                <Blocked reason={blocked}>
                  <input
                    id={`role-${role}`}
                    type="checkbox"
                    className="mt-1 accent-primary"
                    checked={roles.includes(role)}
                    disabled={blocked !== null}
                    onChange={(event) =>
                      setRoles(
                        event.target.checked ? [...roles, role] : roles.filter((r) => r !== role),
                      )
                    }
                  />
                </Blocked>
                <label htmlFor={`role-${role}`}>
                  <span className="block text-sm text-foreground">{ROLE_LABEL[role]}</span>
                  <span className="block text-xs text-muted-foreground">{ROLE_HINT[role]}</span>
                </label>
              </div>
            );
          })}
        </section>

        {isLoanOfficer ? (
          <section className="space-y-3" aria-label="Licensing">
            <h3 className="text-label uppercase text-muted-foreground">
              Licensing{" "}
              <span className="normal-case tracking-normal">
                · shown because Loan officer is ticked
              </span>
            </h3>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label htmlFor="person-nmls">NMLS ID</Label>
                <Input id="person-nmls" {...text("nmls_id")} />
              </div>
              <div className="space-y-1">
                <Label htmlFor="person-states">Licensed states</Label>
                <div className="flex min-h-7 flex-wrap items-center gap-1 rounded-md border border-input px-1.5 py-0.5">
                  {details.licensed_states.map((code) => (
                    <Badge key={code} variant="outline" className="gap-1">
                      {code}
                      <button
                        type="button"
                        aria-label={`Remove ${code}`}
                        onClick={() =>
                          setDetails({
                            ...details,
                            licensed_states: details.licensed_states.filter((c) => c !== code),
                          })
                        }
                      >
                        <X className="h-3 w-3" />
                      </button>
                    </Badge>
                  ))}
                  <input
                    id="person-states"
                    className="min-w-16 flex-1 bg-transparent text-sm outline-none"
                    placeholder="Add state…"
                    value={stateDraft}
                    maxLength={2}
                    aria-invalid={stateError !== null}
                    onChange={(event) => {
                      setStateDraft(event.target.value);
                      setStateError(null);
                    }}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === ",") {
                        event.preventDefault();
                        addState();
                      }
                    }}
                    onBlur={addState}
                  />
                </div>
              </div>
            </div>
            {stateError ? <p className="text-xs text-destructive">{stateError}</p> : null}
            <p className="text-xs text-muted-foreground">
              Goes on pre-approval letters and the borrower&rsquo;s team card when the portal ships.
              Nothing here is validated against NMLS.
            </p>
          </section>
        ) : null}

        <section className="space-y-3">
          <h3 className="text-label uppercase text-muted-foreground">Loan files</h3>
          <label className="flex items-start gap-3">
            <input
              type="checkbox"
              className="mt-1 accent-primary"
              checked={details.sees_all_loans}
              onChange={(event) => setDetails({ ...details, sees_all_loans: event.target.checked })}
            />
            <span>
              <span className="block text-sm text-foreground">Sees all company loan files</span>
              <span className="block text-xs text-muted-foreground">
                {isLoanOfficer
                  ? "A loan officer normally sees only their own files once restriction is on."
                  : "Only matters when “Restrict loan files to their team” is on."}
              </span>
            </span>
          </label>
        </section>

        <section className="space-y-2">
          <h3 className="text-label uppercase text-muted-foreground">History</h3>
          {history.isPending ? (
            <p className="text-sm text-muted-foreground">Loading…</p>
          ) : history.isError ? (
            <p className="text-sm text-muted-foreground">The history is unavailable.</p>
          ) : (history.data?.pages[0]?.items.length ?? 0) === 0 ? (
            <p className="text-sm text-muted-foreground">No changes recorded yet.</p>
          ) : (
            <ul className="divide-y divide-border border-y border-border">
              {history.data?.pages[0]?.items.map((entry) => (
                <li
                  key={entry.id}
                  className="flex items-baseline justify-between gap-3 py-2 text-sm"
                >
                  <span>
                    <span className="text-muted-foreground">{entry.actor?.name ?? "System"}: </span>
                    {entry.summary}
                  </span>
                  <span className="shrink-0 text-xs text-muted-foreground">
                    {auditTimeLabel(entry.created_at)}
                  </span>
                </li>
              ))}
            </ul>
          )}
          <Link href="/admin/audit" className="text-sm text-primary hover:underline">
            Full history in the audit log
          </Link>
        </section>
      </div>

      <div className="flex items-center justify-between gap-3 border-t border-border p-5">
        {person.is_active ? (
          <Blocked reason={deactivateBlock}>
            <Button
              type="button"
              variant="outline"
              className="border-destructive text-destructive"
              disabled={deactivateBlock !== null}
              onClick={() => setConfirming(true)}
            >
              Deactivate
            </Button>
          </Blocked>
        ) : (
          <Button
            type="button"
            variant="outline"
            disabled={setActive.isPending}
            onClick={() => changeActive(true)}
          >
            Reactivate
          </Button>
        )}
        <div className="flex gap-2">
          <Button type="button" variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button type="button" disabled={!dirty || saving} onClick={save}>
            {saving ? "Saving…" : "Save changes"}
          </Button>
        </div>
      </div>

      <DeactivateDialog
        personId={person.id}
        name={name}
        fileCount={person.file_count ?? 0}
        isLoanOfficer={person.roles.includes("loan_officer")}
        open={confirming}
        pending={moving || setActive.isPending}
        onOpenChange={setConfirming}
        onConfirm={(moveTo) => changeActive(false, moveTo)}
      />
    </div>
  );
}
