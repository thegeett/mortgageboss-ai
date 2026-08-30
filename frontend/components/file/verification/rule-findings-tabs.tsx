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

import { Button } from "@/components/ui/button";
import { useDragScroll } from "@/hooks/use-drag-scroll";
import { humanize } from "@/lib/format";
import type { EvaluationOutcome, RuleFinding } from "@/lib/types/verification";
import { cn } from "@/lib/utils";
import {
  OUTCOME_META,
  type OutcomeTone,
  type TabId,
  attentionGroups,
  awaitedDocuments,
  bucketRuleFindings,
  groupByRule,
  outcomeMeta,
  splitByMissingDocument,
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
import type { RuleFindingAction } from "./rule-finding-actions";
import { RuleFindingRow, RuleLabel } from "./rule-finding-row";
import { SnapshotFindingsTab } from "./snapshot-findings-tab";

interface TabDef {
  id: TabId;
  label: string;
  count: number;
  /** Count-badge emphasis: "danger" = a violation (`open`), "warning" = a blocking gap (`couldnt_check`).
   *  A gap must not read as fine at a glance (the honesty contract) — hence a distinct warning tone. */
  tone?: "danger" | "warning";
  /** LP-583 — is this tab something a processor ACTS on, or an audit trail they occasionally consult?
   *
   *  On a real file the counts read: attention 26, satisfied 34, no-longer-applies 113. Every one
   *  rendered in an identical pill, so THE LARGEST NUMBER ON THE PAGE WAS THE LEAST USEFUL FACT —
   *  "subjects that left the file since a previous run". An archive should be REACHABLE, not
   *  advertised, so its count is shown only while the tab is open. */
  archival?: boolean;
  /** Keep the tab even at zero — for one whose CONTENT is an explanation rather than a list.
   *  Independent of the count badge, which is suppressed at zero for every tab. */
  alwaysShow?: boolean;
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
  const drag = useDragScroll<HTMLDivElement>();

  return (
    <div
      ref={drag.ref}
      role="tablist"
      aria-label="Verification outcomes"
      className={cn("flex gap-1 overflow-x-auto border-b border-gray-200", drag.className)}
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
            {/* LP-583 — an archival tab shows its count only while open. Competing for attention is
                the badge's whole function, and these have nothing to compete for. */}
            {/* Two separate concerns: `alwaysShow` decides whether the TAB exists, this decides
                whether its COUNT is worth showing. No tab benefits from displaying a zero — the
                empty state inside says it better — and an archival count shows only while open. */}
            {tab.count > 0 && (!tab.archival || isActive) && (
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
            )}
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
function AttentionTab({
  findings,
  onAct,
  fileId,
}: {
  findings: RuleFinding[];
  onAct?: (action: RuleFindingAction) => void;
  /** LP-577 — threaded to the row so Apply opens its before/after preview. */
  fileId?: string;
}) {
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
        <OutcomeGroup
          key={outcome}
          outcome={outcome}
          findings={groupFindings}
          onAct={onAct}
          fileId={fileId}
        />
      ))}
    </div>
  );
}

function OutcomeGroup({
  outcome,
  findings,
  onAct,
  fileId,
}: {
  outcome: EvaluationOutcome;
  findings: RuleFinding[];
  onAct?: (action: RuleFindingAction) => void;
  /** LP-577 — threaded to the row so Apply opens its before/after preview. */
  fileId?: string;
}) {
  const meta = outcomeMeta(outcome);
  // LP-583 — THE MUST-FIX GROUP CARRIES WEIGHT, NOT JUST POSITION. On a real file the three groups
  // read 1 / 15 / 10, and the single thing that genuinely has to be fixed rendered in the same gray
  // as fifteen missing-document notes. It was already ordered first, and ordering alone does not
  // survive a processor scanning quickly — so it gets a left rule, a tinted panel and a darker
  // heading. Deliberately the ONLY emphasised group: if all three shouted, none would.
  const isViolation = outcome === "open";
  return (
    <section
      className={cn(
        "space-y-2",
        isViolation && "rounded-md border-l-2 border-destructive bg-destructive/[0.03] py-2 pl-3",
      )}
    >
      <div className="flex items-baseline gap-2">
        <h4
          className={cn(
            "text-sm font-semibold",
            isViolation ? "text-destructive" : "text-gray-800",
          )}
        >
          {meta.label}
        </h4>
        <span
          className={cn(
            "text-xs tabular-nums",
            isViolation ? "font-semibold text-destructive" : "text-gray-400",
          )}
        >
          {findings.length}
        </span>
        <span className="text-xs text-gray-400">— {meta.blurb}</span>
      </div>
      {outcome === "couldnt_check" ? (
        <MissingVsPresent findings={findings} onAct={onAct} fileId={fileId} />
      ) : (
        <GroupedFindingList findings={findings} onAct={onAct} fileId={fileId} />
      )}
    </section>
  );
}

