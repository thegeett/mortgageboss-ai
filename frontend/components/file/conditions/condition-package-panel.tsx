"use client";

import { Button } from "@/components/ui/button";
import {
  downloadConditionPackage,
  useBuildPackage,
  useConditionPackage,
  useMarkDuRerunDone,
  useSubmitPackage,
  useUpdatePackageRow,
} from "@/lib/api/conditions";
import { getErrorMessage } from "@/lib/errors/api-error";
import type { ConditionPackage, PackageRow } from "@/lib/types/conditions";
import { cn } from "@/lib/utils";
import { Clock, Copy, Download, Info, Package, Send, Sparkles, TriangleAlert } from "lucide-react";
import { useEffect, useState } from "react";

/** The portal each lender's upload happens in, for the Mark submitted line. */
const PORTAL: Record<string, string> = { UWM: "EASE" };

/**
 * "Package for UWM · round 1" (S3-10, LP-925), on the Conditions tab (README rule 9).
 *
 * NOTHING IS UPLOADED BY THE APP. She downloads the PDFs and notes, uploads them in the lender's
 * portal herself, then presses Mark submitted, which moves the ticked conditions to Sent to lender —
 * the one way our track moves — and keeps the package as the record of what was sent.
 */
export function ConditionPackagePanel({ fileId }: { fileId: string }) {
  const query = useConditionPackage(fileId);
  const build = useBuildPackage(fileId);
  const [note, setNote] = useState<string | null>(null);
  const data = query.data;
  if (!data) return null;
  if (data.status === null && data.ready_count === 0) return null;

  const title = `Package for ${data.lender_short}${data.round_number ? ` · round ${data.round_number}` : ""}`;

  if (data.status === "submitted") {
    return (
      <section className="flex items-center gap-2 rounded-lg border border-input bg-card px-4 py-3 text-sm">
        <Send className="h-4 w-4 text-primary" aria-hidden />
        <span className="font-medium">{title}</span>
        <span className="text-muted-foreground">
          · submitted {data.submitted_at ? stamp(data.submitted_at) : ""} ·{" "}
          {data.rows.filter((r) => r.included).length} sent to lender
        </span>
      </section>
    );
  }

  // LP-958 — THE LIST'S "NEXT" BANNER. The owner set every condition Ready and asked "what next?"
  // (2026-10-03): this panel was the answer, drawn as one more card among the cards. Now it says the
  // next step in a sentence, in the primary colour, above everything it is next for.
  if (data.status === null) {
    const n = data.ready_count;
    return (
      <section
        aria-label="Next"
        className="flex flex-wrap items-center gap-3 rounded-lg bg-primary px-4 py-3 text-primary-foreground"
      >
        <div className="flex min-w-0 flex-col gap-0.5">
          <p className="text-xs font-semibold uppercase tracking-wide opacity-80">Next · {title}</p>
          <p className="text-base font-medium">
            {n} condition{n === 1 ? " is" : "s are"} ready to send. Build the lender package and
            upload it to {data.lender_short}.
          </p>
        </div>
        <Button
          type="button"
          variant="outline"
          className="ml-auto border-transparent bg-background text-primary hover:bg-background/90"
          disabled={build.isPending}
          onClick={() => build.mutate(undefined, { onError: (e) => setNote(getErrorMessage(e)) })}
        >
          <Package className="h-4 w-4" aria-hidden />
          {build.isPending ? "Building…" : "Build lender package"}
        </Button>
        {note ? <p className="w-full text-sm">{note}</p> : null}
      </section>
    );
  }

  return <BuiltPackage fileId={fileId} data={data} title={title} />;
}

