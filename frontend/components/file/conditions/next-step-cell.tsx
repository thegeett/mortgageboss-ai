"use client";

import { type NextStepIcon, type NextStepToken, nextStepToken } from "@/lib/conditions/next-step";
import type { Condition } from "@/lib/types/conditions";
import { cn } from "@/lib/utils";
import {
  CircleX,
  ClipboardList,
  Clock,
  FileCheck,
  Info,
  Landmark,
  type LucideIcon,
  Mail,
  MessageSquare,
  TriangleAlert,
} from "lucide-react";

const TONE: Record<NextStepToken["tone"], string> = {
  action: "text-primary",
  quiet: "text-muted-foreground",
  blocking: "text-destructive",
  attention: "text-warning",
};

const ICON: Record<NextStepIcon, LucideIcon> = {
  failed: CircleX,
  finding: TriangleAlert,
  lender: Landmark,
  info: Info,
  question: MessageSquare,
  mail: Mail,
  task: ClipboardList,
  waits: Clock,
  file: FileCheck,
};

/**
 * S3-12's Next step cell: one token with a glyph, from `nextStepToken`. A dash when there is no plan.
 *
 * LP-964 — "Plan not confirmed yet" while the round's plan waits for her. The condition already
 * carries the AI's PROPOSED step, and drawing it as a token ("Lender + LO emails") reads as decided
 * when nothing has been confirmed or drafted.
 */
export function NextStepCell({
  condition,
  onOpenDraft,
  unplanned = false,
}: {
  condition: Condition;
  /** LP-922 — an email token opens its draft. */
  onOpenDraft?: (draftId: string) => void;
  unplanned?: boolean;
}) {
  if (unplanned) {
    return <span className="pt-0.5 text-sm text-muted-foreground">Plan not confirmed yet</span>;
  }
  const token = nextStepToken(condition);
  if (token === null) {
    return <span className="pt-0.5 text-sm text-muted-foreground">—</span>;
  }
  const Icon = ICON[token.icon];
  const draftId = token.draftId;
  if (draftId && onOpenDraft) {
    return (
      <button
        type="button"
        onClick={() => onOpenDraft(draftId)}
        className={cn(
          "flex items-start gap-1.5 pt-0.5 text-left text-sm hover:underline",
          TONE[token.tone],
        )}
      >
        <Icon className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
        <span>{token.text}</span>
      </button>
    );
  }
  return (
    <span className={cn("flex items-start gap-1.5 pt-0.5 text-sm", TONE[token.tone])}>
      <Icon className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
      <span>{token.text}</span>
    </span>
  );
}
