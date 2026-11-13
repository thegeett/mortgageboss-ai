"use client";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useResendInvite, useRevokeInvite } from "@/lib/api/invites";
import { getErrorMessage } from "@/lib/errors/api-error";
import type { Invite, InviteIssued } from "@/lib/types/invites";
import { ROLE_LABEL } from "@/lib/types/users";
import { cn } from "@/lib/utils";
import { format, formatDistanceToNow } from "date-fns";
import { X } from "lucide-react";
import { useState } from "react";

/**
 * Pending invitations (LP-MB-Admin-04, mockup 08).
 *
 * The copy-link card appears only when a create or resend came back with `accept_url`, which the
 * server sends only when it has no mail transport. It is shown once: dismissing it, or leaving the
 * page, loses the link, and Resend makes a new one.
 */

const DAY = 24 * 60 * 60 * 1000;

/** "Expires in 7 days" / "Expires today" / "Expired Nov 9". */
export function linkState(invite: Invite, now = Date.now()): string {
  const expires = new Date(invite.expires_at);
  if (invite.expired || expires.getTime() <= now) return `Expired ${format(expires, "MMM d")}`;
  const days = Math.ceil((expires.getTime() - now) / DAY);
  return days <= 1 ? "Expires today" : `Expires in ${days} days`;
}

export function CopyLinkCard({
  issued,
  verb,
  onDismiss,
}: {
  issued: InviteIssued;
  verb: "created" | "resent";
  onDismiss: () => void;
}) {
  const [copied, setCopied] = useState(false);
  if (!issued.accept_url) return null;
  const url = issued.accept_url;
  return (
    <Card className="max-w-3xl space-y-3 p-4">
      <p className="text-sm">
        <span className="font-medium">
          Invitation {verb} for {issued.invite.email}.
        </span>{" "}
        No email was sent because this environment has no mail transport. Pass this link on
        yourself; it is shown once.
      </p>
      <div className="flex items-center gap-2">
        <Input readOnly value={url} aria-label="Invitation link" className="font-mono" />
        <Button
          type="button"
          variant="outline"
          onClick={async () => {
            await navigator.clipboard?.writeText(url);
            setCopied(true);
          }}
        >
          {copied ? "Copied" : "Copy link"}
        </Button>
        <Button type="button" variant="ghost" size="icon" aria-label="Dismiss" onClick={onDismiss}>
          <X className="h-4 w-4" />
        </Button>
      </div>
    </Card>
  );
}

export function InvitationsPanel({
  invites,
  onIssued,
}: {
  invites: Invite[];
  onIssued: (issued: InviteIssued, verb: "created" | "resent") => void;
}) {
  const resend = useResendInvite();
  const revoke = useRevokeInvite();
  const [error, setError] = useState<string | null>(null);

  async function run(action: () => Promise<unknown>) {
    setError(null);
    try {
      await action();
    } catch (failure) {
      setError(getErrorMessage(failure));
    }
  }

  return (
    <div className="space-y-3">
      {error ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Email</TableHead>
            <TableHead>Roles</TableHead>
            <TableHead>Invited by</TableHead>
            <TableHead>Link</TableHead>
            <TableHead className="text-right">Actions</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {invites.length === 0 ? (
            <TableRow>
              <TableCell colSpan={5} className="text-sm text-muted-foreground">
                No pending invitations.
              </TableCell>
            </TableRow>
          ) : (
            invites.map((invite) => (
              <TableRow key={invite.id}>
                <TableCell className="font-medium">{invite.email}</TableCell>
                <TableCell>
                  <div className="flex flex-wrap gap-1">
                    {invite.roles.map((role) => (
                      <Badge key={role} variant="outline">
                        {ROLE_LABEL[role]}
                      </Badge>
                    ))}
                  </div>
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {invite.invited_by_name ?? "Someone no longer here"},{" "}
                  {formatDistanceToNow(new Date(invite.created_at), { addSuffix: true })}
                </TableCell>
                <TableCell>
                  <span className="flex items-center gap-1.5">
                    <span
                      aria-hidden
                      className={cn(
                        "h-1.5 w-1.5 rounded-full",
                        invite.expired ? "bg-muted-foreground" : "bg-warning",
                      )}
                    />
                    {linkState(invite)}
                  </span>
                </TableCell>
                <TableCell className="text-right">
                  <div className="flex justify-end gap-2">
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      disabled={resend.isPending}
                      onClick={() =>
                        run(async () => onIssued(await resend.mutateAsync(invite.id), "resent"))
                      }
                    >
                      Resend
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="text-destructive"
                      disabled={revoke.isPending}
                      onClick={() => run(() => revoke.mutateAsync(invite.id))}
                    >
                      Cancel
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>
      <p className="text-xs text-muted-foreground">
        Accepted invitations disappear from this list; the person appears under People. Cancelled
        ones disappear too. Resending makes a new link and stops the old one.
      </p>
    </div>
  );
}
