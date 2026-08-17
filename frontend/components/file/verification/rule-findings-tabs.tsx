"use client";

/**
 * The five §8 tabs (LP-376) — the first human view of the rule engine's governed output.
 *
 * Tabs 1-4 read `rule_findings` (the governed engine); Tab 5 reads the legacy `findings` list (the AI sweep
 * + retired xsrc rows). They are NEVER merged and their counts are NEVER summed (LP-375 made that
 * structural; this preserves it). Tab 1 (Needs attention) is default and groups its three outcomes —
 * `open` first — so the real violations don't drown in `couldnt_check`. Tab 4 (Not applicable) is
 * structurally empty (those subjects aren't persisted) and says so honestly rather than being dropped.
 */

import { humanize } from "@/lib/format";
import type { EvaluationOutcome, RuleFinding } from "@/lib/types/verification";
import { cn } from "@/lib/utils";
import {
  OUTCOME_META,
  type OutcomeTone,
  type TabId,
  attentionGroups,
  bucketRuleFindings,
  groupByRule,
  outcomeMeta,
} from "@/lib/verification/rule-findings";
import {
  Archive,
  CheckCircle2,
  ChevronDown,
  CircleSlash,
  History,
  TriangleAlert,
} from "lucide-react";
import type { ReactNode } from "react";
import { useId, useState } from "react";
import { RuleFindingRow } from "./rule-finding-row";

interface TabDef {
  id: TabId;
  label: string;
  count: number;
  /** Count-badge emphasis: "danger" = a violation (`open`), "warning" = a blocking gap (`couldnt_check`).
   *  A gap must not read as fine at a glance (the honesty contract) — hence a distinct warning tone. */
  tone?: "danger" | "warning";
}

function TabStrip({
  tabs,
  active,
  onPick,
}: {
  tabs: TabDef[];
  active: TabId;
  onPick: (id: TabId) => void;
}) {
  return (
    <div
      role="tablist"
      aria-label="Verification outcomes"
      className="flex gap-1 overflow-x-auto border-b border-gray-200"
    >
      {tabs.map((tab) => {
        const isActive = tab.id === active;
        return (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={isActive}
            onClick={() => onPick(tab.id)}
            className={cn(
              "flex shrink-0 items-center gap-1.5 border-b-2 px-3 py-2 text-sm transition-colors",
              isActive
                ? "border-primary font-semibold text-gray-900"
                : "border-transparent text-gray-500 hover:text-gray-800",
            )}
          >
            {tab.label}
            <span
              className={cn(
                "rounded-full px-1.5 py-px text-[11px] font-medium tabular-nums",
                tab.tone === "danger"
                  ? "bg-destructive/10 text-destructive"
                  : tab.tone === "warning"
                    ? "bg-warning/10 text-warning"
                    : isActive
                      ? "bg-primary/10 text-primary"
                      : "bg-gray-100 text-gray-500",
              )}
            >
              {tab.count}
            </span>
          </button>
        );
      })}
    </div>
  );
}

function EmptyState({ icon, title, body }: { icon: ReactNode; title: string; body: string }) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed border-gray-200 px-6 py-10 text-center">
      <div className="text-gray-300">{icon}</div>
      <p className="text-sm font-medium text-gray-600">{title}</p>
      <p className="max-w-md text-xs leading-relaxed text-gray-400">{body}</p>
    </div>
  );
}

/** Tab 1 — the three outcomes grouped + labelled, `open` first (the real signal must not drown). */
function AttentionTab({ findings }: { findings: RuleFinding[] }) {
  if (findings.length === 0) {
    return (
      <EmptyState
        icon={<CheckCircle2 className="h-8 w-8" />}
        title="Nothing needs attention"
        body="No rule fired, could-not-check, or is awaiting review on this file. When the engine finds a violation, a gap, or a judgment to ratify, it appears here — grouped by kind."
      />
    );
  }
  const groups = attentionGroups(findings);
  return (
    <div className="space-y-5">
      {groups.map(({ outcome, findings: groupFindings }) => (
        <OutcomeGroup key={outcome} outcome={outcome} findings={groupFindings} />
      ))}
    </div>
  );
}

function OutcomeGroup({
  outcome,
  findings,
}: {
  outcome: EvaluationOutcome;
  findings: RuleFinding[];
}) {
  const meta = outcomeMeta(outcome);
  return (
    <section className="space-y-2">
      <div className="flex items-baseline gap-2">
        <h4 className="text-sm font-semibold text-gray-800">{meta.label}</h4>
        <span className="text-xs tabular-nums text-gray-400">{findings.length}</span>
        <span className="text-xs text-gray-400">— {meta.blurb}</span>
      </div>
      <GroupedFindingList findings={findings} />
    </section>
  );
}

