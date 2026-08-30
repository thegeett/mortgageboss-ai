"use client";

import { StatusToken, figureToneClass } from "@/components/status-token";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { useCalculator } from "@/lib/api/calculators";
import { useLoanFileDocuments } from "@/lib/api/documents";
import { useDti } from "@/lib/api/dti";
import { useLoanFile, useLoanFileActivity } from "@/lib/api/loan-files";
import { useLtv } from "@/lib/api/ltv";
import { useResolveFinding, useVerification } from "@/lib/api/verification";
import { formatMoney, humanize } from "@/lib/format";
import { documentCoverage, inFlightDocuments } from "@/lib/loan-files/documents";
import { fileTabSegment } from "@/lib/navigation";
import { EVALUATION_OUTCOME, LOAN_FILE_STATUS, type Tone, resolveStatus } from "@/lib/status";
import type { RuleFinding } from "@/lib/types/verification";
import { cn } from "@/lib/utils";
import {
  ATTENTION_ORDER,
  awaitedDocuments,
  bucketRuleFindings,
  splitByMissingDocument,
} from "@/lib/verification/rule-findings";
import { formatDistanceToNow } from "date-fns";
import { PanelRight } from "lucide-react";
import { usePathname } from "next/navigation";
import { useState } from "react";

/**
 * The 288px file context rail (LP-UI-009).
 *
 * Loan amount, DTI, LTV and reserves are the four numbers a processor switches
 * tabs to check. Pinning them beside the work surface is the point of the whole
 * rail: the tab switching mostly stops.
 *
 * It does NOT fetch anything of its own. Every hook here is one the file's tabs
 * already call with the same query key, so React Query serves both from one
 * request — the rail makes those numbers available on every tab rather than
 * only on the tab that happens to own them.
 *
 * Below `xl` the rail is `hidden`, which removes it from the tab order and the
 * accessibility tree as well as from view. A narrow screen loses the rail
 * rather than squeezing the work surface it exists to support.
 */

/**
 * A number the rail exists to keep on screen.
 *
 * `pending` is not decoration. Every value here falls back to an em dash, and an
 * em dash MEANS "this file has no such value" — using it for "not fetched yet"
 * tells a processor the file is missing a figure it actually has. The tabs show
 * skeletons while they load; the rail has to as well or it contradicts them.
 */
function Metric({
  label,
  value,
  hint,
  tone = "neutral",
  pending = false,
}: {
  label: string;
  value: string;
  hint?: string | null;
  /** The shared vocabulary, not a private three-value copy of it. */
  tone?: Tone;
  pending?: boolean;
}) {
  return (
    <div className="flex items-baseline justify-between gap-2 py-1">
      <span className="truncate text-xs text-muted-foreground">{label}</span>
      {pending ? (
        <Skeleton className="h-3 w-14" />
      ) : (
        <span className="flex items-baseline gap-1.5">
          <span className={cn("tabular text-sm font-medium", figureToneClass(tone))}>{value}</span>
          {hint ? <span className="text-xs text-muted-foreground">{hint}</span> : null}
        </span>
      )}
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="border-b border-border px-3 py-2.5 last:border-b-0">
      <h3 className="pb-1 text-label uppercase text-muted-foreground">{title}</h3>
      {children}
    </section>
  );
}

const DASH = "—";

export function FileContextRail({ fileId }: { fileId: string }) {
  return (
    // Hidden below `xl`, where `FileContextDrawer` carries the same body. The
    // two render `ContextSections` rather than each holding a copy — a rail and
    // a drawer showing different numbers for the same file is the failure this
    // epic has found three times in other places.
    <aside
      aria-label="File context"
      className="hidden w-ctx shrink-0 overflow-y-auto border-l border-border bg-card xl:block"
    >
      <ContextSections fileId={fileId} />
    </aside>
  );
}

/**
 * The same context, reachable below `xl` (LP-UI-037).
 *
 * The rail is `hidden xl:block`, which below 1280px meant the file's status, its
 * three ratios and its activity were not collapsed but GONE, with nothing to
 * open. A 13-inch laptop is 1280 logical pixels at its widest common setting and
 * less at any scaling above 100%, so this is the ordinary case rather than an
 * edge one.
 *
 * A drawer rather than a stacked section: these six numbers are reference
 * material a processor checks and dismisses, and stacking them above the work
 * surface would push the work down the page on exactly the screens with the
 * least room for it.
 */
