"use client";

import { ViewFixDialog } from "@/components/file/verification/view-fix-dialog";
import { Button } from "@/components/ui/button";
import type { RuleFinding } from "@/lib/types/verification";
import { cn } from "@/lib/utils";
import { resolutionLabel } from "@/lib/verification/rule-findings";
import { Wrench } from "lucide-react";
import { useState } from "react";

/**
 * LP-561 — the actions on a governed rule finding.
 *
 * Every one of these existed and worked; none was reachable. `rule-finding-row` rendered no buttons
 * at all, so the whole Needs-Attention tab — all 77 rules — was read-only while the legacy
 * cross-source list had the full set.
 *
 * WHICH BUTTONS APPEAR IS DRIVEN BY THE OUTCOME, not by a per-rule list. A rule that concluded
 * something is missing wants a document request; a rule that made an AI judgment wants a signature;
 * a rule that passed wants nothing at all. Offering the same six everywhere would make the common
 * action hard to find, which is the same failure as a wall of identical findings.
 */
export type RuleFindingAction =
  | { kind: "ratify"; findingId: string; note?: string }
  | { kind: "apply"; findingId: string; expectedFingerprint?: string }
  | { kind: "override"; findingId: string; reason: string }
  | { kind: "accept-risk"; findingId: string; reason: string }
  | { kind: "note"; findingId: string; note: string }
  | { kind: "request-docs"; findingId: string; note: string }
  | { kind: "undo"; findingId: string }
  | { kind: "request-docs-bulk"; findingIds: string[]; note?: string };

type FormKind = "override" | "accept-risk" | "note" | "request-docs";

const FORM: Record<
  FormKind,
  { label: string; submit: string; placeholder: string; required: boolean }
> = {
  override: {
    // LP-584 — "Override" named the MECHANISM (overriding the engine); "Not an issue" states the
    // CLAIM, which is what the processor is actually asserting and what a later reader needs. The
    // distinction from Accept risk is who was right: this says the system was WRONG, Accept risk
    // says it was right and the file proceeds anyway. Those tell opposite stories to an auditor,
    // which is why they are two actions and why the reason is mandatory here.
    label: "Why is this not an issue?",
    submit: "Not an issue",
    placeholder: "e.g. vesting confirmed on the existing deed; not required pre-approval",
    // Required, deliberately: this contradicts the engine, and the reason is what a later reader
    // has instead of the finding.
    required: true,
  },
  "accept-risk": {
    label: "What makes this acceptable?",
    submit: "Accept risk",
    placeholder: "e.g. borrower retired; qualifying income is the pension award letter",
    required: true,
  },
  note: {
    label: "Note",
    submit: "Add note",
    placeholder: "e.g. emailed borrower 8/19 — waiting on the DCU statement",
    required: true,
  },
  "request-docs": {
    // LP-839 — SAYS WHO READS IT. This asked "anything to add to the request?", stored the answer
    // in `NeedsItem.description`, and nothing rendered it: the draft's body came from the catalog's
    // guidance or the need's title, so a processor's note reached a column and stopped. It now
    // appears under its own document in the email, which makes the label a promise rather than an
    // invitation into a void.
    label: "Anything to add for the borrower?",
    submit: "Request",
    placeholder: "e.g. the March statement specifically, not February",
    required: false,
  },
};

/** The party names as a processor says them, not as the catalog keys them. */
const PARTY_NOUN: Record<string, string> = {
  borrower: "borrower",
  employer: "employer",
  lender: "lender",
  title: "title company",
  cpa: "accountant",
  agent: "agent",
  insurer: "insurer",
};

