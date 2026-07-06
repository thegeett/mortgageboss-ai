"use client";

/**
 * The calculators section (LP-88) — all SIX calculators with PROGRESSIVE DISCLOSURE.
 *
 * Six calculators (DTI, LTV [LP-76/77] + MI, self-employed, reserves, max-loan [LP-87])
 * can't all be expanded without overwhelming the tab. So this shows a scannable STRIP of
 * six summary tiles (title + headline + a status dot — the at-a-glance picture) and expands
 * exactly ONE into its full transparent/overrideable calculator on click. The summary hooks
 * share the query cache with the full components, so expanding doesn't refetch.
 */

import { CalculatorCard } from "@/components/file/calculators/calculator-card";
import { DtiCalculator } from "@/components/file/dti/dti-calculator";
import { LtvCalculator } from "@/components/file/ltv/ltv-calculator";
import { useCalculator } from "@/lib/api/calculators";
import { useDti } from "@/lib/api/dti";
import { useLtv } from "@/lib/api/ltv";
import type { CalculatorName } from "@/lib/types/calculators";
import { cn } from "@/lib/utils";
import { Calculator, ChevronDown } from "lucide-react";
import { useState } from "react";

type CalcKey = "dti" | "ltv" | CalculatorName;

const STATUS_DOT: Record<string, string> = {
  over: "bg-destructive",
  insufficient: "bg-destructive",
  pass: "bg-success",
  sufficient: "bg-success",
  required: "bg-warning",
  declining: "bg-warning",
};

function dot(status: string | null | undefined): string {
  return (status && STATUS_DOT[status]) || "bg-gray-300";
}

function Tile({
  title,
  headline,
  status,
  expanded,
  onToggle,
}: {
  title: string;
  headline: string;
  status: string | null | undefined;
  expanded: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-expanded={expanded}
      className={cn(
        "flex w-full items-center justify-between gap-2 rounded-lg border px-3 py-2 text-left transition-colors",
        expanded ? "border-primary/40 bg-primary/5" : "border-gray-200 bg-white hover:bg-gray-50",
      )}
    >
      <div className="min-w-0">
        <div className="flex items-center gap-1.5">
          <span className={cn("h-1.5 w-1.5 shrink-0 rounded-full", dot(status))} aria-hidden />
          <span className="truncate text-xs font-medium text-gray-700">{title}</span>
        </div>
        <div className="mt-0.5 truncate text-sm font-semibold tabular-nums text-gray-900">
          {headline}
        </div>
      </div>
      <ChevronDown
        className={cn(
          "h-4 w-4 shrink-0 text-gray-300 transition-transform",
          expanded && "rotate-180",
        )}
      />
    </button>
  );
}

function DtiTile({ fileId, expanded, onToggle }: TileProps) {
  const { data } = useDti(fileId);
  return (
    <Tile
      title="Back-end DTI"
      headline={data?.back_end_dti != null ? `${data.back_end_dti}%` : "—"}
      status={data?.limit.status}
      expanded={expanded}
      onToggle={onToggle}
    />
  );
}

function LtvTile({ fileId, expanded, onToggle }: TileProps) {
  const { data } = useLtv(fileId);
  return (
    <Tile
      title="LTV"
      headline={data?.ltv != null ? `${data.ltv}%` : "—"}
      status={data?.limit.status}
      expanded={expanded}
      onToggle={onToggle}
    />
  );
}

function CalcTile({
  fileId,
  calculator,
  expanded,
  onToggle,
}: TileProps & { calculator: CalculatorName }) {
  const { data } = useCalculator(fileId, calculator);
  return (
    <Tile
      title={data?.title ?? humanizeCalc(calculator)}
      headline={data?.headline ?? "—"}
      status={data?.status}
      expanded={expanded}
      onToggle={onToggle}
    />
  );
}

interface TileProps {
  fileId: string;
  expanded: boolean;
  onToggle: () => void;
}

function humanizeCalc(name: CalculatorName): string {
  return {
    mortgage_insurance: "Mortgage insurance",
    self_employed: "Self-employed income",
    reserves: "Reserves",
    max_loan: "Maximum loan",
  }[name];
}

export function CalculatorsSection({ fileId }: { fileId: string }) {
  const [expanded, setExpanded] = useState<CalcKey | null>("dti");
  const toggle = (key: CalcKey) => setExpanded((cur) => (cur === key ? null : key));

  return (
    <section className="space-y-3">
      <h3 className="flex items-center gap-2 text-sm font-semibold text-gray-700">
        <Calculator className="h-4 w-4 text-primary" />
        Calculators
        <span className="text-xs font-normal text-gray-400">
          · deterministic, transparent, override-able — expand one to see the math
        </span>
      </h3>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        <DtiTile fileId={fileId} expanded={expanded === "dti"} onToggle={() => toggle("dti")} />
        <LtvTile fileId={fileId} expanded={expanded === "ltv"} onToggle={() => toggle("ltv")} />
        {(["mortgage_insurance", "self_employed", "reserves", "max_loan"] as const).map((c) => (
          <CalcTile
            key={c}
            fileId={fileId}
            calculator={c}
            expanded={expanded === c}
            onToggle={() => toggle(c)}
          />
        ))}
      </div>

      {expanded === "dti" && <DtiCalculator fileId={fileId} />}
      {expanded === "ltv" && <LtvCalculator fileId={fileId} />}
      {expanded !== null && expanded !== "dti" && expanded !== "ltv" && (
        <CalculatorCard fileId={fileId} calculator={expanded} />
      )}
    </section>
  );
}
