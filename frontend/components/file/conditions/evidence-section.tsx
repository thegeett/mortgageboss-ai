"use client";

import { Button } from "@/components/ui/button";
import { useAcceptEvidence, useAnswerFinding, useReaskEvidence } from "@/lib/api/conditions";
import { waitingLabel } from "@/lib/conditions/next-step";
import { getErrorMessage } from "@/lib/errors/api-error";
import type {
  Condition,
  ConditionEvidence,
  EvidenceCheckResult,
  EvidenceFinding,
} from "@/lib/types/conditions";
import { cn } from "@/lib/utils";
import {
  CircleCheckBig,
  CircleDashed,
  CircleX,
  Eye,
  FileText,
  Mail,
  TriangleAlert,
} from "lucide-react";
import Link from "next/link";
import { useState } from "react";

/**
 * Evidence that arrived for the condition's items, and what code found (S3-07, S3-08; LP-923).
 *
 * EVERY RESULT IS CODE'S. A check reads "passed", "failed" or "not run" with its reason; a check whose
 * inputs the file does not have is shown as not run, never as passed. Nothing is drafted by itself: the
 * re-ask goes into the failed item's own email (the borrower's, or title's for a receipt), and the
 * explanation request into the borrower email, when she presses the button.
 */
export function EvidenceSection({ fileId, condition }: { fileId: string; condition: Condition }) {
  if (condition.evidence.length === 0) return null;
  return (
    <section className="flex flex-col gap-3">
      {condition.evidence.map((evidence) => (
        <EvidenceCard key={evidence.id} fileId={fileId} condition={condition} evidence={evidence} />
      ))}
    </section>
  );
}

function EvidenceCard({
  fileId,
  condition,
  evidence,
}: {
  fileId: string;
  condition: Condition;
  evidence: ConditionEvidence;
}) {
  const failed = evidence.checks.filter((check) => check.result === "failed");
  const itemFailures = failed.filter((check) => check.check !== "no_large_deposit");
  // LP-937 — a later document did this item. The card stays, as the record of what arrived and what
  // its checks found. Its failed checks offer nothing to act on; its findings stay unless it was
  // replaced outright, because a statement that is still evidence can still be held by its deposit.
  const superseded = evidence.superseded;
  return (
    <div className={cn("flex flex-col gap-3", superseded && "opacity-70")}>
      <div className="flex items-start gap-3 rounded-lg border border-input bg-card p-3">
        <FileText className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-foreground">{evidence.title}</p>
          <p className="text-xs text-muted-foreground">
            {evidence.via_upload_link ? "Arrived through the borrower upload link" : "Arrived"} ·{" "}
            {arrived(evidence.arrived_at)} · linked to this condition automatically
          </p>
        </div>
        <Button asChild variant="outline" size="sm">
          <Link href={`/loan-files/${fileId}/documents?doc=${evidence.document_id}`}>
            <Eye className="h-3.5 w-3.5" aria-hidden />
            Open
          </Link>
        </Button>
      </div>

      <div>
        <p className="text-xs font-semibold uppercase tracking-wide text-foreground-2">Checks</p>
        <ul className="mt-1 flex flex-col divide-y divide-border">
          {evidence.checks.map((check) => (
            <CheckRow key={check.check} check={check} />
          ))}
        </ul>
      </div>

      {superseded ? (
        <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <CircleCheckBig className="h-3.5 w-3.5 text-success" aria-hidden />
          {superseded}
        </p>
      ) : evidence.status === "accepted" ? (
        <p className="text-xs text-muted-foreground">Accepted anyway: {evidence.accepted_reason}</p>
      ) : itemFailures.length > 0 ? (
        <FailedCallout
          fileId={fileId}
          condition={condition}
          evidence={evidence}
          count={itemFailures.length}
        />
      ) : null}

      {/* Only a REPLACED row's findings go: a superseded row that is still evidence can hold the
          condition by its deposit, and that must stay on screen and answerable (LP-937 review). */}
      {(evidence.replaced ? [] : evidence.findings).map((finding, index) => (
        <FindingBox
          key={`${finding.date}-${finding.amount}`}
          fileId={fileId}
          condition={condition}
          evidence={evidence}
          finding={finding}
          index={index}
        />
      ))}
    </div>
  );
}