function BuiltPackage({
  fileId,
  data,
  title,
}: {
  fileId: string;
  data: ConditionPackage;
  title: string;
}) {
  const submit = useSubmitPackage(fileId);
  const duDone = useMarkDuRerunDone(fileId);
  const [confirming, setConfirming] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const included = data.rows.filter((r) => r.included);
  const pdfs = included.filter((r) => r.file_name).length;
  const pages = included.reduce((sum, r) => sum + r.pages, 0);
  const portal = PORTAL[data.lender_short] ?? "the lender's portal";

  return (
    <section className="flex flex-col gap-3 rounded-lg border border-primary/35 bg-card p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-foreground-2">{title}</p>
          <p className="mt-0.5 text-base font-semibold text-foreground">
            {included.length} condition{included.length === 1 ? "" : "s"} ready · {pages} pages
          </p>
          <p className="text-xs text-muted-foreground">
            One PDF per condition, named with the lender’s code, in sheet order. The note goes in{" "}
            {data.lender_short}’s comment for each condition.
          </p>
        </div>
        {data.cutoff ? (
          <CutoffChip lender={data.lender_short} cutoff={data.cutoff} tz={data.cutoff_tz} />
        ) : null}
      </div>

      {data.warnings.map((warning) => (
        <p
          key={`${warning.kind}-${warning.code}-${warning.text}`}
          className="flex items-start gap-2 rounded-md border border-warning/50 bg-warning/5 px-3 py-2 text-xs text-foreground-2"
        >
          <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" aria-hidden />
          {warning.kind === "open_prior_to_docs" ? (
            <span>
              <b className="font-semibold text-foreground">
                {warning.code} (prior to docs) is still open
              </b>{" "}
              — {warning.text}. Docs cannot be drawn until it clears.
            </span>
          ) : warning.kind === "du_rerun" ? (
            <span className="flex flex-wrap items-center gap-2">
              <b className="font-semibold text-foreground">Re-run DU before submitting.</b>{" "}
              {warning.text}
              <Button type="button" size="sm" variant="outline" onClick={() => duDone.mutate()}>
                Mark DU re-run done
              </Button>
            </span>
          ) : (
            <span>{warning.text}.</span>
          )}
        </p>
      ))}
      {data.later_codes.length > 0 ? (
        <p className="flex items-start gap-2 rounded-md border border-info/40 bg-info/5 px-3 py-2 text-xs text-foreground-2">
          <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-info" aria-hidden />
          Prior-to-funding items ({data.later_codes.join(", ")}) are not included — they go with the
          closing package.
        </p>
      ) : null}

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-foreground-2">
              <th className="w-8 py-2" aria-hidden />
              <th className="w-16 py-2 pr-2 font-semibold">Code</th>
              <th className="w-44 py-2 pr-2 font-semibold">File</th>
              <th className="w-14 py-2 pr-2 font-semibold">Pages</th>
              <th className="py-2 font-semibold">Note for the underwriter</th>
            </tr>
          </thead>
          <tbody>
            {data.rows.map((row) => (
              <Row key={row.condition_id} fileId={fileId} row={row} fields={data.upload_fields} />
            ))}
          </tbody>
        </table>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Button
          type="button"
          onClick={() =>
            void downloadConditionPackage(fileId, `${title} package.zip`).catch((e) =>
              setNote(getErrorMessage(e)),
            )
          }
        >
          <Download className="h-4 w-4" aria-hidden />
          Download package ({pdfs} PDF{pdfs === 1 ? "" : "s"} + notes)
        </Button>
        <Button
          type="button"
          variant="outline"
          onClick={() =>
            void navigator.clipboard
              .writeText(included.map((r) => `${r.code} — ${r.note}`).join("\n"))
              .then(() => setNote("Notes copied."))
              .catch(() => setNote("The copy was blocked — select the notes and copy them."))
          }
        >
          <Copy className="h-4 w-4" aria-hidden />
          Copy all notes
        </Button>
        {confirming ? (
          <span className="inline-flex items-center gap-2 text-sm">
            Move {included.length} to Sent to lender?
            <Button
              type="button"
              size="sm"
              disabled={submit.isPending}
              onClick={() =>
                submit.mutate(undefined, {
                  onError: (e) => setNote(getErrorMessage(e)),
                  onSettled: () => setConfirming(false),
                })
              }
            >
              Mark submitted
            </Button>
            <Button type="button" size="sm" variant="ghost" onClick={() => setConfirming(false)}>
              Not yet
            </Button>
          </span>
        ) : (
          <Button
            type="button"
            variant="outline"
            disabled={included.length === 0}
            onClick={() => setConfirming(true)}
          >
            <Send className="h-4 w-4" aria-hidden />
            Mark submitted
          </Button>
        )}
        <span className="text-xs text-muted-foreground">
          Mark submitted after you upload in {portal} — it moves these {included.length} to{" "}
          <b className="font-semibold text-foreground">Sent to lender</b>.
        </span>
      </div>
      {note ? <p className="text-xs text-muted-foreground">{note}</p> : null}
    </section>
  );
}

