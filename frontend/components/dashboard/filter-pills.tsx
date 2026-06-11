"use client";

import { FILTER_PILLS } from "@/lib/loan-files/status";
import type { FilterKey } from "@/lib/loan-files/status";
import { cn } from "@/lib/utils";

/**
 * The dashboard filter pills (All / Active / Action needed / Completed). The
 * active pill is filled; the rest are quiet outlines. A group of toggle buttons
 * (`aria-pressed`) — accessible without faking radio semantics on a button.
 */
export function FilterPills({
  value,
  onChange,
}: {
  value: FilterKey;
  onChange: (value: FilterKey) => void;
}) {
  return (
    <fieldset className="flex flex-wrap gap-1.5 border-0 p-0">
      <legend className="sr-only">Filter loan files</legend>
      {FILTER_PILLS.map((pill) => {
        const active = pill.key === value;
        return (
          <button
            key={pill.key}
            type="button"
            aria-pressed={active}
            onClick={() => onChange(pill.key)}
            className={cn(
              "rounded-full px-3 py-1.5 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
              active
                ? "bg-primary text-primary-foreground"
                : "border border-gray-200 bg-white text-gray-600 hover:bg-gray-50 hover:text-gray-900",
            )}
          >
            {pill.label}
          </button>
        );
      })}
    </fieldset>
  );
}
