"use client";

/**
 * The findings list (LP-81) — open (dial-filtered, resolvable) + resolved (history).
 *
 * The aggression dial filters the OPEN findings by confidence; RESOLVED findings
 * (applied / overridden) always show in a separate "Resolved" group — a re-run never
 * silently drops a finding the processor already worked (merge-not-replace at the
 * display). Each open finding carries the core resolution actions.
 */

import { AGGRESSION_META } from "@/components/file/verification/aggression-dial";
import { FindingCard } from "@/components/file/verification/finding-card";
import { useResolveFinding } from "@/lib/api/verification";
import { getErrorMessage } from "@/lib/errors/api-error";
import type {
  AggressionLevel,
  VerificationFinding,
  VerificationStatus,
} from "@/lib/types/verification";
import {
  DEFAULT_FILTERS,
  type FindingFilters,
  matchesFilters,
} from "@/lib/verification/finding-filters";
import { toast } from "sonner";

export function FindingsList({
  fileId,
  data,
  activeLevel,
  filters = DEFAULT_FILTERS,
}: {
  fileId: string;
  data: VerificationStatus;
  activeLevel: AggressionLevel;
  filters?: FindingFilters;
}) {
  const resolve = useResolveFinding(fileId);
  const cutoff = data.aggression.cutoffs[activeLevel];

  const openAll = data.findings.filter((f) => f.resolution_status === "open");
  // The dial sets the confidence floor; the pills filter severity + category WITHIN it.
  const inScopeOpen = openAll.filter((f) => f.confidence >= cutoff);
  const shownOpen = inScopeOpen.filter((f) => matchesFilters(f, filters));
  const hiddenOpen = openAll.length - inScopeOpen.length;
  const filteredOut = inScopeOpen.length - shownOpen.length;
  const resolved = data.findings.filter((f) => f.resolution_status !== "open");

  function act(action: Parameters<typeof resolve.mutate>[0], ok: string) {
    resolve.mutate(action, {
      onSuccess: () => toast.success(ok),
      onError: (e) =>
        toast.error("Couldn't resolve the finding", { description: getErrorMessage(e) }),
    });
  }

  return (
    <div className="space-y-4">
      {shownOpen.length === 0 ? (
        <p className="text-sm text-gray-400">
          {!data.latest_run
            ? "Not run yet — run verification to compare the stated data against the documents."
            : openAll.length === 0
              ? "No open discrepancies."
              : filteredOut > 0
                ? `No findings match the active filters (${filteredOut} hidden by the filter${filteredOut === 1 ? "" : "s"}).`
                : `No findings at ${AGGRESSION_META[activeLevel].label} thoroughness — ${hiddenOpen} lower-confidence ${hiddenOpen === 1 ? "finding is" : "findings are"} hidden. Dial up to Thorough to see ${hiddenOpen === 1 ? "it" : "them"}.`}
        </p>
      ) : (
        <ul className="space-y-2">
          {shownOpen.map((f) => (
            <FindingCard
              key={f.id}
              finding={f}
              busy={resolve.isPending}
              onApply={() => act({ kind: "apply", findingId: f.id }, "Finding applied")}
              onOverride={(reason) =>
                act({ kind: "override", findingId: f.id, reason }, "Finding overridden")
              }
              onNote={(note) => act({ kind: "note", findingId: f.id, note }, "Note added")}
              onAcceptRisk={(reason) =>
                act({ kind: "accept-risk", findingId: f.id, reason }, "Finding accepted as risk")
              }
              onRequestDocs={(note) =>
                act({ kind: "request-docs", findingId: f.id, note }, "Documents requested")
              }
            />
          ))}
        </ul>
      )}

      {resolved.length > 0 && <ResolvedGroup findings={resolved} />}
    </div>
  );
}

/** The audit trail: findings the processor already resolved (kept across re-runs). */
function ResolvedGroup({ findings }: { findings: VerificationFinding[] }) {
  return (
    <section>
      <h4 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-gray-400">
        Resolved · {findings.length}
      </h4>
      <ul className="space-y-2 opacity-80">
        {findings.map((f) => (
          <FindingCard key={f.id} finding={f} />
        ))}
      </ul>
    </section>
  );
}