function Row({ fileId, row, fields }: { fileId: string; row: PackageRow; fields: string[] }) {
  const update = useUpdatePackageRow(fileId);
  const [text, setText] = useState(row.note);
  useEffect(() => setText(row.note), [row.note]);
  return (
    <tr className="border-b border-border align-top last:border-b-0">
      <td className="py-2.5">
        <input
          type="checkbox"
          className="accent-primary"
          aria-label={`Include ${row.code}`}
          checked={row.included}
          onChange={(event) =>
            update.mutate({ conditionId: row.condition_id, included: event.target.checked })
          }
        />
      </td>
      <td className="py-2.5 pr-2 font-mono text-sm font-medium">{row.code}</td>
      <td className="py-2.5 pr-2 font-mono text-xs">{row.file_name ?? "—"}</td>
      <td className="py-2.5 pr-2 tabular-nums">{row.file_name ? row.pages : "—"}</td>
      <td className="py-2.5">
        <textarea
          aria-label={`Note for ${row.code}`}
          value={text}
          rows={Math.min(3, Math.max(1, Math.ceil(text.length / 90)))}
          onChange={(event) => setText(event.target.value)}
          onBlur={() => {
            if (text.trim() && text !== row.note) {
              update.mutate({ conditionId: row.condition_id, note: text });
            }
          }}
          className="w-full resize-y rounded-md border border-input bg-background px-2.5 py-1.5 text-sm"
        />
        <NoteMark source={row.note_source} />
        {fields.includes("name_of_source") || fields.includes("date_verified") ? (
          <div className="mt-1 flex flex-wrap gap-2 text-xs text-foreground-2">
            {fields.includes("name_of_source") ? (
              <span>Name of source: {row.fields.name_of_source ?? "—"}</span>
            ) : null}
            {fields.includes("date_verified") ? (
              <span>Date verified: {row.fields.date_verified ?? "—"}</span>
            ) : null}
          </div>
        ) : null}
      </td>
    </tr>
  );
}

function NoteMark({ source }: { source: PackageRow["note_source"] }) {
  if (source === "ai") {
    return (
      <p className="mt-0.5 inline-flex items-center gap-1 text-xs text-ai">
        <Sparkles className="h-3 w-3" aria-hidden />
        drafted · numbers checked by code
      </p>
    );
  }
  return (
    <p className="mt-0.5 text-xs text-muted-foreground">
      {source === "edited" ? "edited by you" : "written by code"}
    </p>
  );
}

/** "UWM upload cutoff 8:00 PM ET · 2 h 14 m left", counted down with this browser's clock. */
function CutoffChip({ lender, cutoff, tz }: { lender: string; cutoff: string; tz: string | null }) {
  const zone = tz ?? "America/New_York";
  const left = minutesUntil(cutoff, zone, new Date());
  const [hour = "0", minute = "0"] = cutoff.split(":");
  const h = Number(hour);
  const label = `${h % 12 === 0 ? 12 : h % 12}:${minute} ${h < 12 ? "AM" : "PM"} ${zone === "America/New_York" ? "ET" : zone}`;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs",
        left !== null && left < 60
          ? "border-warning/50 text-warning"
          : "border-input text-foreground-2",
      )}
    >
      <Clock className="h-3.5 w-3.5" aria-hidden />
      {lender} upload cutoff {label} ·{" "}
      {left === null || left <= 0
        ? "passed for today"
        : `${Math.floor(left / 60)} h ${left % 60} m left`}
    </span>
  );
}

/** Minutes from `now` to today's cutoff in `zone`. Null if the zone cannot be read. */
export function minutesUntil(cutoff: string, zone: string, now: Date): number | null {
  try {
    const parts = new Intl.DateTimeFormat("en-US", {
      timeZone: zone,
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
    }).formatToParts(now);
    const hh = Number(parts.find((p) => p.type === "hour")?.value);
    const mm = Number(parts.find((p) => p.type === "minute")?.value);
    const [ch = "0", cm = "0"] = cutoff.split(":");
    return Number(ch) * 60 + Number(cm) - (hh * 60 + mm);
  } catch {
    return null;
  }
}

function stamp(iso: string): string {
  return new Date(iso).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZone: "America/New_York",
  });
}
