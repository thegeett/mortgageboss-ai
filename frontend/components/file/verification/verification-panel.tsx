"use client";

/**
 * The verification panel (LP-78/79/81) — the verification tab's control surface.
 *
 * The cross-source pass is a deliberate, manual AI call (it compares the stated data
 * against the documents). This panel runs it, shows whether the result is out of date
 * (staleness on document AND baseline edits), the needs-completeness guard, the
 * aggression dial, and the interactive findings list (LP-81: resolve / templated
 * wording / source location). The DTI/LTV calculators sit alongside it on the tab.
 */

import { CalculatorsSection } from "@/components/file/calculators/calculators-section";
import { FindingFilterPills } from "@/components/file/verification/finding-filters";
import { FindingsList } from "@/components/file/verification/findings-list";
import { NeedsCompleteness } from "@/components/file/verification/needs-completeness";
import { RuleFindingsTabs } from "@/components/file/verification/rule-findings-tabs";
import { VerificationStats } from "@/components/file/verification/verification-stats";
import { VersionSelector } from "@/components/file/verification/version-selector";
import { railClass } from "@/components/status-token";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { InlineErrorState } from "@/components/ui/error-state";
import { SkeletonText } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { dtiQueryKey } from "@/lib/api/dti";
import { ltvQueryKey } from "@/lib/api/ltv";
import { useUpdatePreferences } from "@/lib/api/preferences";
import { snapshotFindingsKey, useSnapshotFindings } from "@/lib/api/verification";
import {
  useResolveFinding,
  useRunVerification,
  useSetAggression,
  useVerification,
  verificationQueryKey,
} from "@/lib/api/verification";
import { humanize } from "@/lib/format";
import type { SnapshotFinding } from "@/lib/types/verification";
import type {
  AggressionLevel,
  VerificationFinding,
  VerificationStatus,
} from "@/lib/types/verification";
import { cn } from "@/lib/utils";
import { DEFAULT_FILTERS, type FindingFilters } from "@/lib/verification/finding-filters";
import { phaseLabel, remainingLabel } from "@/lib/verification/rule-findings";
import { useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Lock, Play, Sparkles, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { AGGRESSION_META, AggressionDial } from "./aggression-dial";
import { ThoroughnessControl } from "./thoroughness-control";

/** The legible consequence of moving the dial (the in-scope/clear↔blocked change). */
interface Consequence {
  message: string;
  tone: "info" | "blocked" | "clear";
}

/** A run that did not produce findings — either the trigger request never landed (`request`) or the
 * run reached the worker and failed there (`run`, carrying the run's own reason). */
type FailedRun = { kind: "request" } | { kind: "run"; detail: string | null };

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

  // `run.isError` is STICKY — TanStack holds it until the next `mutate` — so read on its own it would
  // pin the "didn't reach the server" banner for the life of the mount, outranking (and hiding) both a
  // real run failure and the staleness banner even after the panel had refetched a fresh run. Bound it
  // to what it actually claims: the failed click is the most recent thing we know only until the server
  // reports a run we had not seen when it failed — one triggered elsewhere, or a retry that did land.
  // Stamped during render (the "value from a previous render" pattern), reset once the error clears.
  const latestRunId = data?.latest_run?.id ?? null;
  const [runIdAtRequestFailure, setRunIdAtRequestFailure] = useState<string | null | undefined>(
    undefined,
  );
  if (run.isError && runIdAtRequestFailure === undefined) setRunIdAtRequestFailure(latestRunId);
  if (!run.isError && runIdAtRequestFailure !== undefined) setRunIdAtRequestFailure(undefined);
  const requestFailed = run.isError && runIdAtRequestFailure === latestRunId;

  // The two ways "Run verification" can come to nothing, unified into one thing to render. Both were
  // silent: the trigger POST had no `onError` at all, and a run that reached the worker and FAILED
  // there was never rendered. Either way the button re-enabled over an unchanged panel.
  //   - `request` — the POST itself was rejected (offline, 5xx, an expired session). No run exists.
  //   - `run` — a run was created and the worker failed it; `error_detail` carries the reason.
  // The request error wins while it is current: it is the more recent event, and it means the click the
  // processor just made did not land at all.
  const failedRun: FailedRun | null = requestFailed
    ? { kind: "request" }
    : data?.latest_run?.status === "failed"
      ? { kind: "run", detail: data.latest_run.error_detail ?? null }
      : null;

  // A FAILED run is the one case where a plain re-run is a no-op: the fingerprint cache is keyed on the
  // last COMPLETED run, so if the inputs have not changed since that run the POST returns it WITHOUT
  // creating a new one (api/verification.py) — the failed run stays `latest_run`, the banner stays up,
  // and the panel does not move. That is the "the button does nothing" report this banner exists to
  // explain, so force past the cache exactly there. A failed *request* never reached the server: no run
  // was created and nothing about the cache is suspect, so a network blip must not buy a full AI pass.
  const triggerRun = useCallback(() => run.mutate(failedRun?.kind === "run"), [run, failedRun]);

  /**
   * The ONE write for the thoroughness level, shared by both controls.
   *
   * There are two: the compact control in the header (LP-UI-046) and the
   * `AggressionDial` on the Old findings tab. That is deliberate rather than
   * duplication, and the split is by JOB — the header sets the level, which is
   * the frequent action and belongs where the file is being read; the dial also
   * owns the two rarer ones, "reset to default" and "set as my default", which
   * need the explanation that sits around them.
   *
   * They cannot disagree about the value, because both go through this. Recorded
   * because a future reader will see two controls for one setting and reach for
   * the delete key; what is genuinely undecided is whether the header should
   * eventually carry the defaults too, and that is a product call, not a tidy-up.
   */
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
      // LP-589 — the cross-source list too. It has no polling and a 60s staleTime, so a processor
      // watching that tab through a re-run kept seeing the PREVIOUS list — precisely when the
      // findings legitimately changed, and precisely the moment the tab is meant to be trusted.
      void queryClient.invalidateQueries({ queryKey: snapshotFindingsKey(fileId) });
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
    updatePreferences.mutate(
      { default_aggression_level: activeLevel },
      {
        // The verification status carries the (server-derived) default — refetch it.
        onSuccess: () =>
          void queryClient.invalidateQueries({ queryKey: verificationQueryKey(fileId) }),
      },
    );
  }, [activeLevel, updatePreferences, queryClient, fileId]);

  return (
    // LP-UI-020: a section, not a Card. This was Card > CardContent > tab panel >
    // finding card — four rounded borders and four shadows to reach one
    // sentence. The heading, the program, the version selector and both run
    // controls all survive; only the box around them is gone.
    <section aria-labelledby="verification-heading" className="space-y-4">
      <header className="flex flex-wrap items-start justify-between gap-x-6 gap-y-2">
        <div>
          <div className="flex items-center gap-2">
            <h2 id="verification-heading" className="text-label uppercase text-muted-foreground">
              Verification
            </h2>
            {data?.program && (
              <Badge variant="secondary" className="font-medium">
                {humanize(data.program)}
              </Badge>
            )}
          </div>
          <p className="mt-1 text-xs text-muted-foreground">
            The full rule set + the AI cross-source pass, against the documents — program- and
            lender-specific.
          </p>
          {data && (
            <div className="pt-1.5">
              <VersionSelector fileId={fileId} currentRunId={data.latest_run?.id ?? null} />
            </div>
          )}
        </div>
        <div className="flex flex-col items-end gap-1">
          <div className="flex items-center gap-2">
            {/* Beside Run verification, where the mockup puts it (LP-UI-046).
                It was only inside the Old findings tab — the one tab a processor
                has no reason to open. */}
            {data && (
              <ThoroughnessControl
                aggression={data.aggression}
                activeLevel={activeLevel}
                shownAt={(level) => shownCount(data, level)}
                onPick={pickLevel}
                busy={dialBusy}
              />
            )}
            <Button size="sm" className="gap-1.5" disabled={running} onClick={triggerRun}>
              {running ? <Spinner className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
              {running ? "Running…" : "Run verification"}
            </Button>
          </div>
          {/* LP-590 — WHICH phase, and where it sits in the sequence. A run takes about six and a
              half minutes; a bare spinner for that long is indistinguishable from a hung worker.
              A position rather than a percentage, deliberately: stage A scales with the file's
              transaction count, so the phases are not evenly sized and a bar would visibly stall. */}
          {running && data?.latest_run?.phase && (
            <span className="text-[11px] tabular-nums text-muted-foreground">
              {phaseLabel(data.latest_run.phase)}
              {data.latest_run.phase_index && data.latest_run.phase_total
                ? ` (${data.latest_run.phase_index} of ${data.latest_run.phase_total})`
                : ""}
              {(() => {
                const left = remainingLabel(
                  data.latest_run.estimated_total_seconds,
                  data.latest_run.elapsed_seconds,
                );
                return left ? ` · ${left}` : "";
              })()}
            </span>
          )}
          {/* Escape hatch (LP-376-A): force a run past the fingerprint cache, enqueuing BOTH passes. Shown
              whenever a prior run exists and we're not currently running — INCLUDING a failed run, which is
              exactly when you need it (the default button caches against the last COMPLETED run, so a failed
              or stale run leaves no other way to force). Gating this on status === "completed" hid the hatch
              after a failure — the bug this restores. The cache being blind to engine changes is LP-377. */}
          {data?.latest_run != null && !running && (
            <button
              type="button"
              onClick={() => run.mutate(true)}
              className="text-[11px] text-muted-foreground underline-offset-2 hover:text-foreground-2 hover:underline"
            >
              Re-run anyway
            </button>
          )}
        </div>
      </header>

      {/* The calculators sit between the run controls and the outcomes, as the
          mockup has them (LP-UI-046). They used to be rendered by the ROUTE
          above this whole section, which put the run controls and the
          thoroughness dial ~1,400px down the page — below the fold on a laptop,
          which is the same as not having them. */}
      <CalculatorsSection fileId={fileId} />
      <div aria-busy={isPending}>
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
            fileId={fileId}
            data={data}
            running={running}
            activeLevel={activeLevel}
            dialBusy={dialBusy}
            consequence={consequence}
            failedRun={failedRun}
            onPick={pickLevel}
            onResetToDefault={resetToDefault}
            onSetAsDefault={setAsDefault}
            onDismissConsequence={() => setConsequence(null)}
            onRetry={triggerRun}
          />
        )}
      </div>
    </section>
  );
}

