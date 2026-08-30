"use client";

import { StatusToken, figureToneClass } from "@/components/status-token";
import { Skeleton } from "@/components/ui/skeleton";
import { useCalculator } from "@/lib/api/calculators";
import { useLoanFileDocuments } from "@/lib/api/documents";
import { useDti } from "@/lib/api/dti";
import { useLoanFile, useLoanFileActivity } from "@/lib/api/loan-files";
import { useLtv } from "@/lib/api/ltv";
import { useVerification } from "@/lib/api/verification";
import { formatMoney, humanize } from "@/lib/format";
import { documentCoverage, isTerminalStatus } from "@/lib/loan-files/documents";
import { fileTabSegment } from "@/lib/navigation";
import { LOAN_FILE_STATUS, type Tone, resolveStatus } from "@/lib/status";
import { cn } from "@/lib/utils";
import { formatDistanceToNow } from "date-fns";
import { usePathname } from "next/navigation";

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
    <aside
      aria-label="File context"
      className="hidden w-ctx shrink-0 overflow-y-auto border-l border-border bg-card xl:block"
    >
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
    </aside>
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
  const processing = all.filter((doc) => !isTerminalStatus(doc.status)).length;
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

/** Run stats — only on the Verification tab, which already fetches these. */
function VerificationSection({ fileId }: { fileId: string }) {
  const { data: verification } = useVerification(fileId);
  const run = verification?.latest_run ?? null;

  return (
    <Section title="Verification">
      <Metric
        label="Must fix"
        value={run ? String(run.red_count) : DASH}
        tone={run && run.red_count > 0 ? "blocking" : "neutral"}
      />
      <Metric
        label="Needs attention"
        value={run ? String(run.yellow_count) : DASH}
        tone={run && run.yellow_count > 0 ? "attention" : "neutral"}
      />
      <Metric label="Satisfied" value={run ? String(run.green_count) : DASH} />
      <Metric label="Last run" value={run?.completed_at ? when(run.completed_at) : DASH} />
    </Section>
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
