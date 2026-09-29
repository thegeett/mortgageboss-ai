"use client";

import { MailClientDialog } from "@/components/file/communication/mail-client-dialog";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import {
  useApplyPolish,
  useConditionDraft,
  useDeleteConditionDraft,
  useMarkConditionDraftSent,
  usePolishConditionDraft,
  useSetConditionDraftAddress,
  useSetConditionDraftDueDate,
} from "@/lib/api/conditions";
import { type MailClient, usePreferences, useUpdatePreferences } from "@/lib/api/preferences";
import {
  composeButtonLabel,
  composeUrl,
  effectiveClient,
} from "@/lib/communication/compose-routes";
import { getErrorMessage } from "@/lib/errors/api-error";
import { copyMessage } from "@/lib/markdown/copy-rich";
import type { ConditionDraft, DraftPolish } from "@/lib/types/conditions";
import { Check, Copy, Sparkles, Trash2, TriangleAlert, User } from "lucide-react";
import { useState } from "react";

/** The subtitle every condition draft carries (README rule 4, LP-934 M6). */
export const DRAFT_SUBTITLE =
  "Draft — nothing is sent from the app. Copy it into your mail, send it, then mark it sent.";

/**
 * A round's draft email (S3-04 to S3-06, LP-922) — Phase 4's draft, reused with a side column.
 *
 * NOTHING IS SENT FROM HERE. "Copy & open Gmail" puts the message on the clipboard and opens her own
 * mail with To and Subject filled; "Mark as sent" records that she sent it, which is what moves our
 * status to Waiting on …. The body is built by code from the library's wording and sanitised on the
 * server; it is shown as it will be pasted.
 */
export function ConditionDraftDialog({
  fileId,
  draftId,
  onClose,
}: {
  fileId: string;
  draftId: string | null;
  onClose: () => void;
}) {
  const query = useConditionDraft(fileId, draftId);
  const draft = query.data;
  return (
    <Dialog open={draftId !== null} onOpenChange={(open) => (open ? null : onClose())}>
      {/* NEAR THE TOP, AS S3-04 TO S3-06 DRAW IT: a long email grows downwards instead of recentring. */}
      <DialogContent className="top-10 max-h-[calc(100vh-5rem)] max-w-[61.25rem] translate-y-0 gap-0 overflow-y-auto p-0">
        <div className="border-b border-border px-5 py-3.5 pr-12">
          <DialogTitle className="text-base font-semibold text-foreground">
            {draft?.title ?? "Draft email"}
          </DialogTitle>
          <DialogDescription className="mt-0.5 text-xs text-muted-foreground">
            {DRAFT_SUBTITLE}
          </DialogDescription>
        </div>
        {draft ? (
          <DraftBody fileId={fileId} draft={draft} onClose={onClose} />
        ) : (
          <p className="p-5 text-sm text-muted-foreground">
            {query.isError ? getErrorMessage(query.error) : "Loading the draft…"}
          </p>
        )}
      </DialogContent>
    </Dialog>
  );
}

