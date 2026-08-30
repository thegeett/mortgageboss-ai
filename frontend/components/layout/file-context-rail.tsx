"use client";

import { StatusToken } from "@/components/status-token";
import { useCalculator } from "@/lib/api/calculators";
import { useLoanFileDocuments } from "@/lib/api/documents";
import { useDti } from "@/lib/api/dti";
import { useLoanFile, useLoanFileActivity } from "@/lib/api/loan-files";
import { useLtv } from "@/lib/api/ltv";
import { useVerification } from "@/lib/api/verification";
import { formatMoney, humanize } from "@/lib/format";
import { isTerminalStatus } from "@/lib/loan-files/documents";
import { LOAN_FILE_STATUS, resolveStatus } from "@/lib/status";
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

/** A number the rail exists to keep on screen. */
function Metric({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: string;
  hint?: string | null;
  tone?: "blocking" | "attention" | "neutral";
}) {
  return (
    <div className="flex items-baseline justify-between gap-2 py-1">
      <span className="truncate text-xs text-muted-foreground">{label}</span>
      <span className="flex items-baseline gap-1.5">
        <span
          className={cn(
            "tabular text-sm font-medium",
            tone === "blocking" && "text-destructive",
            tone === "attention" && "text-warning",
            (tone === "neutral" || tone === undefined) && "text-foreground",
          )}
        >
          {value}
        </span>
        {hint ? <span className="text-xs text-muted-foreground">{hint}</span> : null}
      </span>
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
  const { data: file } = useLoanFile(fileId);
  const { data: dti } = useDti(fileId);
  const { data: ltv } = useLtv(fileId);
  const { data: reserves } = useCalculator(fileId, "reserves");
  const { data: activity } = useLoanFileActivity(fileId);

  // Tab-specific sections. These hooks are only mounted on the tab that already
  // owns the query, so the rail never introduces a request the page was not
  // already making.
  const onDocuments = pathname.endsWith("/documents");
  const onVerification = pathname.endsWith("/verification");

  return (
    <aside
      aria-label="File context"
      className="hidden w-ctx shrink-0 overflow-y-auto border-l border-border bg-card xl:block"
    >
      <Section title="Status">
        <div className="py-1">
          <StatusToken meta={resolveStatus(LOAN_FILE_STATUS, file?.status)} variant="inline" />
        </div>
      </Section>

      <Section title="Loan">
        <Metric label="Amount" value={file?.loan_amount ? formatMoney(file.loan_amount) : DASH} />
        <Metric label="Program" value={file?.loan_program ? humanize(file.loan_program) : DASH} />
        <Metric label="Purpose" value={file?.loan_purpose ? humanize(file.loan_purpose) : DASH} />
      </Section>

      <Section title="Ratios">
        <Metric
          label="Back-end DTI"
          value={dti?.back_end_dti ? `${dti.back_end_dti}%` : DASH}
          hint={dti?.limit.back_end_max ? `/ ${dti.limit.back_end_max}%` : null}
          tone={dtiTone(dti?.back_end_dti, dti?.limit.back_end_max)}
        />
        <Metric label="Front-end DTI" value={dti?.front_end_dti ? `${dti.front_end_dti}%` : DASH} />
        <Metric label="LTV" value={ltv?.ltv ? `${ltv.ltv}%` : DASH} />
        <Metric label="Reserves" value={reserves?.headline ?? DASH} />
      </Section>

      {onDocuments ? <DocumentsSection fileId={fileId} /> : null}
      {onVerification ? <VerificationSection fileId={fileId} /> : null}

      <Section title="Recent activity">
        {activity && activity.length > 0 ? (
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

/** Coverage and freshness — only on the Documents tab, which already fetches these. */
function DocumentsSection({ fileId }: { fileId: string }) {
  const { data: documents } = useLoanFileDocuments(fileId);
  const all = documents ?? [];
  const settled = all.filter((doc) => isTerminalStatus(doc.status)).length;
  const stale = all.filter((doc) => doc.staleness?.is_stale && !doc.staleness.resolution).length;

  return (
    <Section title="Documents">
      <Metric label="In the file" value={String(all.length)} />
      <Metric label="Processed" value={`${settled} / ${all.length}`} />
      <Metric
        label="May be stale"
        value={String(stale)}
        tone={stale > 0 ? "attention" : "neutral"}
      />
    </Section>
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
