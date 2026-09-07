"use client";

/**
 * The secure upload link a processor sends instead of asking for an attachment (LP-815).
 *
 * THE URL IS SHOWN ONCE AND CANNOT BE RECOVERED. The server stores a SHA-256 of the token, so if
 * this panel loses the response the link is unreachable and a new one must be minted. That is the
 * property, not a bug: what the database holds must not be usable to reach a loan file.
 *
 * So the newly-minted URL is held in component state and the copy button is the primary action —
 * and the panel says plainly that it will not be shown again, rather than letting a processor
 * navigate away and discover it.
 */

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useMintUploadLink, useRevokeUploadLink, useUploadLinks } from "@/lib/api/upload-links";
import { getErrorMessage } from "@/lib/errors/api-error";
import { notifyError, notifySuccess } from "@/lib/toast";
import type { MintedUploadLink, UploadLinkSummary } from "@/lib/types/upload-link";
import { formatDistanceToNow } from "date-fns";
import { Check, Copy } from "lucide-react";
import { useState } from "react";

const CAPTION = "text-[11px] font-semibold uppercase tracking-wide text-muted-foreground";

/** What a link's state is, in a processor's words. */
function describe(link: UploadLinkSummary): string {
  if (link.revoked_at) return "Revoked";
  if (link.uses >= link.max_uses) return "Used up";
  const expiry = new Date(link.expires_at);
  if (expiry.getTime() <= Date.now()) return "Expired";
  return `Expires ${formatDistanceToNow(expiry, { addSuffix: true })}`;
}

export function UploadLinkPanel({ fileId }: { fileId: string }) {
  const { data: links, isPending, isError } = useUploadLinks(fileId);
  const mint = useMintUploadLink(fileId);
  const revoke = useRevokeUploadLink(fileId);
  const [recipient, setRecipient] = useState("");
  const [fresh, setFresh] = useState<MintedUploadLink | null>(null);
  const [copied, setCopied] = useState(false);

  function create() {
    mint.mutate(
      { recipient_email: recipient.trim() || null },
      {
        onSuccess: (link) => {
          setFresh(link);
          setRecipient("");
          notifySuccess({
            title: "Link created",
            consequence: "Copy it now — it cannot be shown again after you leave this page.",
          });
        },
        onError: (error) =>
          notifyError({ title: "Couldn’t create the link", whatToDo: getErrorMessage(error) }),
      },
    );
  }

  async function copy(url: string) {
    await navigator.clipboard.writeText(url);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 2000);
  }

  return (
    <section className="flex flex-col gap-3">
      <header className="flex flex-col gap-1">
        <h2 className="text-base font-semibold text-foreground">Secure upload link</h2>
        <p className="text-sm text-muted-foreground">
          Send this instead of asking for documents by email. Email is not an appropriate channel
          for account numbers or a Social Security number, and a link keeps them off it.
        </p>
      </header>

      {fresh ? (
        <div className="flex flex-col gap-2 rounded-lg border border-primary/40 bg-primary/5 p-3">
          <span className={CAPTION}>Copy this now</span>
          <div className="flex items-center gap-2">
            <code className="min-w-0 flex-1 truncate rounded bg-background px-2 py-1 font-mono text-xs">
              {fresh.url}
            </code>
            <Button size="sm" onClick={() => void copy(fresh.url)}>
              {copied ? (
                <Check className="h-3.5 w-3.5" aria-hidden />
              ) : (
                <Copy className="h-3.5 w-3.5" aria-hidden />
              )}
              <span className="ml-1">{copied ? "Copied" : "Copy"}</span>
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">
            This is the only time the link is shown. It is stored one-way, so it cannot be looked up
            later — create another if you lose it.
          </p>
        </div>
      ) : null}

      <div className="flex flex-wrap items-end gap-2">
        <div className="flex flex-col gap-1">
          <label className={CAPTION} htmlFor="link-recipient">
            Who is it for (optional)
          </label>
          <Input
            id="link-recipient"
            type="email"
            value={recipient}
            onChange={(event) => setRecipient(event.target.value)}
            placeholder="borrower@example.com"
            className="w-64"
          />
        </div>
        <Button onClick={create} disabled={mint.isPending}>
          Create link
        </Button>
      </div>

      {/* LP-827 — WHAT THE LINK PERMITS, said before one is made. The numbers lived only in the
          backend's constants, so the question "does it just work one time?" had no answer on any
          screen — and the borrower is told nothing either. Opening it costs nothing: a use is spent
          when a document arrives, which is what bounds it. */}
      <p className={CAPTION}>
        A new link works for 3 days and accepts up to 20 documents. Opening it costs nothing — a use
        is spent only when a document is uploaded.
      </p>

      {isPending ? (
        <p className="text-sm text-muted-foreground">Loading links…</p>
      ) : isError ? (
        <p className="text-sm text-danger">Links could not be loaded. Refresh to try again.</p>
      ) : links.length === 0 ? (
        <p className="text-sm text-muted-foreground">No links have been created for this file.</p>
      ) : (
        <ul className="flex flex-col">
          {links.map((link) => (
            <li
              key={link.id}
              className="flex items-center justify-between gap-3 border-t border-border py-2 text-sm first:border-t-0"
            >
              <div className="flex min-w-0 flex-col">
                <span className="truncate text-foreground">
                  {link.recipient_email ?? "Not addressed to anyone in particular"}
                </span>
                <span className="text-xs text-muted-foreground">
                  {describe(link)} · {link.uses} of {link.max_uses} used
                </span>
              </div>
              {link.is_usable ? (
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={revoke.isPending}
                  onClick={() =>
                    revoke.mutate(link.id, {
                      onSuccess: () =>
                        notifySuccess({
                          title: "Link revoked",
                          consequence: "Anyone still holding it now sees an expired page.",
                        }),
                      onError: (error) =>
                        notifyError({
                          title: "Couldn’t revoke the link",
                          whatToDo: getErrorMessage(error),
                        }),
                    })
                  }
                >
                  Revoke
                </Button>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