function DraftBody({
  fileId,
  draft,
  onClose,
}: {
  fileId: string;
  draft: ConditionDraft;
  onClose: () => void;
}) {
  const markSent = useMarkConditionDraftSent(fileId);
  const remove = useDeleteConditionDraft(fileId);
  const preferences = usePreferences();
  const savePreferences = useUpdatePreferences();
  const [chosenClient, setChosenClient] = useState<MailClient | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  // LP-922 follow-up — the AI's proposal, held on screen until she uses it or keeps her own.
  const [proposal, setProposal] = useState<DraftPolish | null>(null);
  const polish = usePolishConditionDraft(fileId);
  const applyPolish = useApplyPolish(fileId);
  const client = chosenClient ?? preferences.data?.mail_client ?? null;
  const sent = draft.status === "sent";

  async function copyAndOpen(chosen?: MailClient) {
    const picked = chosen ?? client;
    if (picked === null && preferences.data !== undefined) {
      setPickerOpen(true);
      return;
    }
    let copied = true;
    try {
      await copyMessage(draft.body_html, "html");
    } catch {
      copied = false;
    }
    const opened = window.open(
      composeUrl(effectiveClient(picked), { to: draft.to, subject: draft.subject }),
      "_blank",
      "noopener,noreferrer",
    );
    setNote(
      !copied
        ? "The copy was blocked — select the message and copy it yourself."
        : opened === null
          ? "Your browser blocked the compose window — the message is on your clipboard, so open your mail and paste it."
          : "Copied. Paste it into the message that opened, send it, then mark it sent here.",
    );
  }

  async function copyOnly() {
    try {
      await copyMessage(draft.body_html, "html");
      setNote("Copied.");
    } catch {
      setNote("The copy was blocked — select the message and copy it yourself.");
    }
  }

  return (
    <div className="grid md:grid-cols-[16.5rem_1fr]">
      <aside className="flex flex-col gap-4 border-b border-border px-5 py-4 md:border-b-0 md:border-r">
        <SideColumn draft={draft} />
      </aside>
      <div className="flex min-w-0 flex-col gap-3 px-5 py-4">
        <Field label="To">
          <span className="block truncate">{draft.to || "—"}</span>
        </Field>
        {draft.needs_address && !sent ? <AddressForm fileId={fileId} draft={draft} /> : null}
        <Field label="Subject">
          <span className="block truncate">{draft.subject}</span>
        </Field>
        {draft.due_date && !sent ? <DueDate fileId={fileId} draft={draft} /> : null}
        {proposal?.polished_html ? (
          <PolishProposal
            proposal={proposal}
            pending={applyPolish.isPending}
            onUse={() =>
              applyPolish.mutate(
                {
                  draftId: draft.id,
                  body_html: proposal.polished_html ?? "",
                  warnings_accepted: proposal.warnings.length,
                },
                {
                  onSuccess: () => {
                    setProposal(null);
                    setNote(null);
                  },
                  onError: (error) => setNote(getErrorMessage(error)),
                },
              )
            }
            onKeep={() => setProposal(null)}
          />
        ) : (
          <>
            {draft.polished_at ? (
              <span className="inline-flex w-fit items-center gap-1 rounded-md border border-ai/30 bg-ai/10 px-1.5 py-0.5 text-xs text-ai">
                <Sparkles className="h-3 w-3" aria-hidden />
                Polished by AI — facts checked by code
              </span>
            ) : null}
            <div
              className={BODY_CLASS}
              // SERVER-BUILT AND SANITISED (LP-922): the words are the library's, filled by code and
              // passed through Phase 4's HTML allow-list before they are stored — and a polished body
              // she chose went through the same allow-list on the way in.
              // biome-ignore lint/security/noDangerouslySetInnerHtml: sanitised server-side, see above
              dangerouslySetInnerHTML={{ __html: draft.body_html }}
            />
          </>
        )}
        {proposal?.polished_html ? null : sent ? (
          <p className="inline-flex items-center gap-1.5 text-sm text-success">
            <Check className="h-4 w-4" aria-hidden />
            Marked sent{draft.sent_at ? ` ${shortDate(draft.sent_at)}` : ""}
          </p>
        ) : (
          <div className="flex flex-wrap items-center gap-2">
            <Button type="button" onClick={() => void copyAndOpen()}>
              <Copy className="h-4 w-4" aria-hidden />
              {composeButtonLabel(client)}
            </Button>
            <Button type="button" variant="outline" onClick={() => void copyOnly()}>
              <Copy className="h-4 w-4" aria-hidden />
              Copy message
            </Button>
            {/* LP-922 FOLLOW-UP — HER CLICK, A PROPOSAL, FACTS CHECKED BY CODE. Violet because it is the
                AI's (README rule 2). */}
            <Button
              type="button"
              variant="outline"
              className="border-ai/40 text-ai hover:bg-ai/10 hover:text-ai"
              disabled={polish.isPending}
              onClick={() =>
                polish.mutate(
                  { draftId: draft.id },
                  {
                    onSuccess: (result) => {
                      if (result.polished_html) {
                        setProposal(result);
                        setNote(null);
                      } else {
                        setNote(result.refusal ?? "The AI could not polish this email just now.");
                      }
                    },
                    onError: (error) => setNote(getErrorMessage(error)),
                  },
                )
              }
            >
              <Sparkles className="h-4 w-4" aria-hidden />
              {polish.isPending ? "Polishing…" : "Polish with AI"}
            </Button>
            <Button
              type="button"
              variant="outline"
              disabled={markSent.isPending || draft.needs_address}
              onClick={() =>
                markSent.mutate(
                  { draftId: draft.id },
                  { onError: (error) => setNote(getErrorMessage(error)) },
                )
              }
            >
              <Check className="h-4 w-4" aria-hidden />
              Mark as sent
            </Button>
            <span className="ml-auto">
              {confirmingDelete ? (
                <span className="inline-flex items-center gap-2 text-sm">
                  Delete this draft?
                  <Button
                    type="button"
                    size="sm"
                    variant="destructive"
                    onClick={() =>
                      remove.mutate(
                        { draftId: draft.id },
                        {
                          onSuccess: onClose,
                          onError: (error) => setNote(getErrorMessage(error)),
                        },
                      )
                    }
                  >
                    Delete
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    onClick={() => setConfirmingDelete(false)}
                  >
                    Keep
                  </Button>
                </span>
              ) : (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="text-destructive hover:text-destructive"
                  onClick={() => setConfirmingDelete(true)}
                >
                  <Trash2 className="h-3.5 w-3.5" aria-hidden />
                  Delete draft
                </Button>
              )}
            </span>
          </div>
        )}
        {note ? <p className="text-xs text-muted-foreground">{note}</p> : null}
      </div>
      <MailClientDialog
        open={pickerOpen}
        suggested={preferences.data?.suggested_mail_client ?? "mailto"}
        reason={preferences.data?.mail_client_suggestion_reason ?? ""}
        pending={savePreferences.isPending}
        onChoose={(picked) => {
          setChosenClient(picked);
          setPickerOpen(false);
          savePreferences.mutate({ mail_client: picked });
          void copyAndOpen(picked);
        }}
      />
    </div>
  );
}

