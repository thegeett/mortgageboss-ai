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
import { useUpdatePreferences } from "@/lib/api/preferences";
import {
  useRunVerification,
  useSetAggression,
  useVerification,
  verificationQueryKey,
} from "@/lib/api/verification";
import { formatPercent, humanize } from "@/lib/format";
import type {
  AggressionLevel,
  VerificationFinding,
  VerificationStatus,
} from "@/lib/types/verification";
import { cn } from "@/lib/utils";
import { useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Lock, Play, ScanSearch, Sparkles, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { AGGRESSION_META, AggressionDial } from "./aggression-dial";

/** The legible consequence of moving the dial (the in-scope/clear↔blocked change). */
interface Consequence {
  message: string;
  tone: "info" | "blocked" | "clear";
}

/** Count of findings shown (in-scope for display) at a given level's cutoff. */
function shownCount(data: VerificationStatus, level: AggressionLevel): number {
  const cutoff = data.aggression.cutoffs[level];
  return data.findings.filter((f) => f.confidence >= cutoff).length;
}

/**
 * Describe what changed when the dial moved — so the processor reads it as "I asked
 * for more/less scrutiny and got it", never as the system randomly changing the file.
 */
function describeChange(
  before: { shown: number; blocked: boolean },
  newLevel: AggressionLevel,
  after: VerificationStatus,
): Consequence {
  const label = AGGRESSION_META[newLevel].label;
  const nowShown = shownCount(after, newLevel);
  const delta = nowShown - before.shown;

  let lead: string;
  if (delta > 0) {
    lead = `${label} surfaced ${delta} more finding${delta === 1 ? "" : "s"} (${nowShown} now in scope).`;
  } else if (delta < 0) {
    const hidden = -delta;
    lead = `${label} now shows ${nowShown} finding${nowShown === 1 ? "" : "s"} (${hidden} lower-confidence ${hidden === 1 ? "one" : "ones"} hidden).`;
  } else {
    lead = `${label}: ${nowShown} finding${nowShown === 1 ? "" : "s"} in scope — no change.`;
  }

  if (!before.blocked && after.blocked) {
    return {
      tone: "blocked",
      message: `${lead} This file is now blocked — ${after.in_scope_open_count} open finding${after.in_scope_open_count === 1 ? "" : "s"} must be resolved to submit.`,
    };
  }
  if (before.blocked && !after.blocked) {
    return { tone: "clear", message: `${lead} This file is now clear at ${label} thoroughness.` };
  }
  return { tone: "info", message: lead };
}

export function VerificationPanel({ fileId }: { fileId: string }) {
  const { data, isPending, isError, refetch } = useVerification(fileId);
  const run = useRunVerification(fileId);
  const setAggression = useSetAggression(fileId);
  const updatePreferences = useUpdatePreferences();
  const running = data?.latest_run?.status === "running" || run.isPending;

  // The dial re-filters instantly: track the picked level optimistically so the
  // displayed in-scope set updates with zero latency while the server confirms the
  // (authoritative) blocking. Reconciled to the server level once it catches up.
  const [optimisticLevel, setOptimisticLevel] = useState<AggressionLevel | null>(null);
  const serverLevel = data?.aggression.level;
  useEffect(() => {
    if (optimisticLevel !== null && serverLevel === optimisticLevel) setOptimisticLevel(null);
  }, [optimisticLevel, serverLevel]);
  const activeLevel = optimisticLevel ?? serverLevel ?? "balanced";

  // The legible consequence of the last dial move (cleared on a new run / dismiss).
  const [consequence, setConsequence] = useState<Consequence | null>(null);

  const dialBusy = setAggression.isPending || updatePreferences.isPending;

  const pickLevel = useCallback(
    (level: AggressionLevel) => {
      if (!data || level === activeLevel) return;
      const before = { shown: shownCount(data, activeLevel), blocked: data.blocked };
      setOptimisticLevel(level); // instant display re-filter (no AI re-run)
      setAggression.mutate(level, {
        onSuccess: (after) => setConsequence(describeChange(before, level, after)),
      });
    },
    [data, activeLevel, setAggression],
  );

  // When a pass finishes, the findings changed — refresh the finding-coupled
  // calculators so their "unresolved findings" alert + count reflect the new run
  // (they're cached separately and won't refetch on their own). A fresh run also
  // makes the prior dial-consequence stale, so clear it.
  const queryClient = useQueryClient();
  const prevStatus = useRef<string | undefined>(undefined);
  const status = data?.latest_run?.status;
  useEffect(() => {
    if (prevStatus.current === "running" && status === "completed") {
      void queryClient.invalidateQueries({ queryKey: dtiQueryKey(fileId) });
      void queryClient.invalidateQueries({ queryKey: ltvQueryKey(fileId) });
      setConsequence(null);
    }
    prevStatus.current = status;
  }, [status, fileId, queryClient]);

  const resetToDefault = useCallback(() => {
    if (!data) return;
    const before = { shown: shownCount(data, activeLevel), blocked: data.blocked };
    setOptimisticLevel(data.aggression.default);
    setAggression.mutate(null, {
      onSuccess: (after) => setConsequence(describeChange(before, after.aggression.level, after)),
    });
  }, [data, activeLevel, setAggression]);

  const setAsDefault = useCallback(() => {
    updatePreferences.mutate(activeLevel, {
      // The verification status carries the (server-derived) default — refetch it.
      onSuccess: () =>
        void queryClient.invalidateQueries({ queryKey: verificationQueryKey(fileId) }),
    });
  }, [activeLevel, updatePreferences, queryClient, fileId]);

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
        <div className="flex flex-col items-end gap-1">
          <Button
            size="sm"
            className="gap-1.5"
            disabled={running}
            onClick={() => run.mutate(false)}
          >
            {running ? <Spinner className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
            {running ? "Running…" : "Run verification"}
          </Button>
          {/* Escape hatch: re-run the AI even when inputs are unchanged. The default
              button returns the cached result instantly when nothing changed. */}
          {data?.latest_run?.status === "completed" && !running && (
            <button
              type="button"
              onClick={() => run.mutate(true)}
              className="text-[11px] text-gray-400 underline-offset-2 hover:text-gray-600 hover:underline"
            >
              Re-run anyway
            </button>
          )}
        </div>
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
          <VerificationBody
            data={data}
            running={running}
            activeLevel={activeLevel}
            dialBusy={dialBusy}
            consequence={consequence}
            onPick={pickLevel}
            onResetToDefault={resetToDefault}
            onSetAsDefault={setAsDefault}
            onDismissConsequence={() => setConsequence(null)}
          />
        )}
      </CardContent>
    </Card>
  );
}

