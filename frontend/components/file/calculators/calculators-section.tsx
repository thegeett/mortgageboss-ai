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
import { StatusToken } from "@/components/status-token";
import { useCalculator } from "@/lib/api/calculators";
import { useDti } from "@/lib/api/dti";
import { useLtv } from "@/lib/api/ltv";
import { CALCULATOR_STATUS, resolveStatus } from "@/lib/status";
import type { CalculatorName } from "@/lib/types/calculators";
import { cn } from "@/lib/utils";
import { Calculator, ChevronDown } from "lucide-react";
import { useState } from "react";

type CalcKey = "dti" | "ltv" | CalculatorName;

function Tile({
  title,
  fullTitle,
  headline,
  status,
  expanded,
  onToggle,
}: {
  title: string;
  /** The unabbreviated name, for the accessible name when the label is short. */
  fullTitle?: string;
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
      aria-label={`${fullTitle ?? title}: ${headline}`}
      className={cn(
        // `min-w-0` on the button as well as the label: a grid item's default
        // `min-width: auto` refuses to shrink below its content, so six tiles
        // would overflow the strip instead of sharing it.
        "flex w-full min-w-0 items-center justify-between gap-1.5 rounded-lg border px-2.5 py-2 text-left transition-colors",
        expanded ? "border-primary/40 bg-primary/5" : "border-border bg-card hover:bg-muted",
      )}
    >
      <div className="min-w-0">
        <div className="flex items-center gap-1.5">
          <StatusToken meta={resolveStatus(CALCULATOR_STATUS, status, "neutral")} variant="dot" />
          <span className="truncate text-xs font-medium text-foreground-2">{title}</span>
        </div>
        <div className="mt-0.5 truncate text-sm font-semibold tabular-nums text-foreground">
          {headline}
        </div>
      </div>
      <ChevronDown
        className={cn(
          "h-4 w-4 shrink-0 text-muted-foreground transition-transform",
          expanded && "rotate-180",
        )}
      />
    </button>
  );
}

function DtiTile({ fileId, expanded, onToggle }: TileProps) {
  const { data } = useDti(fileId);
  // LP-375: a gated DTI shows "Gated" (a required housing input is unknown), never a number on a
  // fabricated 0. The engine already nulled the ratio; the tile agrees with it.
  const gated = data?.gated === true;
  return (
    <Tile
      title="Back-end DTI"
      headline={gated ? "Gated" : data?.back_end_dti != null ? `${data.back_end_dti}%` : "—"}
      status={gated ? "unknown" : data?.limit.status}
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
      // THE TILE'S OWN SHORT LABEL, not the API's `title`. Six abreast leaves
      // ~9rem, where "Mortgage insurance" renders as "Mortgage insura…" — a
      // label that has to be guessed at. The full name is still the accessible
      // name, and the expanded panel below carries it in full.
      title={humanizeCalc(calculator)}
      fullTitle={data?.title}
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

/**
 * The tile labels, in the mockup's short forms.
 *
 * Six abreast leaves a tile about 9rem wide, and "Mortgage insurance" truncated
 * to "Mortgage insura…" — a label that has to be guessed at is worse than a
 * shorter one that does not. These are the names the Verification mockup uses.
 * The expanded panel below still carries the full name, so nothing is lost.
 */
function humanizeCalc(name: CalculatorName): string {
  return {
    mortgage_insurance: "Mortgage ins.",
    self_employed: "Self-employed",
    reserves: "Reserves",
    max_loan: "Max loan",
  }[name];
}

export function CalculatorsSection({ fileId }: { fileId: string }) {
  const [expanded, setExpanded] = useState<CalcKey | null>("dti");
  const toggle = (key: CalcKey) => setExpanded((cur) => (cur === key ? null : key));

  return (
    <section className="space-y-3">
      <h3 className="flex items-center gap-2 text-sm font-semibold text-foreground-2">
        <Calculator className="h-4 w-4 text-primary" />
        Calculators
        <span className="text-xs font-normal text-muted-foreground">
          · deterministic, transparent, override-able — expand one to see the math
        </span>
      </h3>

      {/* ONE STRIP, six tiles — what LP-UI-021 was named for and did not build.
          It shipped as a 2/3-column grid, so the six calculators took two rows
          and pushed the outcome tabs, which are the point of this screen, below
          the fold on a laptop.

          The ladder is LP-UI-037's, not an arbitrary wrap: six abreast where
          there is room, three where a tile would otherwise be too narrow to read
          its own figure, two at the bottom. A tile is a label over a number, and
          below ~9rem the number truncates — which is worse than a second row. */}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-6">
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