const BODY_CLASS =
  "rounded-lg border border-input bg-card px-4 py-3 text-sm leading-relaxed text-foreground " +
  "[&_a]:text-primary [&_a]:underline [&_em]:not-italic [&_em]:text-muted-foreground " +
  "[&_li]:mb-2 [&_ol]:mb-2 [&_ol]:list-decimal [&_ol]:pl-5 [&_p]:mb-2";

/**
 * The AI's proposal (LP-922 follow-up). NOTHING CHANGES UNTIL SHE USES IT. A fact the AI dropped or added
 * is listed above it — found by code, not by the model — and she decides (product owner, 2026-09-29).
 */
function PolishProposal({
  proposal,
  pending,
  onUse,
  onKeep,
}: {
  proposal: DraftPolish;
  pending: boolean;
  onUse: () => void;
  onKeep: () => void;
}) {
  return (
    <section className="flex flex-col gap-2">
      <span className="inline-flex w-fit items-center gap-1 rounded-md border border-ai/30 bg-ai/10 px-1.5 py-0.5 text-xs text-ai">
        <Sparkles className="h-3 w-3" aria-hidden />
        Proposed by AI — nothing changes until you use it
      </span>
      {proposal.warnings.length > 0 ? (
        <div className="rounded-md border border-warning/50 bg-warning/5 px-3 py-2 text-xs text-foreground-2">
          <p className="inline-flex items-center gap-1 font-medium text-warning">
            <TriangleAlert className="h-3.5 w-3.5" aria-hidden />
            The AI changed {proposal.warnings.length === 1 ? "a fact" : "some facts"} — check before
            you use it:
          </p>
          <ul className="mt-1 list-disc pl-5">
            {proposal.warnings.map((warning) => (
              <li key={`${warning.kind}-${warning.fact}`}>{warning.sentence}</li>
            ))}
          </ul>
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">
          Every amount, date, account ending, link and item is still there — checked by code.
        </p>
      )}
      <div
        className={`${BODY_CLASS} border-ai/30`}
        // SANITISED SERVER-SIDE: the model's reply goes through Phase 4's allow-list before it is
        // returned (`condition_polish.polish_draft`).
        // biome-ignore lint/security/noDangerouslySetInnerHtml: sanitised server-side, see above
        dangerouslySetInnerHTML={{ __html: proposal.polished_html ?? "" }}
      />
      <div className="flex flex-wrap items-center gap-2">
        <Button type="button" disabled={pending} onClick={onUse}>
          <Check className="h-4 w-4" aria-hidden />
          Use this
        </Button>
        <Button type="button" variant="outline" onClick={onKeep}>
          Keep mine
        </Button>
      </div>
    </section>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[4.5rem_1fr] items-center gap-2">
      <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </span>
      <div className="min-w-0 rounded-md border border-input bg-background px-2.5 py-1.5 text-sm text-foreground">
        {children}
      </div>
    </div>
  );
}

function Heading({ children }: { children: React.ReactNode }) {
  return (
    <p className="text-xs font-semibold uppercase tracking-wide text-foreground-2">{children}</p>
  );
}