/** LP-376-C: render findings that share a rule + reason as ONE summary row (expandable to WHICH ones), so
 * N documents failing a check the same way don't read as N identical lines. A lone finding renders plainly.
 * A pure display collapse — the underlying findings (and their reconcile keys) are untouched. */
function GroupedFindingList({ findings }: { findings: RuleFinding[] }) {
  return (
    <div className="space-y-2">
      {groupByRule(findings).map((group) => {
        const first = group[0];
        if (first === undefined) return null; // never — groups are non-empty by construction
        return group.length === 1 ? (
          <RuleFindingRow key={first.id} finding={first} />
        ) : (
          <CollapsedFindings key={first.id} findings={group} />
        );
      })}
    </div>
  );
}

// The collapsed-summary dot color per outcome tone — so a collapsed SATISFIED group reads green (a pass),
// an `open` group red, etc., not a blanket warning (every member of a group shares one outcome).
const TONE_DOT: Record<OutcomeTone, string> = {
  danger: "bg-destructive",
  warning: "bg-warning",
  info: "bg-info",
  success: "bg-success",
  muted: "bg-gray-300",
};

/**
 * The one line a collapsed group shows before it is expanded.
 *
 * When every member says the same thing, that sentence IS the summary (LP-376-C's behaviour, unchanged —
 * ID-7's 4 unclassified documents still read as their shared reason). When they differ — which is every
 * JUDGMENT rule, since the model writes a distinct sentence per subject — showing the first member's
 * message would attribute one deposit's finding to all of them. LP-518 names the subjects instead, which
 * is true of the whole group and is what a processor triages on.
 */
function collapsedSummary(findings: RuleFinding[]): string {
  const first = findings[0];
  if (first === undefined) return "";
  if (findings.every((f) => f.message === first.message)) return first.message;
  // NOT prefixed with the count — the badge two lines up already renders "N findings", and printing it
  // here too read as "3 findings   3 findings — …".
  const subjects = findings.map((f) => f.subject_label).filter(Boolean);
  // Every label empty (a subject type the read path could not name) would leave a bare dangling dash,
  // so fall back to the shared-message form rather than punctuation with nothing after it.
  if (subjects.length === 0) return first.message;
  const shown = subjects.slice(0, 3).join(", ");
  const rest = subjects.length - 3;
  return rest > 0 ? `${shown}, and ${rest} more` : shown;
}

function CollapsedFindings({ findings }: { findings: RuleFinding[] }) {
  const first = findings[0];
  // A VIOLATION group starts EXPANDED. LP-518 widened grouping from rule+message to rule alone, which
  // also swept up `open` findings whose messages genuinely differ per subject — collapsing those hid the
  // violation text and its how_to_fix behind a click, which is not the noise this set out to remove.
  // Grouping still applies (one card per rule, as asked); only the default disclosure state differs.
  const [open, setOpen] = useState(first?.evaluation_outcome === "open");
  const panelId = useId();
  if (first === undefined) return null; // never — the caller only builds this for a non-empty group
  const dot = TONE_DOT[outcomeMeta(first.evaluation_outcome).tone];
  return (
    <div className="rounded-lg border border-gray-200/70">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls={panelId}
        className="flex w-full items-start gap-2.5 rounded-lg px-3 py-2.5 text-left hover:bg-gray-50/70"
      >
        <span className={cn("mt-1.5 h-2 w-2 shrink-0 rounded-full", dot)} aria-hidden />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="font-mono text-xs font-semibold text-gray-800">{first.rule_id}</span>
            <span className="text-[11px] text-gray-400">{humanize(first.category)}</span>
            <span className="rounded bg-gray-100 px-1.5 py-px text-[11px] font-medium text-gray-600">
              {findings.length} findings
            </span>
          </div>
          <p className="mt-0.5 text-sm text-gray-700">{collapsedSummary(findings)}</p>
        </div>
        <ChevronDown
          className={cn(
            "mt-0.5 h-4 w-4 shrink-0 text-gray-300 transition-transform",
            open && "rotate-180",
          )}
        />
      </button>
      {open && (
        <div id={panelId} className="space-y-2 border-t border-gray-100 bg-gray-50/40 px-3 py-3">
          {findings.map((finding) => (
            <RuleFindingRow key={finding.id} finding={finding} />
          ))}
        </div>
      )}
    </div>
  );
}

function FindingList({ findings }: { findings: RuleFinding[] }) {
  // Also collapsed by reason (LP-376-C) — e.g. AS-1's 15 identical "deposit sourced" satisfied rows.
  return <GroupedFindingList findings={findings} />;
}