function VerificationBody({
  fileId,
  data,
  running,
  activeLevel,
  dialBusy,
  consequence,
  failedRun,
  onPick,
  onResetToDefault,
  onSetAsDefault,
  onDismissConsequence,
  onRetry,
}: {
  fileId: string;
  data: VerificationStatus;
  activeLevel: AggressionLevel;
  dialBusy: boolean;
  consequence: Consequence | null;
  failedRun: FailedRun | null;
  onPick: (level: AggressionLevel) => void;
  onResetToDefault: () => void;
  onSetAsDefault: () => void;
  onDismissConsequence: () => void;
  onRetry: () => void;
  running: boolean;
}) {
  // LP-589 — read here, where the tabs are rendered, so the badge reports a real number.
  const crossSource = useSnapshotFindings(fileId);
  // LP-561 — the governed findings become actionable. This hook already refreshes the DTI, LTV
  // and needs list on success, which is exactly what an Apply or a Request needs.
  const resolveRuleFinding = useResolveFinding(fileId);
  // The file-level chrome sits ABOVE the tabs; the governed §8 tabs (1-4) render the rule engine's
  // output; the LEGACY body (the dial + stats + AI-sweep findings list) is quarantined into Tab 5, its
  // behaviour unchanged. The two systems' lists + counts are never merged (LP-375/376).
  return (
    <div className="space-y-4">
      {/* A FAILED run is the FIRST thing to say. It used to be said nowhere: the status was typed but
          never rendered, so a run that died on the worker (a dead AI call, a governed pass exhausted
          after retries) left the button re-enabled over an unchanged panel — indistinguishable from a
          click that did nothing, which is exactly how it was reported. Ranked above staleness: a run
          that failed is why the findings are old. */}
      {failedRun && <FailedRunBanner run={failedRun} onRetry={onRetry} retrying={running} />}
      {data.stale && !running && !failedRun && <StaleBanner />}
      <NeedsCompleteness fileId={fileId} />
      <RuleFindingsTabs
        fileId={fileId}
        // LP-589 — OPEN ones only. A badge counting signed-off and resolved findings would keep
        // showing work after a processor cleared it, which is the opposite of the signal it exists
        // to give.
        crossSourceCount={
          (crossSource.data ?? []).filter((f: SnapshotFinding) => f.disposition === "open").length
        }
        onAct={(action) => resolveRuleFinding.mutate(action)}
        // `?? []` guards a stale/version-skewed response missing the newly-added field — degrade to the
        // empty-state tabs rather than throwing in bucketRuleFindings and blanking the whole panel.
        ruleFindings={data.rule_findings ?? []}
        // LP-377-C: the latest run's rule engine did not complete → these findings are from an earlier run.
        ruleFindingsStale={data.rule_findings_stale ?? false}
        legacyCount={data.findings.length}
        legacy={
          <LegacyBody
            fileId={fileId}
            data={data}
            running={running}
            activeLevel={activeLevel}
            dialBusy={dialBusy}
            consequence={consequence}
            onPick={onPick}
            onResetToDefault={onResetToDefault}
            onSetAsDefault={onSetAsDefault}
            onDismissConsequence={onDismissConsequence}
          />
        }
      />
    </div>
  );
}

