"use client";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useCreateInvite } from "@/lib/api/invites";
import { getErrorMessage } from "@/lib/errors/api-error";
import type { InviteIssued } from "@/lib/types/invites";
import { ROLES, ROLE_LABEL, type Role } from "@/lib/types/users";
import { useState } from "react";

/**
 * Invite a person (LP-MB-Admin-04, mockup 07).
 *
 * Email and roles, Processor ticked to start. The server's refusal (already on the team, deactivated,
 * an address that can't be invited, the 50 limit) is shown under the email field in its own words.
 * The mockup's "Owner is not on this list" note is left out: the owner is set at onboarding.
 */
const ROLE_HINT: Record<Role, string> = {
  admin: "Manages people, lenders, email and settings. Any admin can invite another admin.",
  loan_officer: "Owns loan files and invites borrowers.",
  processor: "Works the company's loan files.",
};

export function InviteDialog({
  open,
  onOpenChange,
  onIssued,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onIssued: (issued: InviteIssued) => void;
}) {
  const [email, setEmail] = useState("");
  const [roles, setRoles] = useState<Role[]>(["processor"]);
  const [error, setError] = useState<string | null>(null);
  const create = useCreateInvite();

  function reset() {
    setEmail("");
    setRoles(["processor"]);
    setError(null);
  }

  async function send() {
    setError(null);
    try {
      const issued = await create.mutateAsync({ email: email.trim(), roles });
      onIssued(issued);
      reset();
      onOpenChange(false);
    } catch (failure) {
      setError(getErrorMessage(failure));
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) reset();
        onOpenChange(next);
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Invite a person</DialogTitle>
          <DialogDescription>
            They get an email with a link, choose their own password, and join your company. The
            link works once and expires in 7 days.
          </DialogDescription>
        </DialogHeader>
        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            void send();
          }}
        >
          <div className="space-y-1">
            <Label htmlFor="invite-email">Email</Label>
            <Input
              id="invite-email"
              type="email"
              autoComplete="off"
              value={email}
              aria-invalid={error !== null}
              aria-describedby={error ? "invite-email-error" : undefined}
              onChange={(event) => setEmail(event.target.value)}
            />
            {error ? (
              <p id="invite-email-error" role="alert" className="text-xs text-destructive">
                {error}
              </p>
            ) : null}
          </div>
          <fieldset className="space-y-3">
            <legend className="text-label uppercase text-muted-foreground">Roles</legend>
            {ROLES.map((role) => (
              <label key={role} className="flex items-start gap-3">
                <input
                  type="checkbox"
                  className="mt-1 accent-primary"
                  checked={roles.includes(role)}
                  onChange={(event) =>
                    setRoles(
                      event.target.checked ? [...roles, role] : roles.filter((r) => r !== role),
                    )
                  }
                />
                <span>
                  <span className="block text-sm text-foreground">{ROLE_LABEL[role]}</span>
                  <span className="block text-xs text-muted-foreground">{ROLE_HINT[role]}</span>
                </span>
              </label>
            ))}
          </fieldset>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={email.trim() === "" || roles.length === 0 || create.isPending}
            >
              {create.isPending ? "Sending…" : "Send invitation"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