function VerificationBody({
  data,
  running,
  activeLevel,
  dialBusy,
  consequence,
  onPick,
  onResetToDefault,
  onSetAsDefault,
  onDismissConsequence,
}: {
  data: VerificationStatus;
  activeLevel: AggressionLevel;
  dialBusy: boolean;
  consequence: Consequence | null;
  onPick: (level: AggressionLevel) => void;
  onResetToDefault: () => void;
  onSetAsDefault: () => void;
  onDismissConsequence: () => void;
  running: boolean;
}) {
  // The dial is a read-time view filter: show only findings at/above the active
  // cutoff. The same stored findings, re-filtered — never re-fetched or re-run.
  const cutoff = data.aggression.cutoffs[activeLevel];
  const shown = data.findings.filter((f) => f.confidence >= cutoff);
  const hidden = data.findings.length - shown.length;

  return (
    <div className="space-y-4">
      {data.stale && !running && <StaleBanner />}
      <AggressionDial
        aggression={data.aggression}
        activeLevel={activeLevel}
        onPick={onPick}
        onResetToDefault={onResetToDefault}
        onSetAsDefault={onSetAsDefault}
        busy={dialBusy}
      />
      {consequence && (
        <ConsequenceBanner consequence={consequence} onDismiss={onDismissConsequence} />
      )}
      <RunSummary data={data} shown={shown} running={running} />
      {!running && data.latest_run && <SubmitStatus data={data} activeLevel={activeLevel} />}
      {shown.length === 0 ? (
        <p className="text-sm text-gray-400">
          {!data.latest_run
            ? "Not run yet — run verification to compare the stated data against the documents."
            : data.findings.length === 0
              ? "No cross-source discrepancies surfaced."
              : `No findings at ${AGGRESSION_META[activeLevel].label} thoroughness — ${hidden} lower-confidence ${hidden === 1 ? "finding is" : "findings are"} hidden. Dial up to Thorough to see ${hidden === 1 ? "it" : "them"}.`}
        </p>
      ) : (
        <ul className="space-y-2">
          {shown.map((f) => (
            <FindingRow key={f.id} finding={f} />
          ))}
        </ul>
      )}
    </div>
  );
}

