"use client";

/**
 * LP-586 — the snapshot-based AI cross-source tab.
 *
 * WHAT MAKES THIS TAB DIFFERENT, and why it is worth its own space: the governed rules each ask one
 * scoped question and prove it. This pass reads the whole frozen snapshot looking for a fact in one
 * source that can be CHECKED AGAINST a fact in another, and hands the pairing to a processor. On a
 * real file it found a tax bill's assessed value sitting beside a stated valuation nobody had
 * reconciled, and a tax bill naming two owners beside an application with one borrower — while the
 * rule that asks about title vesting was abstaining for want of a document one folder away.
 *
 * IT NOTICES; IT DOES NOT JUDGE. There is no rule spec behind any of these, no calibrated threshold
 * and no guideline citation, so there is deliberately NO APPLY — nothing here writes to the loan.
 * The processor signs off, dismisses, or leaves it open.
 *
 * AND IT DOES NOT MOVE. The list is refreshed by the verification RUN and only when the snapshot's
 * fingerprint changes, so opening the tab twice shows the same thing — the property the older
 * cross-source tab could not offer, because its inputs were reassembled from live tables each run.
 */

import { Button } from "@/components/ui/button";
import { InlineErrorState } from "@/components/ui/error-state";
import { SkeletonText } from "@/components/ui/skeleton";
import { useSetSnapshotFindingDisposition, useSnapshotFindings } from "@/lib/api/verification";
import type { SnapshotFinding } from "@/lib/types/verification";
import { cn } from "@/lib/utils";
import { Check, CheckCircle2, Layers, X } from "lucide-react";

const DISPOSITION: Record<string, { label: string; tone: string }> = {
  // The SYSTEM's two.
  open: { label: "Open", tone: "bg-primary/10 text-primary" },
  resolved: { label: "Resolved by a file change", tone: "bg-success/10 text-success" },
  // The PROCESSOR's two.
  signed_off: { label: "Signed off", tone: "bg-muted text-foreground-2" },
  not_an_issue: { label: "Not an issue", tone: "bg-muted text-foreground-2" },
};

function Row({ finding, fileId }: { finding: SnapshotFinding; fileId: string }) {
  const setDisposition = useSetSnapshotFindingDisposition(fileId);
  const meta = DISPOSITION[finding.disposition] ?? DISPOSITION.open;
  const isOpen = finding.disposition === "open";
  const isResolved = finding.disposition === "resolved";

  return (
    <li
      className={cn(
        "rounded-md border p-3",
        isOpen ? "border-border bg-card" : "border-border bg-muted/60",
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 space-y-1">
          <p
            className={cn(
              "text-sm font-medium",
              isOpen ? "text-foreground" : "text-muted-foreground",
            )}
          >
            {finding.title}
          </p>
          <p className="text-xs leading-relaxed text-foreground-2">{finding.detail}</p>
        </div>
        <span
          className={cn("shrink-0 rounded-full px-2 py-0.5 text-[10px] font-medium", meta?.tone)}
        >
          {meta?.label}
        </span>
      </div>

      {/* THE TWO SIDES. A cross-source finding is only checkable if the processor can see both
          figures without reopening every document — that is the whole value of the pairing. */}
      {finding.sources.length > 0 && (
        <dl className="mt-2 grid gap-x-4 gap-y-1 border-t border-border pt-2 text-xs sm:grid-cols-2">
          {finding.sources.map((source) => (
            <div key={`${source.label}-${source.value}`} className="flex justify-between gap-2">
              <dt className="truncate text-muted-foreground">{source.label}</dt>
              <dd className="shrink-0 font-medium tabular-nums text-foreground">{source.value}</dd>
            </div>
          ))}
        </dl>
      )}

      {finding.disposition_note && (
        <p className="mt-2 text-[11px] italic text-muted-foreground">{finding.disposition_note}</p>
      )}

      {/* NO APPLY — see the header. These record a decision and change nothing on the loan. */}
      {isOpen && (
        <div className="mt-2 flex gap-1.5">
          <Button
            size="sm"
            variant="outline"
            className="h-7 gap-1 px-2 text-xs"
            disabled={setDisposition.isPending}
            onClick={() =>
              setDisposition.mutate({ findingId: finding.id, disposition: "signed_off" })
            }
            title="You reviewed this pairing and it is fine — nothing on the loan changes"
          >
            <Check className="h-3 w-3" /> Sign off
          </Button>
          <Button
            size="sm"
            variant="ghost"
            className="h-7 gap-1 px-2 text-xs"
            disabled={setDisposition.isPending}
            onClick={() =>
              setDisposition.mutate({ findingId: finding.id, disposition: "not_an_issue" })
            }
            title="The comparison does not hold — dismiss it"
          >
            <X className="h-3 w-3" /> Not an issue
          </Button>
        </div>
      )}

      {/* A dispositioned finding can be put back — a processor who signed off in error should not
          have to wait for the file to change to undo it. `resolved` is NOT reopenable here: the
          system set it because the file stopped producing the finding, and a person claiming
          otherwise would make the tab lie about why something cleared. */}
      {!isOpen && !isResolved && (
        <button
          type="button"
          className="mt-2 text-[11px] text-muted-foreground underline hover:text-foreground-2"
          disabled={setDisposition.isPending}
          onClick={() => setDisposition.mutate({ findingId: finding.id, disposition: "open" })}
        >
          Reopen
        </button>
      )}
    </li>
  );
}

export function SnapshotFindingsTab({ fileId }: { fileId: string }) {
  const { data, isPending, isError, refetch } = useSnapshotFindings(fileId);

  if (isPending) return <SkeletonText lines={4} />;
  if (isError) {
    return (
      <InlineErrorState message="Couldn't load the cross-checks." onRetry={() => void refetch()} />
    );
  }

  const findings = data ?? [];
  if (findings.length === 0) {
    return (
      <div className="flex flex-col items-center gap-2 py-10 text-center">
        <Layers className="h-8 w-8 text-muted-foreground" />
        <p className="text-sm font-medium text-foreground-2">Nothing flagged on a cross-check</p>
        <p className="max-w-md text-xs text-muted-foreground">
          This pass reads the whole snapshot for a fact in one source that can be checked against a
          fact in another. It runs with verification, and only re-reads when the file actually
          changes — so an empty list here means the last run found nothing to reconcile, not that
          nothing was looked at.
        </p>
      </div>
    );
  }

  const open = findings.filter((f) => f.disposition === "open");
  const rest = findings.filter((f) => f.disposition !== "open");

  return (
    <div className="space-y-4">
      {open.length > 0 && (
        <ul className="space-y-2">
          {open.map((f) => (
            <Row key={f.id} finding={f} fileId={fileId} />
          ))}
        </ul>
      )}
      {rest.length > 0 && (
        <section className="space-y-2">
          <h4 className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            <CheckCircle2 className="h-3 w-3" /> Reviewed
          </h4>
          <ul className="space-y-2">
            {rest.map((f) => (
              <Row key={f.id} finding={f} fileId={fileId} />
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