export function RuleFindingActions({
  finding,
  onAct,
  pending = false,
  fileId,
}: {
  finding: RuleFinding;
  onAct: (action: RuleFindingAction) => void;
  pending?: boolean;
  // LP-577 — needed for the before/after preview. Optional so a caller that has not threaded it
  // through degrades to the direct Apply rather than losing the button entirely.
  fileId?: string;
}) {
  const [previewOpen, setPreviewOpen] = useState(false);
  const [form, setForm] = useState<FormKind | null>(null);
  const [text, setText] = useState("");

  const resolved = finding.resolution_status !== "open";
  if (resolved) {
    return (
      <div className="mt-2 flex items-center gap-2 text-[11px] text-muted-foreground">
        <span>{resolutionLabel(finding.resolution_status)}</span>
        <button
          type="button"
          className="underline underline-offset-2 hover:text-foreground-2"
          onClick={() => onAct({ kind: "undo", findingId: finding.id })}
          disabled={pending}
        >
          Undo
        </button>
      </div>
    );
  }

  // A pass needs no action. Offering "Note" on 28 satisfied rows would put a control on every line
  // that says the file is fine — noise on exactly the rows a processor should be able to skip.
  if (finding.evaluation_outcome === "satisfied") return null;

  function submit() {
    if (!form) return;
    const value = text.trim();
    if (FORM[form].required && !value) return;
    if (form === "override") onAct({ kind: "override", findingId: finding.id, reason: value });
    else if (form === "accept-risk")
      onAct({ kind: "accept-risk", findingId: finding.id, reason: value });
    else if (form === "note") onAct({ kind: "note", findingId: finding.id, note: value });
    else onAct({ kind: "request-docs", findingId: finding.id, note: value });
    setForm(null);
    setText("");
  }

  const meta = form ? FORM[form] : null;
  // The primary is whatever the outcome actually calls for. A judgment awaiting a signature is
  // Ratify; a missing document is a request; anything else leads with the dismissal path.
  const canRatify = finding.ratification_pending;
  const canRequest = finding.missing_documents.length > 0;
  // LP-839 — LP-801 has written this marker at request time since that ticket, and nothing read it.
  const alreadyRequested = finding.documents_requested === true;
  // LP-841 — `{label: party}`. WHERE THE REQUEST WENT, said on the row rather than only in a toast
  // that has gone. A document that is not the borrower's stays out of THEIR email and goes to the
  // party who holds it, so "in the borrower's draft" and "requested" remain different claims — but
  // the second one no longer means "and nobody was asked".
  const elsewhere = finding.documents_other_party ?? {};
  const inDraft = finding.missing_documents.filter((d) => !(d in elsewhere));
  const byParty = new Map<string, string[]>();
  for (const [label, party] of Object.entries(elsewhere)) {
    byParty.set(party, [...(byParty.get(party) ?? []), label]);
  }

  return (
    <div className="mt-2">
      {/* LP-839 — WHAT THE LAST REQUEST DID, on the row and not only in a toast that has gone.
          Split, because "requested" and "in the draft" are different claims: a document that is not
          the borrower's to send is deliberately kept out of their email. */}
      {alreadyRequested && canRequest ? (
        <p className="mb-1 text-[11px] text-muted-foreground">
          {inDraft.length > 0 ? (
            <>
              <span className="text-foreground">{inDraft.join(", ")}</span> requested — in the
              latest draft.
            </>
          ) : null}
          {inDraft.length > 0 && byParty.size > 0 ? " " : null}
          {/* LP-841 — one clause per party. This read "on the needs list, not the borrower's to
              send": true while those documents were dropped from every draft, and false now that
              they go to the party who holds them. It told a processor their request reached nobody
              in exactly the case where it reached somebody. */}
          {[...byParty.entries()].map(([party, labels]) => (
            <span key={party}>
              <span className="text-foreground">{labels.join(", ")}</span> requested — in a draft
              for the {PARTY_NOUN[party] ?? party}.{" "}
            </span>
          ))}
        </p>
      ) : null}
      {meta === null ? (
        <div className="flex flex-wrap items-center gap-1.5">
          {canRatify && (
            <Button
              variant="default"
              className="px-2 text-xs"
              disabled={pending}
              onClick={() => onAct({ kind: "ratify", findingId: finding.id })}
              // The verb matters: this records agreement with the AI's judgment, where Override
              // records that it was wrong. They were the same button until LP-560.
              title="Record that you reviewed this judgment and agree — nothing on the loan changes"
            >
              {/* LP-581 — "Ratify" is not a word a mortgage processor uses; it came from the engine's
                  calibration model (ADR-336), not from the domain. What the action DOES is record
                  that a person reviewed an AI judgment and agreed — it changes no data at all, and
                  its entire value is that the verdict now carries a name. That is a sign-off.

                  "Agree" was the other candidate and pairs neatly against Override, but the status
                  text has to match the button ("Awaiting sign-off" reads; "Agreement pending" does
                  not), so one word covers both. The wire action stays `ratify` — this is display
                  text, not a contract change. */}
              Sign off
            </Button>
          )}
          {finding.can_apply && (
            <Button
              variant={canRatify ? "outline" : "default"}
              className="px-2 text-xs"
              disabled={pending}
              // LP-577 — Apply WRITES TO THE LOAN and moves an underwriting number: on DT-8 the
              // back-end DTI swings from 58.59% to 34.39%, the difference between a file that fails
              // most conventional overlays and one that passes. It opens the itemized before/after
              // first, so a processor confirms a figure rather than discovers it. Undo exists, but a
              // wrong Apply nobody notices is not something Undo helps with.
              onClick={() =>
                fileId ? setPreviewOpen(true) : onAct({ kind: "apply", findingId: finding.id })
              }
              title={
                fileId
                  ? "See the before/after impact — nothing is written until you confirm"
                  : "Write this correction into the loan — the DTI and LTV recompute"
              }
            >
              {/* LP-580 — THE LABEL MUST MATCH THE CONSEQUENCE. "Apply" reads as "do it now", and
                  this opens a dry-run preview instead — so the most consequential word in the UI was
                  on the button that changes nothing. The legacy finding card already settled this
                  convention ("View fix" opens the impact dialog, "Apply fix" inside it commits); the
                  rule findings simply had not followed it, leaving the same word meaning two
                  different things in the two lists.

                  Conditional, because the FALLBACK path genuinely does apply on click: with no
                  fileId there is no preview to open, and labelling that "View fix" would be the same
                  lie in the opposite direction. */}
              {fileId ? (
                <>
                  <Wrench className="h-3 w-3" /> View fix
                </>
              ) : (
                "Apply"
              )}
            </Button>
          )}
          {canRequest && (
            <Button
              variant={alreadyRequested || canRatify || finding.can_apply ? "outline" : "default"}
              className="px-2 text-xs"
              disabled={pending}
              // LP-839 — the whole effect of this button is on another page, so the tooltip is the
              // cheapest place to say where. Named as the LATEST draft: LP-832 makes a request
              // create a new one carrying everything outstanding, so "the draft" is ambiguous.
              title={
                byParty.size > 0 && inDraft.length === 0
                  ? `Not the borrower's to send — this starts a draft to the ${
                      PARTY_NOUN[[...byParty.keys()][0] ?? ""] ?? "responsible party"
                    }.`
                  : "This will be added to the latest communication draft."
              }
              onClick={() => setForm("request-docs")}
            >
              {alreadyRequested ? "Re-request" : "Request"} {finding.missing_documents.join(", ")}
            </Button>
          )}
          <Button
            variant="ghost"
            className="px-2 text-xs"
            disabled={pending}
            onClick={() => setForm("override")}
            title="The system got this wrong — dismiss it with a reason"
          >
            Not an issue
          </Button>
          <Button
            variant="ghost"
            className="px-2 text-xs"
            disabled={pending}
            onClick={() => setForm("accept-risk")}
          >
            Accept risk
          </Button>
          <Button
            variant="ghost"
            className="px-2 text-xs"
            disabled={pending}
            onClick={() => setForm("note")}
          >
            Note
          </Button>
        </div>
      ) : (
        <div className="space-y-1.5 rounded-md border border-border bg-muted/70 p-2">
          <label
            className="block text-[11px] font-medium text-foreground-2"
            htmlFor={`f-${finding.id}`}
          >
            {meta.label}
          </label>
          <textarea
            id={`f-${finding.id}`}
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={meta.placeholder}
            rows={2}
            className={cn(
              "w-full rounded border border-input px-2 py-1 text-field md:text-xs",
              "focus:border-primary focus:outline-none",
            )}
          />
          <div className="flex items-center gap-1.5">
            <Button
              className="px-2 text-xs"
              onClick={submit}
              disabled={pending || (meta.required && text.trim() === "")}
            >
              {meta.submit}
            </Button>
            <Button
              variant="ghost"
              className="px-2 text-xs"
              onClick={() => {
                setForm(null);
                setText("");
              }}
            >
              Cancel
            </Button>
          </div>
        </div>
      )}
      {/* LP-577 — the itemized before/after (LP-97's dialog, which already computed exactly this
          for the legacy findings and was simply unreachable from here). Confirming inside it runs
          the real Apply. */}
      {fileId && finding.can_apply && (
        <ViewFixDialog
          open={previewOpen}
          onOpenChange={setPreviewOpen}
          fileId={fileId}
          finding={finding}
          onApply={(expectedFingerprint) => {
            setPreviewOpen(false);
            onAct({ kind: "apply", findingId: finding.id, expectedFingerprint });
          }}
          busy={pending}
        />
      )}
    </div>
  );
}