export function FileContextDrawer({ fileId }: { fileId: string }) {
  const [open, setOpen] = useState(false);
  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild>
        <Button
          type="button"
          variant="outline"
          size="sm"
          // Mirrors the rail exactly: shown only where the rail is hidden, so the
          // context is reachable at every width and duplicated at none.
          className="gap-1.5 xl:hidden"
        >
          <PanelRight className="h-3.5 w-3.5" />
          File context
        </Button>
      </SheetTrigger>
      {/* The sheet already slides from the right and carries its own header
          border; only the width and the scrolling are ours. */}
      <SheetContent className="overflow-y-auto sm:max-w-[var(--ctx-w,22rem)]">
        <SheetHeader>
          <SheetTitle className="text-sm">File context</SheetTitle>
        </SheetHeader>
        <div className="min-h-0 flex-1 overflow-y-auto">
          <ContextSections fileId={fileId} />
        </div>
      </SheetContent>
    </Sheet>
  );
}

/**
 * The rail's contents, without the rail.
 *
 * Below `xl` the aside is hidden and this is what the drawer shows. Extracted so
 * there is ONE definition of what "file context" means — the alternative is two
 * lists that agree until one of them is edited.
 */
function ContextSections({ fileId }: { fileId: string }) {
  const pathname = usePathname();
  const { data: file, isPending: filePending } = useLoanFile(fileId);
  const { data: dti, isPending: dtiPending } = useDti(fileId);
  const { data: ltv, isPending: ltvPending } = useLtv(fileId);
  const { data: reserves, isPending: reservesPending } = useCalculator(fileId, "reserves");
  const { data: activity, isPending: activityPending } = useLoanFileActivity(fileId);

  // Tab-specific sections, anchored to the file's own base rather than matched
  // against the end of the whole path.
  const tab = fileTabSegment(pathname);

  return (
    <>
      <Section title="Status">
        <div className="py-1">
          {filePending ? (
            <Skeleton className="h-4 w-28" />
          ) : (
            // The DEFAULT `attention` fallback is deliberate here, unlike the
            // calculators. There the tone coloured a computed figure, so an
            // unrecognised status painted amber over a number with nothing wrong
            // with it. Here the tone colours the STATUS ITSELF: a loan-file
            // status this build does not know is a thing a processor should
            // look at, which is what amber says.
            <StatusToken meta={resolveStatus(LOAN_FILE_STATUS, file?.status)} variant="inline" />
          )}
        </div>
      </Section>

      <Section title="Loan">
        <Metric
          label="Amount"
          value={file?.loan_amount ? formatMoney(file.loan_amount) : DASH}
          pending={filePending}
        />
        <Metric
          label="Program"
          value={file?.loan_program ? humanize(file.loan_program) : DASH}
          pending={filePending}
        />
        <Metric
          label="Purpose"
          value={file?.loan_purpose ? humanize(file.loan_purpose) : DASH}
          pending={filePending}
        />
      </Section>

      <Section title="Ratios">
        <Metric
          label="Back-end DTI"
          // LP-375: a gated DTI has no ratio, and the engine nulls it rather
          // than fabricating a 0. The tile says "Gated"; an em dash here would
          // read as "this file has no DTI" instead of "a required input is
          // unknown", so the rail says the same word the tile does.
          value={dtiValue(dti?.gated, dti?.back_end_dti)}
          hint={dti?.limit.back_end_max ? `/ ${dti.limit.back_end_max}%` : null}
          tone={dtiTone(dti?.back_end_dti, dti?.limit.back_end_max)}
          pending={dtiPending}
        />
        <Metric
          label="Front-end DTI"
          value={dtiValue(dti?.gated, dti?.front_end_dti)}
          pending={dtiPending}
        />
        <Metric label="LTV" value={ltv?.ltv ? `${ltv.ltv}%` : DASH} pending={ltvPending} />
        <Metric label="Reserves" value={reserves?.headline ?? DASH} pending={reservesPending} />
      </Section>

      {tab === "documents" ? <DocumentsSection fileId={fileId} /> : null}
      {tab === "verification" ? <VerificationSection fileId={fileId} /> : null}

      <Section title="Recent activity">
        {activityPending ? (
          <div className="space-y-1.5 py-1">
            <Skeleton className="h-3 w-full" />
            <Skeleton className="h-3 w-2/3" />
          </div>
        ) : activity && activity.length > 0 ? (
          <ul className="space-y-1.5 py-1">
            {activity.slice(0, 5).map((entry) => (
              <li key={entry.id} className="text-xs leading-snug text-foreground-2">
                <span className="block truncate">{entry.summary}</span>
                <span className="text-muted-foreground">{when(entry.created_at)}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="py-1 text-xs text-muted-foreground">Nothing yet.</p>
        )}
      </Section>
    </>
  );
}

/**
 * Coverage, freshness and duplicates — only on the Documents tab, which has
 * already fetched the list these are derived from (LP-UI-019).
 *
 * Each of these was a per-row cue you noticed one document at a time: a badge on
 * a stale row, a "2 other pay stubs" line under a name. In the rail each is one
 * answer for the whole file, which is the difference between spotting a problem
 * and being able to act on it.
 */
function DocumentsSection({ fileId }: { fileId: string }) {
  const { data: documents } = useLoanFileDocuments(fileId);
  const all = documents ?? [];
  const processing = inFlightDocuments(all).length;
  const coverage = documentCoverage(all);

  return (
    <>
      <Section title="Coverage">
        <Metric
          label="Package-qualified"
          value={`${coverage.qualified} / ${coverage.total}`}
          tone={coverage.qualified === coverage.total ? "verified" : "neutral"}
        />
        {/* The backend checks four criteria in priority order and reports the
            FIRST one each document failed, so these are its words, not a second
            opinion formed here. */}
        {coverage.shortfalls.map((shortfall) => (
          <Metric
            key={shortfall.reason}
            label={shortfall.label}
            value={String(shortfall.count)}
            tone="attention"
          />
        ))}
        {processing > 0 ? <Metric label="Still processing" value={String(processing)} /> : null}
        <p className="pt-1 text-xs leading-snug text-muted-foreground">
          A document is package-qualified when it is current, fresh, typed and extracted.
        </p>
      </Section>

      <Section title="Freshness">
        {coverage.stale.length === 0 ? (
          <p className="py-1 text-xs text-muted-foreground">
            Nothing on this file has passed its window.
          </p>
        ) : (
          <ul className="space-y-1 py-1">
            {coverage.stale.map((doc) => (
              <li key={doc.id} className="text-xs leading-snug">
                <span className="block truncate text-foreground-2">
                  {doc.standard_name || doc.original_filename}
                </span>
                <span className="text-warning">{doc.staleness?.reason}</span>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title="Duplicates">
        {coverage.duplicated.length === 0 ? (
          <p className="py-1 text-xs text-muted-foreground">
            No two current documents share a type.
          </p>
        ) : (
          <ul className="space-y-1 py-1">
            {coverage.duplicated.map((group) => (
              <li key={group.type} className="text-xs leading-snug text-foreground-2">
                {group.documents.length} × {humanize(group.type)}
              </li>
            ))}
          </ul>
        )}
      </Section>
    </>
  );
}

/**
 * Run stats — only on the Verification tab, which already fetches these.
 *
 * THESE ARE THE GOVERNED OUTCOMES, and until LP-UI-020 they were not. The block
 * read `red_count` / `yellow_count` / `green_count` off the run, which
 * `lib/types/verification.ts` says are the LEGACY sweep's severity counts, and
 * printed them under the governed engine's words. On LF-96SV that rendered
 * "Must fix 0" beside a file the engine gives ten `open` violations, and
 * "Satisfied 0" against fourteen satisfied. A processor reading the rail was
 * told there was nothing to fix.
 *
 * Derived through `bucketRuleFindings` — the same function the tab strip buckets
 * with — so the rail and the tabs cannot drift. Reusing the predicate rather
 * than counting outcomes again here is the LP-UI-013 lesson: an aggregate must
 * reuse what its detail screen uses.
 *
 * The legacy sweep keeps its own line and its own word. It is never added to the
 * governed numbers (LP-375), and the two have genuinely different meanings.
 */
function VerificationSection({ fileId }: { fileId: string }) {
  const { data: verification } = useVerification(fileId);
  const run = verification?.latest_run ?? null;
  const ruleFindings = verification?.rule_findings ?? [];
  const buckets = bucketRuleFindings(ruleFindings);

  // `couldnt_check` is its own bucket as of LP-UI-020 — "we could not check
  // this" is a different job from "this is wrong", chased with a document
  // request rather than a correction. The rail reads the same buckets the tab
  // strip renders, so a routing change moves both together or neither.
  const couldntCheck = buckets.couldnt_check.length;
  const legacy = verification?.findings.length ?? 0;

  // Counted PER OUTCOME, never by subtraction. `attention` holds three outcomes
  // (`ATTENTION_ORDER`) and anything `tabForOutcome` cannot place, so
  // `attention.length - mustFix` labelled `pending_automation` — "Manual
  // review", a rule that could not be automated — as "Needs review", which
  // means a human disagreed with a result. Two different jobs, one number,
  // which is the lie this whole ticket set out to stop the rail telling.
  const byOutcome = new Map<string, number>();
  for (const finding of buckets.attention) {
    const key = finding.evaluation_outcome;
    byOutcome.set(key, (byOutcome.get(key) ?? 0) + 1);
  }
  const mustFix = byOutcome.get("open") ?? 0;
  // Whatever the fallback routed here from an enum this build does not know. It
  // is in the tab, so the rail must not quietly disagree about the total.
  const unrecognised =
    buckets.attention.length -
    ATTENTION_ORDER.reduce((sum, outcome) => sum + (byOutcome.get(outcome) ?? 0), 0);

  return (
    <Section title="Verification">
      <Metric
        label={EVALUATION_OUTCOME.open.label}
        value={verification ? String(mustFix) : DASH}
        tone={mustFix > 0 ? "blocking" : "neutral"}
      />
      <Metric
        label={EVALUATION_OUTCOME.couldnt_check.label}
        value={verification ? String(couldntCheck) : DASH}
        tone={couldntCheck > 0 ? "attention" : "neutral"}
      />
      {ATTENTION_ORDER.filter((outcome) => outcome !== "open").map((outcome) => {
        const count = byOutcome.get(outcome) ?? 0;
        return (
          <Metric
            key={outcome}
            label={EVALUATION_OUTCOME[outcome].label}
            value={verification ? String(count) : DASH}
            tone={count > 0 ? "attention" : "neutral"}
          />
        );
      })}
      {unrecognised > 0 ? (
        <Metric label="Other" value={String(unrecognised)} tone="attention" />
      ) : null}
      <Metric
        label={EVALUATION_OUTCOME.satisfied.label}
        value={verification ? String(buckets.satisfied.length) : DASH}
      />
      {/* Its own line, its own word, never added to the four above. */}
      <Metric label="Old findings" value={verification ? String(legacy) : DASH} />
      <Metric label="Last run" value={run?.completed_at ? when(run.completed_at) : DASH} />
      <AwaitingDocuments fileId={fileId} findings={buckets.couldnt_check} />
    </Section>
  );
}

/**
 * The documents the governed rules are waiting on, and one request for all of
 * them (LP-UI-020).
 *
 * Grouped BY DOCUMENT, not by finding: six rules blocked on a credit report is
 * one thing to ask the borrower for, and asking six times is how a borrower gets
 * six emails. `awaitedDocuments` deduplicates, so the count here is documents,
 * not findings.
 *
 * NOT the only way to fire this. The same action sits beside the list it
 * summarises inside the Couldn't check tab (LP-562), and it stays there: this
 * rail is `hidden xl:block`, so making it the sole home would put a primary
 * action out of reach below 1280px — the regression class LP-UI-016 was
 * overruled on. Both entry points dispatch the identical `request-docs-bulk`,
 * so there is one mechanism with two doors, not two mechanisms.
 */
function AwaitingDocuments({ fileId, findings }: { fileId: string; findings: RuleFinding[] }) {
  const resolve = useResolveFinding(fileId);
  const { missing } = splitByMissingDocument(findings);
  const documents = awaitedDocuments(missing);
  if (documents.length === 0) return null;

  // Fifteen document names run to six lines of prose in a 288px rail, which is
  // the opposite of "answerable in one action". Stacked and capped: the names a
  // processor can act on, then how many more the one request still covers.
  const SHOWN = 5;
  const rest = documents.length - SHOWN;

  return (
    <div className="pt-2">
      <p className="text-xs font-medium text-muted-foreground">Waiting on</p>
      <ul className="mt-1 space-y-0.5">
        {documents.slice(0, SHOWN).map((name) => (
          <li key={name} className="truncate text-xs text-foreground-2" title={name}>
            {name}
          </li>
        ))}
        {rest > 0 ? <li className="text-xs text-muted-foreground">and {rest} more</li> : null}
      </ul>
      <Button
        size="sm"
        variant="outline"
        className="mt-2 h-7 w-full text-xs"
        disabled={resolve.isPending}
        onClick={() =>
          resolve.mutate({
            kind: "request-docs-bulk",
            findingIds: missing.map((finding) => finding.id),
          })
        }
      >
        Request all {documents.length}
      </Button>
    </div>
  );
}

/** A ratio, or the word for why there isn't one. */
function dtiValue(gated: boolean | undefined, ratio: string | null | undefined): string {
  if (gated) return "Gated";
  return ratio ? `${ratio}%` : DASH;
}

/** DTI against its own limit — the one ratio with a published ceiling. */
function dtiTone(
  value: string | null | undefined,
  max: string | null | undefined,
): "blocking" | "neutral" {
  if (!value || !max) return "neutral";
  const ratio = Number(value);
  const limit = Number(max);
  if (!Number.isFinite(ratio) || !Number.isFinite(limit)) return "neutral";
  return ratio > limit ? "blocking" : "neutral";
}

function when(iso: string): string {
  try {
    return formatDistanceToNow(new Date(iso), { addSuffix: true });
  } catch {
    return DASH;
  }
}