/**
 * LP-541 — inside Couldn't check, separate the documents to GO AND GET from the ones to GO AND READ.
 *
 * Only this bucket is split. A violation or a ratification is already one kind of job; a couldnt_check
 * is two wearing the same clothes, and on a real file the split was 6 to request against 5 to read.
 *
 * The sub-headers name the documents rather than counting them, because "Waiting on: credit report,
 * appraisal, rate lock agreement, VOE, title commitment" is a request a processor can send in one go,
 * where five separate cards are five separate errands. Rendered only when BOTH sides are non-empty —
 * a single header over the whole bucket adds a level of nesting and says nothing.
 */
function MissingVsPresent({
  findings,
  onAct,
  fileId,
}: {
  findings: RuleFinding[];
  onAct?: (action: RuleFindingAction) => void;
  /** LP-577 — threaded to the row so Apply opens its before/after preview. */
  fileId?: string;
}) {
  const { missing, present } = splitByMissingDocument(findings);
  // LP-564 — gated on `missing` ALONE. Requiring both sides made the button vanish in exactly the
  // case it exists for: a file where every couldnt_check finding is waiting on a document has an
  // empty `present`, which is the maximum-saving case, not the one to skip.
  if (missing.length === 0) {
    return <GroupedFindingList findings={findings} onAct={onAct} fileId={fileId} />;
  }
  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
          <p className="text-xs font-medium text-gray-500">
            Not in the file — request these ({missing.length})
            <span className="ml-1 font-normal text-gray-400">
              waiting on {awaitedDocuments(missing).join(", ")}
            </span>
          </p>
          {/* LP-562 — the list IS the request. Nine cards and five typed asks become one click, and
              the request is deduplicated per DOCUMENT so the borrower is never asked twice for the
              same thing. This is the single biggest saving available on the tab, and the data for it
              was already on screen. */}
          {onAct !== undefined && (
            <Button
              size="sm"
              className="h-6 px-2 text-[11px]"
              onClick={() =>
                onAct({
                  kind: "request-docs-bulk",
                  findingIds: missing.map((finding) => finding.id),
                })
              }
            >
              Request all {awaitedDocuments(missing).length}
            </Button>
          )}
        </div>
        <GroupedFindingList findings={missing} onAct={onAct} fileId={fileId} />
      </div>
      {/* An empty read-side is now reachable (see the gate above) and must not print a header over
          nothing. The request side is what the split exists for; this half is the remainder. */}
      {present.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs font-medium text-gray-500">
            In the file — read or clarify these ({present.length})
          </p>
          <GroupedFindingList findings={present} onAct={onAct} fileId={fileId} />
        </div>
      )}
    </div>
  );
}

/** LP-376-C: render findings that share a rule + reason as ONE summary row (expandable to WHICH ones), so
 * N documents failing a check the same way don't read as N identical lines. A lone finding renders plainly.
 * A pure display collapse — the underlying findings (and their reconcile keys) are untouched. */
