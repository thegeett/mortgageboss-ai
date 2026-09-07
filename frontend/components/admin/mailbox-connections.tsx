"use client";

/**
 * Connect a mailbox (LP-808) — the guided flow, which is guidance and not automation.
 *
 * WHY THERE IS NO "CONNECT" BUTTON THAT DOES THE WORK. A mail routing rule can only be created
 * inside the customer's own admin console: on Google it needs `gmail.settings.basic`, a *restricted*
 * scope requiring a CASA assessment; on Microsoft a rule created through Graph is blocked by the
 * default external-forwarding policy, and asking an admin to relax that policy is asking them to
 * disable a standard exfiltration control. So the screen mints the address, renders the exact
 * click-path, and offers to mail it to whoever administers the mail.
 *
 * VERIFICATION HAS NO BUTTON EITHER. It flips when mail arrives. A button would let somebody mark a
 * connection working before the rule existed, and then the staleness banner — which exists because
 * the failure here is silent — would never fire.
 */

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { SkeletonText } from "@/components/ui/skeleton";
import {
  useConnectMailbox,
  useConnectionSteps,
  useEmailSteps,
  useMailboxConnections,
  useRevokeConnection,
} from "@/lib/api/mailbox-connections";
import { getErrorMessage } from "@/lib/errors/api-error";
import { notifyError, notifySuccess } from "@/lib/toast";
import type { MailboxConnection } from "@/lib/types/mailbox-connection";
import { formatDistanceToNow } from "date-fns";
import { Check, Copy } from "lucide-react";
import { useState } from "react";

const CAPTION = "text-[11px] font-semibold uppercase tracking-wide text-muted-foreground";

const PROVIDERS = [
  { value: "google", label: "Google Workspace" },
  { value: "microsoft", label: "Microsoft 365" },
  { value: "other", label: "Something else" },
] as const;

/**
 * What state a connection is in, as one sentence.
 *
 * FOUR OUTCOMES, NOT TWO. "Waiting for the rule" and "no mail for 6 days" are different problems
 * with different next actions, and a single "not working" would send an admin to check a rule that
 * is fine.
 */
export function connectionState(connection: MailboxConnection): string {
  if (connection.status === "revoked") return "Revoked — this address no longer accepts mail";
  if (connection.verification === "not_verified") {
    return "Not set up yet — create the routing rule, then send a test message";
  }
  if (connection.verification === "awaiting_first_message") {
    return "Waiting for the first message to arrive";
  }
  if (connection.is_stale) {
    const since = connection.last_success_at
      ? formatDistanceToNow(new Date(connection.last_success_at), { addSuffix: true })
      : "a while ago";
    return `No mail received since ${since} — check the routing rule still exists`;
  }
  return connection.last_success_at
    ? `Working — last message ${formatDistanceToNow(new Date(connection.last_success_at), { addSuffix: true })}`
    : "Working";
}

function Steps({ connectionId }: { connectionId: string }) {
  const { data, isPending } = useConnectionSteps(connectionId);
  const [adminEmail, setAdminEmail] = useState("");
  const mail = useEmailSteps(connectionId);

  if (isPending || !data) return <SkeletonText lines={4} />;

  return (
    <div className="flex flex-col gap-3 rounded border border-input bg-background p-3">
      <ol className="flex list-decimal flex-col gap-1 pl-5 text-sm text-foreground-2">
        {data.steps.map((step) => (
          <li key={step}>{step}</li>
        ))}
      </ol>
      <div className="flex flex-wrap items-end gap-2 border-t border-border pt-3">
        <div className="flex flex-col gap-1">
          {/* THE PERSON WHO CAN MAKE THE RULE IS USUALLY NOT THE PROCESSOR. §3 says so, and it is
              why this is a field rather than a button that mails the current user. */}
          <label className={CAPTION} htmlFor={`admin-${connectionId}`}>
            Email these steps to your administrator
          </label>
          <Input
            id={`admin-${connectionId}`}
            type="email"
            value={adminEmail}
            onChange={(event) => setAdminEmail(event.target.value)}
            placeholder="it@yourcompany.com"
            className="w-64"
          />
        </div>
        <Button
          disabled={!adminEmail.trim() || mail.isPending}
          onClick={() =>
            mail.mutate(adminEmail.trim(), {
              onSuccess: () => {
                setAdminEmail("");
                notifySuccess({
                  title: "Steps sent",
                  consequence:
                    "This connection will verify itself the moment mail arrives at the address.",
                });
              },
              onError: (error) =>
                notifyError({ title: "Couldn’t send the steps", whatToDo: getErrorMessage(error) }),
            })
          }
        >
          Send steps
        </Button>
      </div>
      <p className="text-xs text-muted-foreground">
        The message contains only these steps and the address. It says nothing about any loan file
        or any borrower.
      </p>
    </div>
  );
}

