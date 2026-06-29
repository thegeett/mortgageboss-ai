"use client";

/**
 * The finding filter pills (LP-88) — severity + category, ORTHOGONAL to the dial.
 *
 * The dial (LP-79) sets the confidence floor; these pills slice the in-scope set by
 * SEVERITY (all / red / yellow) and CATEGORY (the categories present). Both compose. Pure
 * client-side — instant re-filter. Only rendered when there's something to slice.
 */

import type { VerificationFinding } from "@/lib/types/verification";
import { cn } from "@/lib/utils";
import {
  type FindingFilters,
  type SeverityFilter,
  categoriesPresent,
  categoryLabel,
} from "@/lib/verification/finding-filters";

function Pill({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        "rounded-full border px-2.5 py-0.5 text-xs font-medium transition-colors",
        active
          ? "border-primary bg-primary/10 text-primary"
          : "border-gray-200 bg-white text-gray-500 hover:bg-gray-50",
      )}
    >
      {children}
    </button>
  );
}

export function FindingFilterPills({
  findings,
  filters,
  onChange,
}: {
  findings: VerificationFinding[];
  filters: FindingFilters;
  onChange: (next: FindingFilters) => void;
}) {
  const categories = categoriesPresent(findings);
  // Nothing to slice (≤1 finding, single category) → don't clutter.
  if (findings.length <= 1 && categories.length <= 1) return null;

  const severities: { key: SeverityFilter; label: string }[] = [
    { key: "all", label: "All" },
    { key: "red", label: "Blocking" },
    { key: "yellow", label: "Warnings" },
  ];

  return (
    <div className="space-y-1.5">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="mr-0.5 text-[10px] font-semibold uppercase tracking-wide text-gray-400">
          Severity
        </span>
        {severities.map((s) => (
          <Pill
            key={s.key}
            active={filters.severity === s.key}
            onClick={() => onChange({ ...filters, severity: s.key })}
          >
            {s.label}
          </Pill>
        ))}
      </div>
      {categories.length > 1 && (
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="mr-0.5 text-[10px] font-semibold uppercase tracking-wide text-gray-400">
            Category
          </span>
          <Pill
            active={filters.category === "all"}
            onClick={() => onChange({ ...filters, category: "all" })}
          >
            All
          </Pill>
          {categories.map((c) => (
            <Pill
              key={c}
              active={filters.category === c}
              onClick={() => onChange({ ...filters, category: c })}
            >
              {categoryLabel(c)}
            </Pill>
          ))}
        </div>
      )}
    </div>
  );
}