function GroupedFindingList({
  findings,
  onAct,
  fileId,
}: {
  findings: RuleFinding[];
  onAct?: (action: RuleFindingAction) => void;
  /** LP-577 — threaded to the row so Apply opens its before/after preview. */
  fileId?: string;
}) {
  return (
    <div className="space-y-2">
      {groupByRule(findings).map((group) => {
        const first = group[0];
        if (first === undefined) return null; // never — groups are non-empty by construction
        return group.length === 1 ? (
          <RuleFindingRow key={first.id} finding={first} onAct={onAct} fileId={fileId} />
        ) : (
          <CollapsedFindings key={first.id} findings={group} onAct={onAct} fileId={fileId} />
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
 * The one-line gist of a finding: its ACTION sentence (LP-522).
 *
 * A guidance message is "Action.\n\nWhy…", so the action is the part before the blank line. Falls back
 * to the first sentence for a rule that has not adopted guidance yet, and to the whole message when it
 * is a single short one — every judgment rule except AS-12 is still in that state, so the fallback is
 * the common path today, not an edge case.
 */
function actionLine(message: string): string {
  const [head] = message.split("\n\n");
  const text = (head ?? message).trim();
  const stop = text.indexOf(". ");
  return stop === -1 ? text : text.slice(0, stop + 1);
}

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

function CollapsedFindings({
  findings,
  onAct,
  fileId,
}: {
  findings: RuleFinding[];
  onAct?: (action: RuleFindingAction) => void;
  /** LP-577 — threaded to the row so Apply opens its before/after preview. */
  fileId?: string;
}) {
  const first = findings[0];
  // A VIOLATION group starts EXPANDED. LP-518 widened grouping from rule+message to rule alone, which
  // also swept up `open` findings whose messages genuinely differ per subject — collapsing those hid the
  // violation text and its how_to_fix behind a click, which is not the noise this set out to remove.
  // Grouping still applies (one card per rule, as asked); only the default disclosure state differs.
  const [open, setOpen] = useState(first?.evaluation_outcome === "open");
  const panelId = useId();
  if (first === undefined) return null; // never — the caller only builds this for a non-empty group
  const dot = TONE_DOT[outcomeMeta(first.evaluation_outcome).tone];
  // Computed once and used by the header AND the bullets — two independent 'do they agree?' checks
  // would eventually disagree, and the bullets exist precisely to complement whatever the header says.
  const shared = findings.every((f) => f.message === first.message);
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
            <RuleLabel finding={first} />
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
      {/* LP-522 — every member VISIBLE WITHOUT EXPANDING, one line each, scrolling if long.
       *
       * This only became worth doing once the message led with the ACTION: a bullet reading "Document
       * the source of the $2,000.00 deposit on 3/3" tells a processor what the item is, where the same
       * bullet reading "the AI judged that…" would have been five identical non-sentences. Expanding
       * still gives the full row; this is the at-a-glance pass over a rule's whole set.
       *
       * Bounded height because a rule's set is not: AS-2 carries 57 findings on one real file. */}
      {!open && (
        <ul className="max-h-56 space-y-1 overflow-y-auto border-t border-gray-100 px-3 py-2">
          {findings.map((finding) => (
            <li key={finding.id} className="flex gap-2 text-xs leading-relaxed">
              <span className="mt-1 h-1 w-1 shrink-0 rounded-full bg-gray-300" aria-hidden />
              <span className="min-w-0">
                {finding.subject_label.length > 0 && (
                  <span className="font-medium text-gray-700">{finding.subject_label}</span>
                )}
                {/* When every member says the SAME thing the header already carries that sentence, so
                 * repeating it per bullet rebuilds the exact noise LP-376-C removed — four identical
                 * lines under a summary that exists to replace them. Subjects only, in that case. */}
                {!shared && (
                  <span className="text-gray-500">
                    {finding.subject_label.length > 0 && " — "}
                    {actionLine(finding.message)}
                  </span>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}

      {open && (
        <div id={panelId} className="space-y-2 border-t border-gray-100 bg-gray-50/40 px-3 py-3">
          {/* bug-001 — `onAct` WAS ACCEPTED HERE AND DROPPED. RuleFindingRow gates its whole action
              bar on `onAct !== undefined`, so every finding inside a grouped rule rendered with no
              buttons: a rule with ONE finding was actionable and the same rule with two was not.
              On a real file that was 32 of 48 findings — AS-1's fifteen deposits, AS-12's nine,
              FR-5's four, CR-6's four — visible, expandable, and impossible to act on. */}
          {findings.map((finding) => (
            <RuleFindingRow key={finding.id} finding={finding} onAct={onAct} fileId={fileId} />
          ))}
        </div>
      )}
    </div>
  );
}

function FindingList({
  findings,
  onAct,
  fileId,
}: {
  findings: RuleFinding[];
  onAct?: (action: RuleFindingAction) => void;
  /** LP-577 — threaded to the row so Apply opens its before/after preview. */
  fileId?: string;
}) {
  // Also collapsed by reason (LP-376-C) — e.g. AS-1's 15 identical "deposit sourced" satisfied rows.
  return <GroupedFindingList findings={findings} onAct={onAct} fileId={fileId} />;
}

export function RuleFindingsTabs({
  ruleFindings,
  ruleFindingsStale = false,
  legacyCount,
  legacy,
  onAct,
  fileId,
  crossSourceCount = 0,
}: {
  ruleFindings: RuleFinding[];
  /** LP-377-C: the latest run's rule engine did not complete — these findings are from an earlier run. */
  ruleFindingsStale?: boolean;
  legacyCount: number;
  legacy: ReactNode;
  /** LP-577 — threaded through to the Apply preview. Optional: without it Apply still works, it
   *  just skips the before/after dialog rather than the button vanishing. */
  fileId?: string;
  /** LP-589 — open cross-source findings. Owned by the panel (which already holds that query) so
   *  the badge reports a real number rather than a placeholder nobody can act on. */
  crossSourceCount?: number;
  /** LP-561 — resolve a governed finding. Optional so a read-only caller (a test, a print view) can
   *  render the tabs without the action bar appearing at all. */
  onAct?: (action: RuleFindingAction) => void;
}) {
  const [active, setActive] = useState<TabId>("attention");
  const buckets = bucketRuleFindings(ruleFindings);
  const openCount = buckets.attention.filter((f) => f.evaluation_outcome === "open").length;
  const couldntCheckCount = buckets.attention.filter(
    (f) => f.evaluation_outcome === "couldnt_check",
  ).length;

  const allTabs: TabDef[] = [
    {
      id: "attention",
      label: "Needs attention",
      count: buckets.attention.length,
      // A violation reds the badge; a blocking gap (couldnt_check, no open) warns it — never neutral, so
      // a file that only "couldn't check" doesn't read as fine at the tab-strip glance (honesty contract).
      tone: openCount > 0 ? "danger" : couldntCheckCount > 0 ? "warning" : undefined,
    },
    { id: "satisfied", label: "Satisfied", count: buckets.satisfied.length },
    // Archival: real, worth keeping, and not what anyone opens the page to do.
    {
      id: "no_longer_applies",
      label: "No longer applies",
      count: buckets.no_longer_applies.length,
      archival: true,
    },
    // NOT hidden when empty. Today `not_applicable` subjects are never persisted as findings, so
    // this tab is an EXPLANATION of an absence rather than a list — dropping it would delete an
    // honest §8 statement rather than remove noise.
    //
    // It is slated to carry real content later, so it reads its REAL count. LP-585 claimed that
    // alone made it future-proof and it did not: the outcome was absent from the union, so
    // `tabForOutcome` would have routed it to NEEDS ATTENTION via the fallback, and the body
    // rendered the empty state unconditionally. LP-588 wired the routing and branched the body, so
    // the count, the routing and the panel now agree.
    {
      id: "not_applicable",
      label: "Not applicable",
      count: buckets.not_applicable.length,
      archival: true,
      alwaysShow: true,
    },
    // LP-589 — the count is PASSED IN, not hardcoded. It shipped as `count: 0`, which the badge gate
    // (`count > 0 && …`) turns into "never show a number" — so a file with five unreconciled
    // pairings looked identical to one with none and nobody had a reason to click. That is exactly
    // the failure recorded four lines above for `not_applicable`, reintroduced immediately below it.
    //
    // `alwaysShow` because an empty list is a real answer ("the last run reconciled everything"),
    // not an absence worth hiding. Not archival: unlike "no longer applies", these are open work.
    {
      id: "cross_source",
      // LP-593 — "Cross-source" named the METHOD (comparing across sources), which is our word.
      // "Cross-check" is ordinary English a processor already uses and says what the tab contains.
      label: "Cross-checks",
      count: crossSourceCount,
      alwaysShow: true,
    },
    // LP-588 — NOT archival, and marking it so was a real regression. LP-583's rationale was that a
    // 113-count of "no longer applies" is noise; this tab is not that. `legacyCount` is
    // `data.findings.length` and that list still carries OPEN, blocking findings with the full
    // action set — and the Blocking/Warnings/Resolved tiles render INSIDE this tab's body, so
    // hiding its count left a file with unresolved blocking work showing no number and no stats
    // anywhere in the default view.
    { id: "legacy", label: "Old findings", count: legacyCount },
    // LP-583 — AN EMPTY CATEGORY IS NOT A CATEGORY ON THIS FILE. "Not applicable 0" spent real
    // estate telling a processor that nothing exists. `attention` is kept unconditionally: an empty
    // one is the answer they came for, and its own empty state says so.
  ];
  const tabs = allTabs.filter((tab) => tab.alwaysShow || tab.id === "attention" || tab.count > 0);
  // LP-588 — RECONCILE THE SELECTION WITH WHAT SURVIVED THE FILTER. `active` is plain state and the
  // panel POLLS every 2s while a run is in flight, so the findings are replaced under a processor:
  // sitting on "Satisfied" when a re-run empties that bucket, the tab disappears from the strip
  // while `active` still names it. Every body guard is `active === …`, so the panel kept rendering a
  // tab that no longer existed, nothing carried aria-selected, and the content shown was an empty
  // state that is otherwise unreachable. Falling back is one line; noticing it needed a re-run to
  // land while someone was reading.
  const shown = tabs.some((tab) => tab.id === active) ? active : "attention";

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
      <TabStrip tabs={tabs} active={shown} onPick={setActive} />

      <div role="tabpanel">
        {shown === "attention" && (
          <AttentionTab findings={buckets.attention} onAct={onAct} fileId={fileId} />
        )}

        {shown === "satisfied" &&
          (buckets.satisfied.length > 0 ? (
            <div className="space-y-2">
              <p className="text-xs text-gray-400">
                {OUTCOME_META.satisfied.blurb} These ran and passed — visible so you know a rule was
                actually checked, not silently skipped.
              </p>
              <FindingList findings={buckets.satisfied} onAct={onAct} fileId={fileId} />
            </div>
          ) : (
            <EmptyState
              icon={<CheckCircle2 className="h-8 w-8" />}
              title="No satisfied rules yet"
              body="When a rule runs and passes with evidence, it appears here — so a pass is visible, never assumed."
            />
          ))}

        {shown === "no_longer_applies" &&
          (buckets.no_longer_applies.length > 0 ? (
            <FindingList findings={buckets.no_longer_applies} onAct={onAct} fileId={fileId} />
          ) : (
            <EmptyState
              icon={<History className="h-8 w-8" />}
              title="Nothing has stopped applying"
              body="A finding lands here when its subject leaves the file between runs (e.g. a deposit that's gone). It needs a prior run to compare against, so a first run never populates it. It is NOT the same as 'not applicable'."
            />
          ))}

        {/* LP-588 — branch on the bucket rather than rendering the explanation unconditionally.
            The count is read from the real bucket (LP-585), so an unconditional empty state would
            have let the badge and the body contradict each other the day one is populated. */}
        {shown === "not_applicable" && buckets.not_applicable.length > 0 && (
          <FindingList findings={buckets.not_applicable} onAct={onAct} fileId={fileId} />
        )}

        {shown === "not_applicable" && buckets.not_applicable.length === 0 && (
          <EmptyState
            icon={<CircleSlash className="h-8 w-8" />}
            title="Nothing to show — and that's by design"
            body="Subjects a rule doesn't apply to (e.g. AS-1's money-OUT transactions) are not recorded as findings, so this tab is structurally empty on every file. It exists so that 'not applicable' can never quietly absorb a 'couldn't check' — a real gap always stays in Needs attention."
          />
        )}

        {shown === "cross_source" && fileId && <SnapshotFindingsTab fileId={fileId} />}

        {shown === "legacy" && (
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