export function MailboxConnections() {
  const { data: connections, isPending, isError } = useMailboxConnections();
  const connect = useConnectMailbox();
  const revoke = useRevokeConnection();
  const [provider, setProvider] = useState<string>("google");
  const [sourceAddress, setSourceAddress] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);

  async function copy(address: string) {
    await navigator.clipboard.writeText(address);
    setCopied(address);
    window.setTimeout(() => setCopied(null), 2000);
  }

  return (
    <section className="flex flex-col gap-4">
      <header className="flex flex-col gap-1">
        <h2 className="text-base font-semibold text-foreground">Connected mailboxes</h2>
        <p className="text-sm text-muted-foreground">
          Forward one of your own aliases — <code className="font-mono text-xs">docs@…</code> — to
          the address below, and mail sent there appears in your inbox for triage. Forward a
          dedicated alias rather than a whole mailbox: it is selective by construction and revocable
          in one click.
        </p>
      </header>

      {isPending ? (
        <SkeletonText lines={3} />
      ) : isError ? (
        <p className="text-sm text-danger">
          Connections could not be loaded. Refresh to try again.
        </p>
      ) : connections.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No mailbox is connected. Mail sent to a file&apos;s own address still arrives; this is for
          mail your borrowers send to you.
        </p>
      ) : (
        <ul className="flex flex-col gap-2">
          {connections.map((connection) => (
            <li
              key={connection.id}
              className="flex flex-col gap-2 rounded-lg border border-input p-3"
            >
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="flex min-w-0 flex-col gap-1">
                  <div className="flex items-center gap-2">
                    <code className="truncate rounded bg-muted px-2 py-0.5 font-mono text-xs">
                      {connection.address}
                    </code>
                    <Button size="sm" variant="ghost" onClick={() => void copy(connection.address)}>
                      {copied === connection.address ? (
                        <Check className="h-3.5 w-3.5" aria-hidden />
                      ) : (
                        <Copy className="h-3.5 w-3.5" aria-hidden />
                      )}
                    </Button>
                  </div>
                  <span
                    className={
                      connection.is_stale
                        ? "text-xs font-medium text-warning"
                        : "text-xs text-muted-foreground"
                    }
                  >
                    {connectionState(connection)}
                  </span>
                  {connection.source_address ? (
                    <span className="text-xs text-muted-foreground">
                      Forwarded from {connection.source_address}
                    </span>
                  ) : null}
                </div>
                <div className="flex shrink-0 gap-1">
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => setOpen(open === connection.id ? null : connection.id)}
                  >
                    {open === connection.id ? "Hide steps" : "Show steps"}
                  </Button>
                  {connection.status !== "revoked" ? (
                    <Button
                      size="sm"
                      variant="ghost"
                      disabled={revoke.isPending}
                      onClick={() =>
                        revoke.mutate(connection.id, {
                          onSuccess: () =>
                            notifySuccess({
                              title: "Connection revoked",
                              consequence:
                                "Mail sent to that address is refused. Remove the routing rule too.",
                            }),
                          onError: (error) =>
                            notifyError({
                              title: "Couldn’t revoke it",
                              whatToDo: getErrorMessage(error),
                            }),
                        })
                      }
                    >
                      Revoke
                    </Button>
                  ) : null}
                </div>
              </div>
              {open === connection.id ? <Steps connectionId={connection.id} /> : null}
            </li>
          ))}
        </ul>
      )}

      <div className="flex flex-wrap items-end gap-2 border-t border-border pt-4">
        <div className="flex flex-col gap-1">
          <label className={CAPTION} htmlFor="connection-provider">
            Your mail provider
          </label>
          <select
            id="connection-provider"
            className="h-7 rounded border border-input bg-background px-2 text-sm"
            value={provider}
            onChange={(event) => setProvider(event.target.value)}
          >
            {PROVIDERS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
        <div className="flex flex-col gap-1">
          <label className={CAPTION} htmlFor="connection-source">
            Alias to forward (optional)
          </label>
          <Input
            id="connection-source"
            type="email"
            value={sourceAddress}
            onChange={(event) => setSourceAddress(event.target.value)}
            placeholder="docs@yourcompany.com"
            className="w-64"
          />
        </div>
        <Button
          disabled={connect.isPending}
          onClick={() =>
            connect.mutate(
              { provider, source_address: sourceAddress.trim() || null },
              {
                onSuccess: (created) => {
                  setSourceAddress("");
                  setOpen(created.id);
                  notifySuccess({
                    title: "Address created",
                    consequence: "Follow the steps to route your alias to it.",
                  });
                },
                onError: (error) =>
                  notifyError({
                    title: "Couldn’t create the address",
                    whatToDo: getErrorMessage(error),
                  }),
              },
            )
          }
        >
          Create address
        </Button>
      </div>
    </section>
  );
}
