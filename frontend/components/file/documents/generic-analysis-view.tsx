import { humanize } from "@/lib/format";
import type { GenericAnalysis } from "@/lib/types/document";

/**
 * Tier 3 (long-tail) detail (LP-66/72) — the generic analyzer's flexible findings:
 * key parties, dates, amounts, and findings. The proportional-investment philosophy:
 * an unrecognized document gets a light, structured read rather than deep extraction.
 */
export function GenericAnalysisView({ analysis }: { analysis: GenericAnalysis }) {
  const parties = analysis.key_parties ?? [];
  const dates = analysis.key_dates ?? [];
  const amounts = analysis.key_amounts ?? [];
  const findings = analysis.key_findings ?? [];
  const empty =
    parties.length === 0 && dates.length === 0 && amounts.length === 0 && findings.length === 0;

  if (empty) {
    return (
      <p className="mt-3 rounded-lg border border-dashed border-gray-200 px-3 py-4 text-sm text-gray-400">
        No structured findings — see the summary above.
      </p>
    );
  }

  return (
    <div className="mt-3 space-y-4">
      {findings.length > 0 && (
        <Group label="Findings">
          <ul className="space-y-1.5">
            {findings.map((f) => (
              <li key={JSON.stringify(f)} className="text-sm text-gray-700">
                {f.finding_type && (
                  <span className="mr-1.5 rounded bg-info/10 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-info">
                    {humanize(f.finding_type)}
                  </span>
                )}
                {f.description ?? "—"}
                {f.amount != null && (
                  <span className="text-gray-500">
                    {" "}
                    · {String(f.amount)}
                    {f.frequency ? ` / ${f.frequency}` : ""}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </Group>
      )}

      {parties.length > 0 && (
        <Group label="Parties">
          <ul className="space-y-1">
            {parties.map((p) => (
              <KeyValue key={JSON.stringify(p)} k={p.name ?? "—"} v={p.role} />
            ))}
          </ul>
        </Group>
      )}

      {dates.length > 0 && (
        <Group label="Dates">
          <ul className="space-y-1">
            {dates.map((d) => (
              <KeyValue key={JSON.stringify(d)} k={d.date ?? "—"} v={d.description} />
            ))}
          </ul>
        </Group>
      )}

      {amounts.length > 0 && (
        <Group label="Amounts">
          <ul className="space-y-1">
            {amounts.map((a) => (
              <KeyValue
                key={JSON.stringify(a)}
                k={a.value != null ? String(a.value) : "—"}
                v={a.context}
              />
            ))}
          </ul>
        </Group>
      )}
    </div>
  );
}

function Group({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <section>
      <h4 className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-gray-400">
        {label}
      </h4>
      {children}
    </section>
  );
}

function KeyValue({ k, v }: { k: string; v: string | null }) {
  return (
    <li className="flex items-start justify-between gap-3 text-sm">
      <span className="font-medium text-gray-900">{k}</span>
      {v && <span className="max-w-[60%] text-right text-gray-500">{v}</span>}
    </li>
  );
}
