"use client";

/**
 * One GOVERNED rule-engine finding (LP-376) — the row + its provenance card (the detail).
 *
 * The row is identifiable WITHOUT its raw content-id: the rule id + category + a recognisable subject chip
 * (from the load-bearing tags) + the message as the identifying subline. Expanding reveals THE PROVENANCE —
 * the product: the SPEC's guideline citation, the reason in plain language, and each load-bearing tag with
 * its value, confidence, and — prominently — the AI's own REASONING (the sentence that makes a finding
 * trustworthy, LP-334). A confidence number without its reasoning is noise, so confidence shows only
 * alongside a reasoning sentence. NO §10 actions here (Accept-risk / Request-docs / Override / Note are
 * LP-377, and a button that does nothing is a lie).
 */

import { humanize } from "@/lib/format";
import type { RuleFinding, RuleFindingTag } from "@/lib/types/verification";
import { cn } from "@/lib/utils";
import { type OutcomeTone, outcomeMeta, ruleCategoryLabel } from "@/lib/verification/rule-findings";
import { ChevronDown, Gavel } from "lucide-react";
import { useId, useState } from "react";
import { type RuleFindingAction, RuleFindingActions } from "./rule-finding-actions";

const TONE: Record<OutcomeTone, { text: string; chipBg: string; border: string; dot: string }> = {
  danger: {
    text: "text-destructive",
    chipBg: "bg-destructive/10 text-destructive",
    border: "border-destructive/30",
    dot: "bg-destructive",
  },
  warning: {
    text: "text-warning",
    chipBg: "bg-warning/10 text-warning",
    border: "border-warning/30",
    dot: "bg-warning",
  },
  info: {
    text: "text-info",
    chipBg: "bg-info/10 text-info",
    border: "border-info/30",
    dot: "bg-info",
  },
  success: {
    text: "text-success",
    chipBg: "bg-success/10 text-success",
    border: "border-success/30",
    dot: "bg-success",
  },
  muted: {
    text: "text-gray-500",
    chipBg: "bg-gray-100 text-gray-500",
    border: "border-gray-200",
    dot: "bg-gray-300",
  },
};

function formatTagValue(value: unknown): string {
  if (value == null) return "—";
  if (typeof value === "boolean") return value ? "yes" : "no";
  const text = String(value).trim();
  return text.length > 0 ? text : "—";
}

/** One load-bearing tag's provenance — value + (only WITH its reasoning) confidence + the reasoning. */
function TagProvenance({ tag }: { tag: RuleFindingTag }) {
  const hasReasoning = tag.reasoning != null && tag.reasoning.trim().length > 0;
  const confidence =
    hasReasoning && tag.confidence != null ? `${Math.round(tag.confidence * 100)}%` : null;
  return (
    <li className="rounded-md border border-gray-200 bg-white px-2.5 py-2">
      <div className="flex items-baseline justify-between gap-2">
        <span className="truncate font-mono text-[11px] text-gray-500">{tag.tag_id}</span>
        <div className="flex shrink-0 items-baseline gap-2">
          <span className="text-xs font-semibold tabular-nums text-gray-900">
            {formatTagValue(tag.value)}
          </span>
          {confidence != null && (
            <span className="text-[11px] font-medium text-gray-400">conf {confidence}</span>
          )}
        </div>
      </div>
      {hasReasoning && (
        <p className="mt-1 text-xs leading-relaxed text-gray-600">{tag.reasoning}</p>
      )}
    </li>
  );
}

function DetailBlock({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-[11px] font-semibold uppercase tracking-wide text-gray-400">{label}</div>
      <div className="mt-0.5">{children}</div>
    </div>
  );
}

/**
 * The rule's identity line: NAME first, id kept beside it.
 *
 * "DT-7" identifies a rule to us and tells a processor nothing — they cannot know it means ATR
 * documentation completeness without opening the spec. The name leads because it is what the row is
 * about; the id stays because it is what a processor quotes when they escalate, what every ticket and
 * spec file calls the rule, and what makes a screenshot answerable.
 */
export function RuleLabel({ finding }: { finding: RuleFinding }) {
  return (
    <>
      <span className="font-mono text-[11px] text-gray-400">{finding.rule_id}</span>
      {finding.rule_name !== null && (
        <span className="text-xs font-semibold text-gray-800">{finding.rule_name}</span>
      )}
      <span className="text-[11px] text-gray-400">{ruleCategoryLabel(finding.category)}</span>
      {/* LP-542 — the missing-document marker OUTSIDE Couldn't check, where the request/read split
       *  already carries it. DT-7 is the case that needs it: it lands in NEEDS REVIEW saying every
       *  ability-to-repay factor is documented, while the credit report it declares is not on the
       *  file. Without this the contradiction is only visible to someone who opens the provenance.
       *  Inside couldnt_check this would repeat the sub-header, so it is suppressed there. */}
      {finding.evaluation_outcome !== "couldnt_check" && finding.missing_documents.length > 0 && (
        <span className="rounded bg-warning/10 px-1.5 py-px text-[11px] font-medium text-warning">
          not in the file: {finding.missing_documents.join(", ")}
        </span>
      )}
    </>
  );
}