export function RuleFindingsTabs({
  ruleFindings,
  ruleFindingsStale = false,
  legacyCount,
  legacy,
}: {
  ruleFindings: RuleFinding[];
  /** LP-377-C: the latest run's rule engine did not complete — these findings are from an earlier run. */
  ruleFindingsStale?: boolean;
  legacyCount: number;
  legacy: ReactNode;
}) {
  const [active, setActive] = useState<TabId>("attention");
  const buckets = bucketRuleFindings(ruleFindings);
  const openCount = buckets.attention.filter((f) => f.evaluation_outcome === "open").length;
  const couldntCheckCount = buckets.attention.filter(
    (f) => f.evaluation_outcome === "couldnt_check",
  ).length;

  const tabs: TabDef[] = [
    {
      id: "attention",
      label: "Needs attention",
      count: buckets.attention.length,
      // A violation reds the badge; a blocking gap (couldnt_check, no open) warns it — never neutral, so
      // a file that only "couldn't check" doesn't read as fine at the tab-strip glance (honesty contract).
      tone: openCount > 0 ? "danger" : couldntCheckCount > 0 ? "warning" : undefined,
    },
    { id: "satisfied", label: "Satisfied", count: buckets.satisfied.length },
    {
      id: "no_longer_applies",
      label: "No longer applies",
      count: buckets.no_longer_applies.length,
    },
    { id: "not_applicable", label: "Not applicable", count: buckets.not_applicable.length },
    { id: "legacy", label: "Old findings", count: legacyCount },
  ];

  return (
    <div className="space-y-4">
      {ruleFindingsStale && ruleFindings.length > 0 && (
        // LP-377-C: the latest run did not complete (still running, or failed/killed), so these governed
        // findings may be from an EARLIER run (carry-forward, LP-322). Say so — a processor must not read a
        // prior run's output as this run's. Worded around the RUN, not "the rule engine failed": a run can
        // fail on the sweep while the rule pass succeeded, so the findings can even be fresh.
        <div className="flex items-start gap-2 rounded-lg border border-warning/30 bg-warning/5 px-3 py-2.5 text-xs text-gray-600">
          <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" />
          <span>
            <span className="font-medium text-gray-700">
              These rule-engine findings may be out of date.
            </span>{" "}
            The latest verification run didn&rsquo;t complete, so the results below may be from an
            earlier run — re-run verification to refresh them.
          </span>
        </div>
      )}
      <TabStrip tabs={tabs} active={active} onPick={setActive} />

      <div role="tabpanel">
        {active === "attention" && <AttentionTab findings={buckets.attention} />}

        {active === "satisfied" &&
          (buckets.satisfied.length > 0 ? (
            <div className="space-y-2">
              <p className="text-xs text-gray-400">
                {OUTCOME_META.satisfied.blurb} These ran and passed — visible so you know a rule was
                actually checked, not silently skipped.
              </p>
              <FindingList findings={buckets.satisfied} />
            </div>
          ) : (
            <EmptyState
              icon={<CheckCircle2 className="h-8 w-8" />}
              title="No satisfied rules yet"
              body="When a rule runs and passes with evidence, it appears here — so a pass is visible, never assumed."
            />
          ))}

        {active === "no_longer_applies" &&
          (buckets.no_longer_applies.length > 0 ? (
            <FindingList findings={buckets.no_longer_applies} />
          ) : (
            <EmptyState
              icon={<History className="h-8 w-8" />}
              title="Nothing has stopped applying"
              body="A finding lands here when its subject leaves the file between runs (e.g. a deposit that's gone). It needs a prior run to compare against, so a first run never populates it. It is NOT the same as 'not applicable'."
            />
          ))}

        {active === "not_applicable" && (
          <EmptyState
            icon={<CircleSlash className="h-8 w-8" />}
            title="Nothing to show — and that's by design"
            body="Subjects a rule doesn't apply to (e.g. AS-1's money-OUT transactions) are not recorded as findings, so this tab is structurally empty on every file. It exists so that 'not applicable' can never quietly absorb a 'couldn't check' — a real gap always stays in Needs attention."
          />
        )}

        {active === "legacy" && (
          <div className="space-y-3">
            <div className="flex items-start gap-2 rounded-lg border border-gray-200 bg-gray-50 px-3 py-2.5 text-xs text-gray-500">
              <Archive className="mt-0.5 h-3.5 w-3.5 shrink-0 text-gray-400" />
              <span>
                <span className="font-medium text-gray-600">Legacy — two deprecated systems</span>{" "}
                (the AI cross-source sweep + retired rules). These are NOT the governed rule engine
                and are scheduled for removal; they carry their own counts and actions, separate
                from the tabs above.
              </span>
            </div>
            {legacy}
          </div>
        )}
      </div>
    </div>
  );
}
