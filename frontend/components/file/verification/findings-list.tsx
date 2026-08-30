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
import { notifyError, notifySuccess } from "@/lib/toast";
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

  /**
   * Resolve a finding and say what it did.
   *
   * EVERY RESOLUTION CARRIES AN UNDO, because one already exists — `kind: "undo"`
   * reverses any of them (LP-98), and the row has offered that button since. A
   * toast is where a processor is looking the instant they realise they clicked
   * the wrong row, and making them find the row again to undo it is the gap this
   * closes. The undo itself is not undoable, so it gets none.
   */
  function act(
    action: Parameters<typeof resolve.mutate>[0],
    { title, consequence }: { title: string; consequence: string },
  ) {
    resolve.mutate(action, {
      onSuccess: () =>
        notifySuccess({
          title,
          consequence,
          // A bulk action has no single finding to reverse, and `undo` is not
          // itself undoable. Both fall through to no undo rather than to a
          // button that would throw.
          ...(action.kind === "undo" || !("findingId" in action)
            ? {}
            : {
                undo: {
                  onUndo: () =>
                    act(
                      { kind: "undo", findingId: action.findingId },
                      {
                        title: "Resolution undone",
                        consequence: "The finding is open again and back in Needs attention.",
                      },
                    ),
                },
              }),
        }),
      onError: (e) =>
        notifyError({
          // NAMES WHAT THE PROCESSOR ACTUALLY DID. `act` serves both the
          // resolutions and the undo, and a fixed "couldn't resolve" told someone
          // who had just clicked Undo that a resolution failed — a false account
          // of their own action, in the one message they get about it.
          title:
            action.kind === "undo"
              ? "Couldn’t undo the resolution"
              : "Couldn’t resolve the finding",
          whatToDo: getErrorMessage(e),
        }),
    });
  }

  return (
    <div className="space-y-4">
      {shownOpen.length === 0 ? (
        <p className="text-sm text-muted-foreground">
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
              fileId={fileId}
              busy={resolve.isPending}
              onApply={() =>
                act(
                  { kind: "apply", findingId: f.id },
                  {
                    title: "Finding applied",
                    consequence: "The fix is recorded on the file and the finding is closed.",
                  },
                )
              }
              onOverride={(reason) =>
                act(
                  { kind: "override", findingId: f.id, reason },
                  {
                    title: "Marked not an issue",
                    consequence: "Your reason is on the file, and it no longer blocks submission.",
                  },
                )
              }
              onNote={(note) =>
                act(
                  { kind: "note", findingId: f.id, note },
                  {
                    title: "Note added",
                    consequence: "It travels with the finding for whoever reads the file next.",
                  },
                )
              }
              onAcceptRisk={(reason) =>
                act(
                  { kind: "accept-risk", findingId: f.id, reason },
                  {
                    title: "Accepted as a risk",
                    consequence:
                      "It stops blocking submission and stays visible to the underwriter.",
                  },
                )
              }
              onRequestDocs={(note) =>
                act(
                  { kind: "request-docs", findingId: f.id, note },
                  {
                    title: "Documents requested",
                    consequence: "A need is on the file; the finding stays open until it is met.",
                  },
                )
              }
            />
          ))}
        </ul>
      )}

      {resolved.length > 0 && (
        <ResolvedGroup
          findings={resolved}
          fileId={fileId}
          busy={resolve.isPending}
          onUndo={(id) =>
            act(
              { kind: "undo", findingId: id },
              {
                title: "Resolution undone",
                consequence: "The finding is open again and back in Needs attention.",
              },
            )
          }
        />
      )}
    </div>
  );
}

/** The audit trail: findings the processor already resolved (kept across re-runs — LP-94). Each
 * carries an Undo (LP-98) — reversing an Applied one reverses the data change + recomputes. */
function ResolvedGroup({
  findings,
  fileId,
  onUndo,
  busy,
}: {
  findings: VerificationFinding[];
  fileId?: string;
  onUndo: (id: string) => void;
  busy: boolean;
}) {
  return (
    <section>
      <h4 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        Resolved · {findings.length}
      </h4>
      <ul className="space-y-2 opacity-80">
        {findings.map((f) => (
          <FindingCard
            key={f.id}
            finding={f}
            fileId={fileId}
            busy={busy}
            onUndo={() => onUndo(f.id)}
          />
        ))}
      </ul>
    </section>
  );
}