/** Tab 5 — the LEGACY quarantine: the AI cross-source sweep (+ retired xsrc rows) with its dial, stats,
 * filters, list, and actions UNCHANGED (LP-376 keeps the sweep identical). */
function LegacyBody({
  fileId,
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
  fileId: string;
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
  // The dial filters the OPEN findings by the active cutoff (a read-time view filter —
  // never re-fetched/re-run); resolved findings are kept in their own group below.
  const cutoff = data.aggression.cutoffs[activeLevel];
  const shownOpen = data.findings.filter(
    (f) => f.resolution_status === "open" && f.confidence >= cutoff,
  );

  // The severity + category pills (LP-88) — orthogonal to the dial; they slice the
  // in-scope set further. Held here so the stats reflect totals + the list reflects the slice.
  const [filters, setFilters] = useState<FindingFilters>(DEFAULT_FILTERS);

  return (
    <div className="space-y-4">
      {/* At-a-glance stats (LP-88) — where does this file stand. */}
      <VerificationStats fileId={fileId} data={data} activeLevel={activeLevel} />

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
      <RunSummary data={data} shown={shownOpen} running={running} />
      {!running && data.latest_run && <SubmitStatus data={data} activeLevel={activeLevel} />}

      {/* The filter pills (LP-88) — severity + category, composing with the dial. */}
      {shownOpen.length > 0 && (
        <FindingFilterPills findings={shownOpen} filters={filters} onChange={setFilters} />
      )}

      <FindingsList fileId={fileId} data={data} activeLevel={activeLevel} filters={filters} />
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
        "flex items-start gap-2 rounded-lg border px-3 py-2.5 text-sm text-foreground-2",
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
        className="shrink-0 text-muted-foreground hover:text-foreground-2"
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
        <span className="text-foreground-2">
          <span className="font-medium text-foreground">
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
      <span className="text-foreground-2">Clear to submit at {label} thoroughness.</span>
    </div>
  );
}

/**
 * The verification did not run — say so, say why, and offer the retry.
 *
 * The reason is the run's OWN ``error_detail``, not a guess: "AI cross-source pass failed" and
 * "Rule-engine pass failed after retries" are different operational problems, and a processor
 * forwarding a screenshot is the fastest route from "the button is broken" to the actual cause. It
 * degrades to the generic line when the detail is null (an older run, or a version-skewed backend).
 * Retry re-triggers exactly like the header button (see ``triggerRun``): forcing past the fingerprint
 * cache after a failed RUN, where the last completed run's inputs still matching would otherwise
 * return that stale run and look like another no-op; a plain re-run after a failed REQUEST, which
 * created no run and left the cache above suspicion.
 */
function FailedRunBanner({
  run,
  onRetry,
  retrying,
}: {
  run: FailedRun;
  onRetry: () => void;
  retrying: boolean;
}) {
  const message =
    run.kind === "request"
      ? "Couldn't start the verification — the request didn't reach the server. Check your connection and try again."
      : (run.detail ?? "The verification pass failed on the worker. No findings were produced.");

  return (
    // LP-UI-020 — a RAIL, not a tinted box. State lives on the left rule and the
    // glyph; a fill costs text contrast and stacks badly against hover and
    // focus. `danger` resolves because LP-UI-002 defined it as an alias of
    // `destructive` — before that, twenty class names across four files named a
    // colour that did not exist, and this banner drew no border at all.
    <div
      role="alert"
      className={cn(
        railClass("blocking"),
        "flex items-start gap-2 py-1.5 pl-3 text-sm text-foreground-2",
      )}
    >
      <X className="mt-0.5 h-4 w-4 shrink-0 text-danger" />
      <div className="flex-1 space-y-1.5">
        <p>
          <span className="font-medium text-foreground">Verification didn't complete</span> —{" "}
          {message}
        </p>
        <p className="text-xs text-muted-foreground">
          The findings below, if any, are from an earlier run.
        </p>
      </div>
      <Button
        size="sm"
        variant="outline"
        className="shrink-0"
        disabled={retrying}
        onClick={onRetry}
      >
        {retrying ? "Retrying…" : "Try again"}
      </Button>
    </div>
  );
}

function StaleBanner() {
  return (
    <div
      role="alert"
      className={cn(
        railClass("attention"),
        "flex items-start gap-2 py-1.5 pl-3 text-sm text-foreground-2",
      )}
    >
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
      <span>
        <span className="font-medium text-foreground">The file changed</span> — this verification is
        out of date. Re-run it to compare against the current data.
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
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
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
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
      <span className="inline-flex items-center gap-1 font-medium text-foreground-2">
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