/** The left column: In this email, Asked once, Privacy, Other drafts, Insurance emails, Why. */
function SideColumn({ draft }: { draft: ConditionDraft }) {
  const borrower = draft.recipient === "borrower";
  return (
    <>
      <section className="flex flex-col gap-1.5">
        <Heading>In this email</Heading>
        <ul className="flex flex-col divide-y divide-border">
          {draft.in_this_email.map((row) => (
            <li key={row.condition_id} className="flex items-start gap-2 py-1.5 text-xs">
              <Check
                className="mt-0.5 h-3.5 w-3.5 shrink-0 rounded-sm bg-primary p-0.5 text-primary-foreground"
                aria-hidden
              />
              <span>
                <span className="font-mono font-medium text-foreground">{row.code ?? "—"}</span>{" "}
                <span className="text-foreground-2">{row.label}</span>
              </span>
            </li>
          ))}
        </ul>
      </section>

      {draft.why_facts.length > 0 ? (
        <section className="flex flex-col gap-1.5">
          <Heading>Why we think so</Heading>
          <ul className="flex flex-col divide-y divide-border">
            {draft.why_facts.map((fact) => (
              <li key={fact.label} className="flex items-start gap-2 py-1.5 text-xs">
                <Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-success" aria-hidden />
                <span className="text-foreground-2">
                  {fact.label} <b className="font-semibold text-foreground">{fact.value}</b>
                </span>
              </li>
            ))}
          </ul>
          <p className="text-xs text-muted-foreground">
            Both dates were read by code from the letter, not by AI. Our status becomes{" "}
            <b className="font-semibold text-foreground">{draft.becomes}</b> when this is marked
            sent.
          </p>
        </section>
      ) : null}

      {draft.asked_once.length > 0 ? (
        <section className="flex flex-col gap-1">
          <Heading>Asked once</Heading>
          {draft.asked_once.map((shared) => (
            <p key={shared.what} className="text-xs text-foreground-2">
              The {shared.what} answer{" "}
              <b className="font-semibold text-foreground">{joinCodes(shared.codes)}</b>. The
              borrower is asked for them once.
            </p>
          ))}
        </section>
      ) : null}

      {borrower ? (
        <section className="flex flex-col gap-1">
          <Heading>Privacy</Heading>
          <p className="text-xs text-foreground-2">
            Account shown as last four only. Documents come back through the upload link, not email.
          </p>
        </section>
      ) : null}

      {/* A THIRD PARTY'S EMAIL ONLY (S3-05): the borrower's and the question's dialogs do not list the
          round's other emails (S3-04, S3-06). */}
      {!borrower && draft.recipient !== "underwriter" && draft.other_drafts.length > 0 ? (
        <section className="flex flex-col gap-1">
          <Heading>Other drafts this round</Heading>
          {draft.other_drafts.map((other) => (
            <p
              key={other.draft_id}
              className="inline-flex items-start gap-1 text-xs text-foreground-2"
            >
              <User className="mt-0.5 h-3 w-3 shrink-0" aria-hidden />
              <span>
                {other.label} · {other.summary}
              </span>
            </p>
          ))}
        </section>
      ) : null}

      {draft.mortgagee_clause ? (
        <section className="flex flex-col gap-1">
          <Heading>Insurance emails</Heading>
          <p className="text-xs text-foreground-2">
            When a round asks the insurance agent, the lender's mortgagee clause from the letter is
            added automatically:
          </p>
          <p className="font-mono text-xs text-foreground-2">{draft.mortgagee_clause}</p>
        </section>
      ) : null}
    </>
  );
}

/** A missing address, asked once: saved on the file, so every later draft to them has it. */
function AddressForm({ fileId, draft }: { fileId: string; draft: ConditionDraft }) {
  const save = useSetConditionDraftAddress(fileId);
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);
  return (
    <form
      className="flex flex-wrap items-center gap-2 rounded-md border border-warning/50 bg-warning/5 px-3 py-2 text-xs"
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate(
          { draftId: draft.id, email: email.trim() },
          { onError: (failure) => setError(getErrorMessage(failure)) },
        );
      }}
    >
      <span className="text-foreground-2">
        No address yet. Add it once — it is remembered for this file.
      </span>
      <input
        aria-label="Email address"
        type="email"
        required
        value={email}
        onChange={(event) => setEmail(event.target.value)}
        className="h-7 flex-1 rounded-md border border-input bg-background px-2 text-sm"
      />
      <Button type="submit" size="sm" disabled={!email.trim() || save.isPending}>
        Save
      </Button>
      {error ? <span className="w-full text-destructive">{error}</span> : null}
    </form>
  );
}

/** The date the email asks for (§8: "editable in the draft"). Saving re-renders the body. */
function DueDate({ fileId, draft }: { fileId: string; draft: ConditionDraft }) {
  const save = useSetConditionDraftDueDate(fileId);
  return (
    <label className="grid grid-cols-[4.5rem_1fr] items-center gap-2">
      <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Due</span>
      <input
        type="date"
        aria-label="Due date"
        defaultValue={draft.due_date ?? undefined}
        disabled={save.isPending}
        onChange={(event) => {
          const value = event.target.value;
          if (value && value !== draft.due_date)
            save.mutate({ draftId: draft.id, due_date: value });
        }}
        className="h-8 w-44 rounded-md border border-input bg-background px-2 text-sm"
      />
    </label>
  );
}

function joinCodes(codes: string[]): string {
  if (codes.length <= 1) return codes.join("");
  return `${codes.slice(0, -1).join(", ")} and ${codes[codes.length - 1]}`;
}

function shortDate(iso: string): string {
  const date = new Date(iso);
  return `${String(date.getMonth() + 1).padStart(2, "0")}/${String(date.getDate()).padStart(2, "0")}`;
}
