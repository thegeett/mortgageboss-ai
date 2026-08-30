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

import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { useVerificationRuns } from "@/lib/api/verification";
import type { VerificationRun } from "@/lib/types/verification";
import { cn } from "@/lib/utils";
import { ChevronDown, History } from "lucide-react";
import { useEffect, useRef, useState } from "react";

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

/** Radix renders tooltip content in a portal at the document root, so it is not a DOM descendant of
 * the panel that owns it. Without this an outside-click handler counts a tooltip as "outside". */
function isInsideTooltip(node: Node): boolean {
  const element = node instanceof Element ? node : node.parentElement;
  return element?.closest("[data-radix-popper-content-wrapper]") != null;
}

/** One count in a history row: the number, with what it means on hover.
 *
 * LP-594 — a real tooltip, not the native `title` attribute. `title` is drawn by the OS after about
 * a second, cannot be styled, and — the part that actually matters — gives NO cursor affordance, so
 * a processor has no way to know a number is explainable at all. `cursor-help` and the dotted
 * underline are the signal; the tooltip is what it promises.
 *
 * A `<button>` rather than a `<span>`: Radix puts the tooltip on focus as well as hover, so it is
 * reachable by keyboard, and `aria-label` gives a screen reader the meaning a bare figure lacks.
 */
function Count({
  value,
  label,
  tone,
}: {
  value: number | string;
  label: string;
  tone: string;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          aria-label={`${value} ${label}`}
          className={cn(
            "cursor-help underline decoration-dotted decoration-from-font underline-offset-2",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
            tone,
          )}
        >
          {value}
        </button>
      </TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  );
}

export function VersionSelector({
  fileId,
  currentRunId,
}: {
  fileId: string;
  currentRunId: string | null;
}) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);

  // LP-594 — dismiss on an outside click or Escape. In flow the panel only ever pushed content
  // down, so leaving it open cost nothing and re-clicking the trigger was the whole contract. As an
  // overlay it now COVERS what is underneath, so a processor who opens it and moves on has a panel
  // sitting over their findings with no obvious way out — every dropdown they have ever used closes
  // this way, and the one that doesn't reads as stuck.
  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      // `composedRoot` guards the tooltip: Radix portals its content OUTSIDE this subtree, so a
      // plain `contains` check would treat hovering a tooltip as an outside click and close the
      // panel under the pointer.
      const target = event.target as Node | null;
      if (target && !root.current?.contains(target) && !isInsideTooltip(target)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);
  const { data: runs } = useVerificationRuns(fileId, open);
  const count = runs?.length ?? 0;

  return (
    // 150ms rather than the Radix default: these are dense, adjacent numbers a processor scans
    // across, so a slow tooltip would be missed and a zero-delay one would flicker as the pointer
    // travels. Matches the LTV calculator's provider, which made the same call.
    <TooltipProvider delayDuration={150}>
      {/* LP-594 — `relative` so the panel can anchor to this trigger, and `inline-block` so the
          anchor is the WIDTH OF THE BUTTON. As a plain block this sits in the header's left column
          and spans it, which would put the panel's edges nowhere near the control that opened it. */}
      <div ref={root} className="relative inline-block text-xs">
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          className="inline-flex items-center gap-1 text-muted-foreground hover:text-foreground"
        >
          <History className="h-3.5 w-3.5" />
          Run history
          <ChevronDown className={cn("h-3 w-3 transition-transform", open && "rotate-180")} />
        </button>

        {/* LP-594 — OVERLAYS rather than expanding. In flow this pushed every component below it
            down the page, so opening the history reflowed the whole panel and a processor lost
            their place — and with twenty runs it displaced the findings entirely.

            `absolute` takes it out of flow and `left-0` hangs it under the trigger, which sits in
            the header's left column. `z-20` clears the tab strip below. `shadow-lg` over an opaque
            background makes it read as floating rather than as content that appeared — without the
            background it would be transparent, since out-of-flow elements no longer paint over the
            card. `max-h` with its own scroll bounds the height and `max-w` the width, because the
            list is unbounded: twenty runs today and no cap on a busy file. */}
        {open && (
          <div className="absolute left-0 z-20 mt-2 max-h-80 w-max min-w-full max-w-[min(28rem,calc(100vw-3rem))] overflow-y-auto overflow-x-hidden rounded-lg border border-border bg-white shadow-lg">
            {runs === undefined ? (
              <p className="px-3 py-2 text-muted-foreground">Loading…</p>
            ) : count === 0 ? (
              <p className="px-3 py-2 text-muted-foreground">No runs yet.</p>
            ) : (
              <ul className="divide-y divide-border">
                {runs.map((run) => (
                  <li key={run.id} className="flex items-center justify-between gap-2 px-3 py-2">
                    <div className="flex items-center gap-2">
                      <span className="text-foreground-2">{runWhen(run)}</span>
                      {run.id === currentRunId && (
                        <span className="rounded bg-primary/10 px-1 py-px text-[10px] font-medium text-primary">
                          current
                        </span>
                      )}
                      <span className="text-muted-foreground">· {run.trigger}</span>
                    </div>
                    {/* LP-593 — the counts a processor reads on the TAB STRIP, not the legacy
                      sweep's severity letters. `R` and `Y` were colour codes needing decoding, and
                      they named a different vocabulary from the panel beside them.

                      Numbers alone with the tab name on hover: this list exists to COMPARE runs and
                      pick one, so the figures are what the eye needs, and spelling three labels on
                      every row would wrap the dropdown. */}
                    <div className="flex items-center gap-2 tabular-nums">
                      {run.attention_count > 0 && (
                        <Count
                          value={run.attention_count}
                          label="Needs attention"
                          tone="text-warning"
                        />
                      )}
                      {run.satisfied_count > 0 && (
                        <Count value={run.satisfied_count} label="Satisfied" tone="text-success" />
                      )}
                      {run.cross_check_count > 0 && (
                        <Count
                          value={run.cross_check_count}
                          label="Cross-checks"
                          tone="text-primary"
                        />
                      )}
                      {run.attention_count === 0 &&
                        run.satisfied_count === 0 &&
                        run.cross_check_count === 0 && (
                          <Count
                            value="—"
                            label="This run produced no findings"
                            tone="text-muted-foreground"
                          />
                        )}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>
    </TooltipProvider>
  );
}
