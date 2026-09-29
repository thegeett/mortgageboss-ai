"use client";

import { Button } from "@/components/ui/button";
import { useApplyFigures, useFiguresCheck } from "@/lib/api/conditions";
import { getErrorMessage } from "@/lib/errors/api-error";
import type { FigureChange } from "@/lib/types/conditions";
import { ArrowRight, Check, CircleCheckBig, TriangleAlert } from "lucide-react";
import { useState } from "react";

/**
 * "Figures check" (S3-09, LP-924): what the file's accepted evidence changes, computed by code.
 *
 * NOTHING CHANGES UNTIL SHE APPLIES IT (README rule 6). The rail keeps the old ratios until then, and
 * applying sends back exactly the rows on screen — the server refuses if the file would now get
 * something else. "Not now" hides it for this view; it is recomputed the next time the tab opens.
 */
export function FiguresCheckPanel({ fileId }: { fileId: string }) {
  const check = useFiguresCheck(fileId);
  const apply = useApplyFigures(fileId);
  const [hidden, setHidden] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const data = check.data;
  if (!data || hidden || data.apply_count === 0) return null;
  const count = data.apply_count;
  const noun = `${count} change${count === 1 ? "" : "s"}`;
  return (
    <section className="flex flex-col gap-3 rounded-lg border border-primary/35 bg-card p-4">
      <div>
        <p className="text-xs font-semibold uppercase tracking-wide text-foreground-2">
          Figures check
        </p>
        <p className="mt-0.5 text-base font-semibold text-foreground">
          {noun} from accepted evidence
        </p>
        <p className="text-xs text-muted-foreground">
          Computed by code from the documents you accepted. Nothing changes in the file until you
          apply it.
        </p>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-foreground-2">
              <th className="py-2 pr-2 font-semibold">Figure</th>
              <th className="py-2 pr-2 font-semibold">In the file</th>
              <th className="w-6 py-2" aria-hidden />
              <th className="py-2 pr-2 font-semibold">From evidence</th>
              <th className="py-2 font-semibold">Source</th>
            </tr>
          </thead>
          <tbody>
            {data.changes.map((change) => (
              <Row key={change.key} change={change} />
            ))}
          </tbody>
        </table>
      </div>

      <div className="grid gap-2 md:grid-cols-2">
        {data.covers && Number(data.covers.verified) >= Number(data.covers.required) ? (
          <Callout tone="ok">
            <b className="font-semibold">Assets now cover closing.</b> {money(data.covers.verified)}{" "}
            verified against {money(data.covers.required)} required.
          </Callout>
        ) : data.covers ? (
          <Callout tone="warn">
            <b className="font-semibold">Assets still short.</b> {money(data.covers.verified)}{" "}
            verified against {money(data.covers.required)} required.
          </Callout>
        ) : null}
        {data.du_rerun ? (
          <Callout tone="warn">
            <b className="font-semibold">Re-run DU before submitting.</b>{" "}
            {sentence(data.du_reasons)} ({data.citation}).
          </Callout>
        ) : (
          <Callout tone="ok">
            <b className="font-semibold">DU re-run not needed.</b> DTI stays at or under 45% and
            rose less than 3 points ({data.citation}).
          </Callout>
        )}
      </div>
      {data.du_not_checked.length > 0 ? (
        <p className="text-xs text-muted-foreground">
          Not checked: {data.du_not_checked.join("; ")}.
        </p>
      ) : null}
      <p className="text-xs text-muted-foreground">
        If DTI went over 45%, or rose 3 points or more, this would say{" "}
        <b className="font-semibold text-foreground">“Re-run DU before submitting”</b> and the
        package would warn until you mark it done.
      </p>

      <div className="flex flex-wrap items-center gap-2">
        <Button
          type="button"
          disabled={apply.isPending}
          onClick={() =>
            apply.mutate(
              {
                // BOTH SIDES OF EACH ROW: a figure changed underneath is refused, not overwritten.
                changes: data.changes.map((c) => ({
                  key: c.key,
                  in_file: c.in_file,
                  from_evidence: c.from_evidence,
                })),
              },
              { onError: (error) => setNote(getErrorMessage(error)) },
            )
          }
        >
          <Check className="h-4 w-4" aria-hidden />
          Apply {noun} to the file’s figures
        </Button>
        <Button type="button" variant="outline" onClick={() => setHidden(true)}>
          Not now
        </Button>
        <span className="text-xs text-muted-foreground">
          Applies through the file’s stated assets and expenses, with the evidence linked.
        </span>
      </div>
      {note ? <p className="text-sm text-destructive">{note}</p> : null}
    </section>
  );
}

function Row({ change }: { change: FigureChange }) {
  const show = (value: string) => (change.unit === "money" ? money(value) : `${value}%`);
  return (
    <tr className="border-b border-border last:border-b-0">
      <td className="py-2 pr-2 text-foreground">{change.label}</td>
      <td className="py-2 pr-2 text-muted-foreground line-through">
        {change.in_file === null ? "—" : show(change.in_file)}
      </td>
      <td className="py-2 text-muted-foreground">
        <ArrowRight className="h-3.5 w-3.5" aria-hidden />
      </td>
      <td className="py-2 pr-2 font-semibold text-foreground">{show(change.from_evidence)}</td>
      <td className="py-2 text-xs text-foreground-2">{change.source}</td>
    </tr>
  );
}

function Callout({ tone, children }: { tone: "ok" | "warn"; children: React.ReactNode }) {
  const Icon = tone === "ok" ? CircleCheckBig : TriangleAlert;
  return (
    <p
      className={
        tone === "ok"
          ? "flex items-start gap-2 rounded-lg border border-success/40 bg-success/5 p-2.5 text-xs text-foreground-2"
          : "flex items-start gap-2 rounded-lg border border-warning/50 bg-warning/5 p-2.5 text-xs text-foreground-2"
      }
    >
      <Icon
        className={`mt-0.5 h-3.5 w-3.5 shrink-0 ${tone === "ok" ? "text-success" : "text-warning"}`}
        aria-hidden
      />
      <span>{children}</span>
    </p>
  );
}

function sentence(reasons: string[]): string {
  const text = reasons.join("; ");
  return text ? `${text.charAt(0).toUpperCase()}${text.slice(1)}.` : "";
}

/** `41914.42` → `$41,914.42`, on the string (no float). */
function money(value: string): string {
  const [whole = "0", cents = "00"] = value.split(".");
  return `$${whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",")}.${cents.padEnd(2, "0").slice(0, 2)}`;
}
