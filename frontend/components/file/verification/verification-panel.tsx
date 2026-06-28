"use client";

/**
 * The verification panel (LP-78) — the minimal trigger + staleness surface.
 *
 * The cross-source pass is a deliberate, manual AI call (it compares the stated
 * data against the documents — meaningful only when both are assembled). This
 * panel runs it and shows whether the result is out of date; it lists the surfaced
 * findings **read-only** (the rich findings UI + resolution flow is LP-81).
 */

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { InlineErrorState } from "@/components/ui/error-state";
import { SkeletonText } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { dtiQueryKey } from "@/lib/api/dti";
import { ltvQueryKey } from "@/lib/api/ltv";
import { useRunVerification, useVerification } from "@/lib/api/verification";
import { formatPercent, humanize } from "@/lib/format";
import type { VerificationFinding, VerificationStatus } from "@/lib/types/verification";
import { cn } from "@/lib/utils";
import { useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Play, ScanSearch, Sparkles } from "lucide-react";
import { useEffect, useRef } from "react";

export function VerificationPanel({ fileId }: { fileId: string }) {
  const { data, isPending, isError, refetch } = useVerification(fileId);
  const run = useRunVerification(fileId);
  const running = data?.latest_run?.status === "running" || run.isPending;

  // When a pass finishes, the findings changed — refresh the finding-coupled
  // calculators so their "unresolved findings" alert + count reflect the new run
  // (they're cached separately and won't refetch on their own).
  const queryClient = useQueryClient();
  const prevStatus = useRef<string | undefined>(undefined);
  const status = data?.latest_run?.status;
  useEffect(() => {
    if (prevStatus.current === "running" && status === "completed") {
      void queryClient.invalidateQueries({ queryKey: dtiQueryKey(fileId) });
      void queryClient.invalidateQueries({ queryKey: ltvQueryKey(fileId) });
    }
    prevStatus.current = status;
  }, [status, fileId, queryClient]);

  return (
    <Card className="border-gray-200/80 shadow-sm">
      <CardHeader className="flex-row items-start justify-between space-y-0 pb-4">
        <div className="space-y-1">
          <CardTitle className="flex items-center gap-2 text-base font-semibold text-gray-900">
            <span className="flex h-7 w-7 items-center justify-center rounded-md bg-primary/10 text-primary">
              <ScanSearch className="h-4 w-4" />
            </span>
            Cross-source verification
          </CardTitle>
          <p className="pl-9 text-xs text-gray-500">
            Reads the stated application against the documents and surfaces what doesn&rsquo;t line
            up.
          </p>
        </div>
        <Button size="sm" className="gap-1.5" disabled={running} onClick={() => run.mutate()}>
          {running ? <Spinner className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
          {running ? "Running…" : "Run verification"}
        </Button>
      </CardHeader>
      <CardContent aria-busy={isPending}>
        {isPending ? (
          <>
            <output className="sr-only">Loading verification</output>
            <SkeletonText lines={3} />
          </>
        ) : isError || !data ? (
          <InlineErrorState
            message="Couldn't load the verification status."
            onRetry={() => void refetch()}
          />
        ) : (
          <VerificationBody data={data} running={running} />
        )}
      </CardContent>
    </Card>
  );
}

function VerificationBody({
  data,
  running,
}: {
  data: VerificationStatus;
  running: boolean;
}) {
  return (
    <div className="space-y-4">
      {data.stale && !running && <StaleBanner />}
      <RunSummary data={data} running={running} />
      {data.findings.length === 0 ? (
        <p className="text-sm text-gray-400">
          {data.latest_run
            ? "No cross-source discrepancies surfaced."
            : "Not run yet — run verification to compare the stated data against the documents."}
        </p>
      ) : (
        <ul className="space-y-2">
          {data.findings.map((f) => (
            <FindingRow key={f.id} finding={f} />
          ))}
        </ul>
      )}
    </div>
  );
}

function StaleBanner() {
  return (
    <div
      role="alert"
      className="flex items-start gap-2 rounded-lg border border-warning/40 bg-warning/5 px-3 py-2.5 text-sm text-gray-700"
    >
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
      <span>
        <span className="font-medium text-gray-900">Documents changed</span> — this verification is
        out of date. Re-run it to compare against the current file.
      </span>
    </div>
  );
}

function RunSummary({ data, running }: { data: VerificationStatus; running: boolean }) {
  if (running) {
    return (
      <div className="flex items-center gap-2 text-sm text-gray-500">
        <Spinner className="h-3.5 w-3.5" />
        Comparing the stated data against the documents…
      </div>
    );
  }
  if (!data.latest_run || data.latest_run.status !== "completed") {
    return null;
  }
  // Count from the rendered list (not the run's per-run counts) so the summary
  // can never disagree with the findings shown below it.
  const total = data.findings.length;
  const red = data.findings.filter((f) => f.status === "red").length;
  const yellow = data.findings.filter((f) => f.status === "yellow").length;
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-gray-500">
      <span className="inline-flex items-center gap-1 font-medium text-gray-700">
        <Sparkles className="h-3.5 w-3.5 text-primary" /> AI cross-source
      </span>
      <span>
        {total} finding{total === 1 ? "" : "s"}
      </span>
      {red > 0 && <span className="text-destructive">{red} red</span>}
      {yellow > 0 && <span className="text-warning">{yellow} yellow</span>}
    </div>
  );
}

function FindingRow({ finding }: { finding: VerificationFinding }) {
  const red = finding.status === "red";
  return (
    <li className="rounded-lg border border-gray-200 px-3 py-2">
      <div className="flex items-start gap-2">
        <span
          className={cn(
            "mt-1.5 h-2 w-2 shrink-0 rounded-full",
            red ? "bg-destructive" : "bg-warning",
          )}
          aria-hidden
        />
        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between gap-2">
            <span className="text-sm font-medium text-gray-900">{finding.message}</span>
            <Badge variant="outline" className="shrink-0 font-normal text-gray-500">
              {humanize(finding.resolution_status)}
            </Badge>
          </div>
          <div className="mt-0.5 flex flex-wrap items-center gap-x-2 text-[11px] text-gray-400">
            <span>{humanize(finding.rule_id.replace("cross_source.", ""))}</span>
            <span>· {formatPercent(String(finding.confidence * 100))} confidence</span>
            {finding.source_page !== null && <span>· p.{finding.source_page}</span>}
          </div>
          {finding.source_snippet && (
            <p className="mt-1 truncate font-mono text-[11px] text-gray-500">
              “{finding.source_snippet}”
            </p>
          )}
        </div>
      </div>
    </li>
  );
}