export function RuleFindingRow({
  finding,
  onAct,
  pending = false,
}: {
  finding: RuleFinding;
  onAct?: (action: RuleFindingAction) => void;
  /** LP-564 — a mutation is in flight. Without it the buttons stayed live, and double-clicking Apply
   *  ran the change twice: two liabilities, one `applied_record`, and an Undo that reverses half. */
  pending?: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const meta = outcomeMeta(finding.evaluation_outcome);
  const tone = TONE[meta.tone];
  // LP-377-B: the subject label (a filename / amount / borrower / "Loan-level") — resolved by the read
  // path per subject TYPE, never the raw content-id. Two rows of the same rule are now tellable apart.
  // `?? ""` guards a version-skewed response missing the newly-added field (degrade to no chip, not throw).
  const chip = finding.subject_label ?? "";
  const panelId = useId();

  return (
    <div className={cn("rounded-lg border", expanded ? tone.border : "border-gray-200/70")}>
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
        aria-controls={panelId}
        className="flex w-full items-start gap-2.5 rounded-lg px-3 py-2.5 text-left hover:bg-gray-50/70"
      >
        <span className={cn("mt-1.5 h-2 w-2 shrink-0 rounded-full", tone.dot)} aria-hidden />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <RuleLabel finding={finding} />
            {chip.length > 0 && (
              <span className="rounded bg-gray-100 px-1.5 py-px text-[11px] font-medium text-gray-600">
                {chip}
              </span>
            )}
            {finding.ratification_pending && (
              <span className="inline-flex items-center gap-0.5 rounded bg-info/10 px-1.5 py-px text-[11px] font-medium text-info">
                <Gavel className="h-2.5 w-2.5" /> Ratification pending
              </span>
            )}
          </div>
          <p className="mt-0.5 line-clamp-2 text-sm text-gray-700">{finding.message}</p>
        </div>
        <span
          className={cn("shrink-0 rounded px-1.5 py-0.5 text-[11px] font-semibold", tone.chipBg)}
        >
          {meta.label}
        </span>
        <ChevronDown
          className={cn(
            "mt-0.5 h-4 w-4 shrink-0 text-gray-300 transition-transform",
            expanded && "rotate-180",
          )}
        />
      </button>

      {expanded && (
        <div
          id={panelId}
          className="space-y-3 border-t border-gray-100 bg-gray-50/40 px-3 py-3 pl-[1.375rem]"
        >
          <DetailBlock label={`Outcome — ${meta.label}`}>
            <p className={cn("text-xs font-medium", tone.text)}>{meta.blurb}</p>
            <p className="mt-1 text-sm text-gray-700">{finding.message}</p>
          </DetailBlock>

          {finding.how_to_fix != null && finding.how_to_fix.trim().length > 0 && (
            <DetailBlock label="How to fix">
              <p className="text-sm text-gray-700">{finding.how_to_fix}</p>
            </DetailBlock>
          )}

          {finding.guideline != null && finding.guideline.trim().length > 0 && (
            <DetailBlock label="Guideline (from the rule spec)">
              <p className="text-sm italic leading-relaxed text-gray-600">{finding.guideline}</p>
            </DetailBlock>
          )}

          {finding.ratification_pending && (
            <p className="flex items-start gap-1.5 rounded-md border border-info/30 bg-info/5 px-2.5 py-2 text-xs text-gray-600">
              <Gavel className="mt-0.5 h-3.5 w-3.5 shrink-0 text-info" />
              This is a judgment (AI) verdict awaiting human ratification — it is not an
              auto-shipped conclusion, and it is not a violation.
            </p>
          )}

          {finding.load_bearing_tags.length > 0 && (
            // LP-522 — COLLAPSED BY DEFAULT. This is the ratifier's audit trail, not the processor's
            // reading: on a real AS-12 finding it ran ~400 words of model prose, and the fact a
            // processor most needed ("no matching withdrawal was found") was the fifth entry down. That
            // fact is now a sentence in the message itself, so the tags are here to be AUDITED, not
            // read. It also puts the bare `yes`/`no` verdict chips behind a click — two
            // opposite-polarity values sat adjacent with no legend, and a skimmed `yes` on a
            // borrowed-funds check reads as "yes, fine" when it means the opposite.
            <details className="group">
              <summary className="cursor-pointer list-none text-[11px] font-semibold uppercase tracking-wide text-gray-400 hover:text-gray-600">
                <span className="group-open:hidden">
                  Show the {finding.load_bearing_tags.length} tags this verdict rested on
                </span>
                <span className="hidden group-open:inline">Hide the tags</span>
              </summary>
              <ul className="mt-1.5 space-y-2">
                {finding.load_bearing_tags.map((tag, index) => (
                  <TagProvenance key={`${tag.tag_id}-${index}`} tag={tag} />
                ))}
              </ul>
            </details>
          )}

          {finding.subject_label.length > 0 && (
            // LP-377-B: the subject in human terms (a filename / borrower / "Loan-level"), never the raw
            // content-id an engineer's `subject_key` carries — a processor should not see a hash here.
            <p className="text-[11px] text-gray-400">
              Subject: <span className="font-medium text-gray-500">{finding.subject_label}</span>
            </p>
          )}
        </div>
      )}

      {/* LP-561 — OUTSIDE the expander, deliberately. The point of the buttons is to clear a queue;
          hiding them behind a click makes acting cost more than reading, and the fastest action on a
          list of twenty-five is the one that needs no navigation. */}
      {onAct !== undefined && (
        <div className="px-3 pb-2.5">
          <RuleFindingActions finding={finding} onAct={onAct} pending={pending} />
        </div>
      )}
    </div>
  );
}
