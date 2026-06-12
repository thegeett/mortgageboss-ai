"use client";

import { catchAllSections, extractionFields, formatSource } from "@/lib/loan-files/documents";
import type { SourceLocation } from "@/lib/types/document";
import { ChevronRight, Quote } from "lucide-react";
import { useState } from "react";

/**
 * One field row (label + value) with a click-to-source affordance: when the field
 * carries a `source`, a small button reveals "p.{page}: “{snippet}”" — the exact
 * document line the value was read from (the trust/audit mechanism, LP-39a).
 */
function FieldRow({
  label,
  value,
  source,
}: {
  label: string;
  value: string;
  source: SourceLocation | null;
}) {
  const [open, setOpen] = useState(false);
  const sourceText = formatSource(source);
  return (
    <div className="px-3 py-2 text-sm">
      <div className="flex items-start justify-between gap-3">
        <span className="flex shrink-0 items-center gap-1.5 text-gray-500">
          {label}
          {sourceText && (
            <button
              type="button"
              onClick={() => setOpen((v) => !v)}
              title={sourceText}
              aria-label={`Source for ${label}: ${sourceText}`}
              aria-expanded={open}
              className="rounded p-0.5 text-gray-300 transition-colors hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <Quote className="h-3 w-3" aria-hidden />
            </button>
          )}
        </span>
        <span className="max-w-[62%] truncate text-right font-medium text-gray-900">{value}</span>
      </div>
      {open && sourceText && (
        <p className="mt-1 rounded bg-gray-50 px-2 py-1 text-[11px] leading-relaxed text-gray-500">
          {sourceText}
        </p>
      )}
    </div>
  );
}

/**
 * The full extraction (LP-39a shape): the typed core as labelled key/value rows
 * (each with its source), then the grouped catch-all as collapsible sections so
 * the processor sees EVERY captured field organized by section. Source snippets
 * are revealed on demand.
 */
export function ExtractionView({ data }: { data: Record<string, unknown> }) {
  const core = extractionFields(data);
  const sections = catchAllSections(data);

  return (
    <div className="space-y-4">
      {core.length > 0 && (
        <dl className="divide-y divide-gray-100 rounded-lg border border-gray-100">
          {core.map((field) => (
            <FieldRow
              key={field.key}
              label={field.label}
              value={field.value}
              source={field.source}
            />
          ))}
        </dl>
      )}

      {sections.length > 0 && (
        <div className="space-y-2">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-gray-400">
            All captured fields
          </p>
          {sections.map((section) => (
            <details
              key={section.section}
              className="group rounded-lg border border-gray-100 [&[open]>summary_svg]:rotate-90"
            >
              <summary className="flex cursor-pointer list-none items-center gap-1.5 px-3 py-2 text-sm font-medium text-gray-700 marker:content-none">
                <ChevronRight
                  className="h-3.5 w-3.5 text-gray-400 transition-transform"
                  aria-hidden
                />
                {section.section}
                <span className="ml-auto rounded-full bg-gray-100 px-1.5 text-[11px] font-medium text-gray-500">
                  {section.fields.length}
                </span>
              </summary>
              <dl className="divide-y divide-gray-100 border-t border-gray-100">
                {section.fields.map((field, i) => (
                  <FieldRow
                    key={`${field.label}-${i}`}
                    label={field.label}
                    value={field.value ?? "—"}
                    source={field.source}
                  />
                ))}
              </dl>
            </details>
          ))}
        </div>
      )}
    </div>
  );
}