function CheckRow({ check }: { check: EvidenceCheckResult }) {
  const Icon =
    check.result === "passed" ? CircleCheckBig : check.result === "failed" ? CircleX : CircleDashed;
  return (
    <li className="flex items-start gap-2 py-1.5 text-sm">
      <Icon
        className={cn(
          "mt-0.5 h-3.5 w-3.5 shrink-0",
          check.result === "passed" && "text-success",
          check.result === "failed" && "text-destructive",
          check.result === "not_run" && "text-muted-foreground",
        )}
        aria-label={check.result === "not_run" ? "not run" : check.result}
      />
      <span>
        <b className="font-medium text-foreground">{check.label}</b>{" "}
        <span className="text-xs text-foreground-2">
          {check.result === "not_run" ? `Not run — ${check.reason}` : check.reason}
        </span>
      </span>
    </li>
  );
}

/** S3-07's blocking callout: re-ask in the failed item's own email, or accept anyway with a reason. */
function FailedCallout({
  fileId,
  condition,
  evidence,
  count,
}: {
  fileId: string;
  condition: Condition;
  evidence: ConditionEvidence;
  count: number;
}) {
  const reask = useReaskEvidence(fileId);
  const accept = useAcceptEvidence(fileId);
  const [accepting, setAccepting] = useState(false);
  const [reason, setReason] = useState("");
  const [note, setNote] = useState<string | null>(null);
  // The failed item's own email: a receipt title sent is asked of title again (LP-938 follow-up).
  const reaskTo = evidence.reask_to ?? "borrower";
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-col gap-2 rounded-lg border border-destructive/40 bg-destructive/5 p-3 text-sm">
        <p className="inline-flex items-start gap-1.5">
          <CircleX className="mt-0.5 h-4 w-4 shrink-0 text-destructive" aria-hidden />
          <span>
            <b className="font-semibold">
              Not ready: {count} check{count === 1 ? "" : "s"} failed.
            </b>{" "}
            The condition stays <b className="font-semibold">{statusWords(condition)}</b>.
          </span>
        </p>
        <div className="flex flex-wrap items-center gap-2 pl-6">
          {evidence.reask ? (
            <Button
              type="button"
              size="sm"
              disabled={reask.isPending}
              onClick={() =>
                reask.mutate(
                  { conditionId: condition.id, evidenceId: evidence.id },
                  {
                    onSuccess: () => setNote(`Added to the ${reaskTo} email as a draft.`),
                    onError: (error) => setNote(getErrorMessage(error)),
                  },
                )
              }
            >
              <Mail className="h-3.5 w-3.5" aria-hidden />
              Add “please send {evidence.reask}” to the {reaskTo} email
            </Button>
          ) : null}
          <Button type="button" size="sm" variant="ghost" onClick={() => setAccepting(true)}>
            Accept anyway…
          </Button>
        </div>
        {accepting ? (
          <form
            className="flex flex-wrap items-center gap-2 pl-6"
            onSubmit={(event) => {
              event.preventDefault();
              accept.mutate(
                { conditionId: condition.id, evidenceId: evidence.id, reason: reason.trim() },
                { onError: (error) => setNote(getErrorMessage(error)) },
              );
            }}
          >
            <input
              aria-label="Why you are accepting it"
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              placeholder="Why — for example, page 6 is a blank back page"
              className="h-8 min-w-0 flex-1 rounded-md border border-input bg-background px-2 text-sm"
            />
            <Button type="submit" size="sm" disabled={!reason.trim() || accept.isPending}>
              Accept
            </Button>
          </form>
        ) : null}
      </div>
      <p className="text-xs text-muted-foreground">
        “Accept anyway” needs a reason and is kept in the history — for example, when page 6 is a
        blank back page.
      </p>
      {note ? <p className="text-xs text-muted-foreground">{note}</p> : null}
    </div>
  );
}