function ConsequenceBanner({
  consequence,
  onDismiss,
}: {
  consequence: Consequence;
  onDismiss: () => void;
}) {
  const tone = {
    info: { border: "border-info/40", bg: "bg-info/5", icon: "text-info", Icon: Sparkles },
    blocked: {
      border: "border-warning/50",
      bg: "bg-warning/10",
      icon: "text-warning",
      Icon: Lock,
    },
    clear: {
      border: "border-success/40",
      bg: "bg-success/5",
      icon: "text-success",
      Icon: CheckCircle2,
    },
  }[consequence.tone];
  const Icon = tone.Icon;
  return (
    <output
      className={cn(
        "flex items-start gap-2 rounded-lg border px-3 py-2.5 text-sm text-gray-700",
        tone.border,
        tone.bg,
      )}
    >
      <Icon className={cn("mt-0.5 h-4 w-4 shrink-0", tone.icon)} />
      <span className="flex-1">{consequence.message}</span>
      <button
        type="button"
        onClick={onDismiss}
        aria-label="Dismiss"
        className="shrink-0 text-gray-400 hover:text-gray-600"
      >
        <X className="h-3.5 w-3.5" />
      </button>
    </output>
  );
}

/** The blocking consequence, always legible: what "clear" means at this thoroughness. */
function SubmitStatus({
  data,
  activeLevel,
}: {
  data: VerificationStatus;
  activeLevel: AggressionLevel;
}) {
  const label = AGGRESSION_META[activeLevel].label;
  if (data.blocked) {
    return (
      <div className="flex items-center gap-2 text-xs text-warning">
        <Lock className="h-3.5 w-3.5 shrink-0" />
        <span className="text-gray-600">
          <span className="font-medium text-gray-800">
            {data.in_scope_open_count} open finding{data.in_scope_open_count === 1 ? "" : "s"}
          </span>{" "}
          must be resolved to submit (at {label} thoroughness).
        </span>
      </div>
    );
  }
  return (
    <div className="flex items-center gap-2 text-xs text-success">
      <CheckCircle2 className="h-3.5 w-3.5 shrink-0" />
      <span className="text-gray-600">Clear to submit at {label} thoroughness.</span>
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

function RunSummary({
  data,
  shown,
  running,
}: {
  data: VerificationStatus;
  shown: VerificationFinding[];
  running: boolean;
}) {
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
  // Count from the in-scope (shown) list at the active thoroughness — never the
  // run's per-run counts — so the summary can't disagree with the findings below it.
  // The dial changes which findings are in scope, never their intrinsic severity.
  const total = shown.length;
  const red = shown.filter((f) => f.status === "red").length;
  const yellow = shown.filter((f) => f.status === "yellow").length;
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
