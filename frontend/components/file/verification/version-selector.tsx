"use client";

/**
 * The verification version selector (LP-88) — the run history.
 *
 * Verification runs are versioned (each "Run verification" is a row). This makes the
 * history visible: a collapsible list of prior runs newest-first with their summary counts
 * + timestamp, the current one marked. It connects to LP-81's merge semantics — resolutions
 * persist across runs, so the history shows how the file's verification evolved (before/
 * after applied findings, new docs). The findings shown are always the current state (they
 * live on the file, not a run); the history compares the run summaries.
 */

import { useVerificationRuns } from "@/lib/api/verification";
import type { VerificationRun } from "@/lib/types/verification";
import { cn } from "@/lib/utils";
import { ChevronDown, History } from "lucide-react";
import { useState } from "react";

function runWhen(run: VerificationRun): string {
  const ts = run.completed_at ?? run.started_at;
  if (!ts) return "—";
  return new Date(ts).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function VersionSelector({
  fileId,
  currentRunId,
}: {
  fileId: string;
  currentRunId: string | null;
}) {
  const [open, setOpen] = useState(false);
  const { data: runs } = useVerificationRuns(fileId, open);
  const count = runs?.length ?? 0;

  return (
    <div className="text-xs">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="inline-flex items-center gap-1 text-gray-500 hover:text-gray-800"
      >
        <History className="h-3.5 w-3.5" />
        Run history
        <ChevronDown className={cn("h-3 w-3 transition-transform", open && "rotate-180")} />
      </button>

      {open && (
        <div className="mt-2 overflow-hidden rounded-lg border border-gray-200">
          {runs === undefined ? (
            <p className="px-3 py-2 text-gray-400">Loading…</p>
          ) : count === 0 ? (
            <p className="px-3 py-2 text-gray-400">No runs yet.</p>
          ) : (
            <ul className="divide-y divide-gray-100">
              {runs.map((run) => (
                <li key={run.id} className="flex items-center justify-between gap-2 px-3 py-2">
                  <div className="flex items-center gap-2">
                    <span className="text-gray-600">{runWhen(run)}</span>
                    {run.id === currentRunId && (
                      <span className="rounded bg-primary/10 px-1 py-px text-[10px] font-medium text-primary">
                        current
                      </span>
                    )}
                    <span className="text-gray-400">· {run.trigger}</span>
                  </div>
                  <div className="flex items-center gap-2 tabular-nums">
                    {run.red_count > 0 && (
                      <span className="text-destructive">{run.red_count}R</span>
                    )}
                    {run.yellow_count > 0 && (
                      <span className="text-warning">{run.yellow_count}Y</span>
                    )}
                    {run.red_count === 0 && run.yellow_count === 0 && (
                      <span className="text-success">clear</span>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