/** S3-08: a large deposit, its four figures, and her two answers. */
function FindingBox({
  fileId,
  condition,
  evidence,
  finding,
  index,
}: {
  fileId: string;
  condition: Condition;
  evidence: ConditionEvidence;
  finding: EvidenceFinding;
  index: number;
}) {
  const answer = useAnswerFinding(fileId);
  const [explaining, setExplaining] = useState(false);
  const [reason, setReason] = useState("");
  const [note, setNote] = useState<string | null>(null);
  const what = (finding.description || "deposit").toLowerCase();
  return (
    <div className="flex flex-col gap-2 rounded-lg border border-warning/50 bg-card p-3 text-sm">
      <p className="inline-flex flex-wrap items-center gap-2">
        <TriangleAlert className="h-4 w-4 text-warning" aria-hidden />
        <b className="font-semibold">
          New finding: a large deposit {finding.needed ? "needs sourcing" : "on the statement"}
        </b>
        {finding.citation ? (
          <span className="rounded-md border border-input px-1.5 py-0.5 text-xs text-foreground-2">
            {finding.citation}
          </span>
        ) : null}
      </p>
      <table className="w-full text-sm">
        <tbody className="divide-y divide-border">
          <Figure
            label={`Deposit on ${usDate(finding.date)} (${what})`}
            value={money(finding.amount)}
          />
          {finding.threshold && finding.income ? (
            <Figure
              label={`Large-deposit threshold: 50% of ${money(finding.income)} monthly income`}
              value={money(finding.threshold)}
            />
          ) : null}
          {finding.assets_without ? (
            <Figure
              label="Verified assets without this deposit"
              value={money(finding.assets_without)}
            />
          ) : null}
          {finding.required ? (
            <Figure label="Required for closing" value={money(finding.required)} />
          ) : null}
        </tbody>
      </table>
      <p className="text-xs text-foreground-2">
        {finding.needed
          ? "The deposit is needed to close, so it must be sourced. Payroll deposits on the same statement were explained by the statement itself and need nothing."
          : "The funds to close are there without it, so it can be left out of the verified assets instead of being sourced."}
      </p>
      {finding.status === "explained" ? (
        <p className="text-xs text-muted-foreground">Explained: {finding.reason}</p>
      ) : finding.status === "asked" ? (
        <p className="text-xs text-muted-foreground">
          Explanation asked — it is in the borrower email.
        </p>
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          <Button
            type="button"
            size="sm"
            disabled={answer.isPending}
            onClick={() =>
              answer.mutate(
                { conditionId: condition.id, evidenceId: evidence.id, index, answer: "ask" },
                { onError: (error) => setNote(getErrorMessage(error)) },
              )
            }
          >
            <Mail className="h-3.5 w-3.5" aria-hidden />
            Ask the borrower to explain it
          </Button>
          <Button type="button" size="sm" variant="outline" onClick={() => setExplaining(true)}>
            It’s already explained…
          </Button>
        </div>
      )}
      {explaining && finding.status === "open" ? (
        <form
          className="flex flex-wrap items-center gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            answer.mutate(
              {
                conditionId: condition.id,
                evidenceId: evidence.id,
                index,
                answer: "explained",
                reason: reason.trim(),
              },
              { onError: (error) => setNote(getErrorMessage(error)) },
            );
          }}
        >
          <input
            aria-label="How it is explained"
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            placeholder="How — for example, the gift letter and transfer are in the file"
            className="h-8 min-w-0 flex-1 rounded-md border border-input bg-background px-2 text-sm"
          />
          <Button type="submit" size="sm" disabled={!reason.trim() || answer.isPending}>
            Save
          </Button>
        </form>
      ) : null}
      {finding.needed && finding.status !== "explained" ? (
        <p className="text-xs text-muted-foreground">
          {condition.lender_code ?? "This condition"} stays{" "}
          <b className="font-semibold text-foreground">{statusWords(condition)}</b> until this is
          answered. All figures above are computed by code.
        </p>
      ) : null}
      {note ? <p className="text-xs text-muted-foreground">{note}</p> : null}
    </div>
  );
}

function Figure({ label, value }: { label: string; value: string }) {
  return (
    <tr>
      <td className="py-1.5 pr-3 text-xs text-foreground-2">{label}</td>
      <td className="py-1.5 text-right font-medium tabular-nums text-foreground">{value}</td>
    </tr>
  );
}

function statusWords(condition: Condition): string {
  if (condition.prep_status === "waiting")
    return `Waiting on ${waitingLabel(condition.waiting_on)}`;
  if (condition.prep_status === "to_do") return "To do";
  if (condition.prep_status === "ready") return "Ready to send";
  return "Sent to lender";
}

/** `4000.00` → `$4,000.00`, on the string (the server sends Decimal strings; no float). */
function money(value: string): string {
  const [whole = "0", cents = "00"] = value.split(".");
  const negative = whole.startsWith("-");
  const digits = negative ? whole.slice(1) : whole;
  return `${negative ? "-" : ""}$${digits.replace(/\B(?=(\d{3})+(?!\d))/g, ",")}.${cents.padEnd(2, "0").slice(0, 2)}`;
}

function usDate(iso: string | null): string {
  if (!iso) return "—";
  const [year, month, day] = iso.slice(0, 10).split("-");
  return `${month}/${day}/${year}`;
}

/** `Sep 2, 9:14 AM` in Eastern time, as S3-07 prints it. */
function arrived(iso: string): string {
  return new Date(iso).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZone: "America/New_York",
  });
}
