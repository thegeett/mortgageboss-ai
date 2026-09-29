"use client";

import { type NextStepIcon, nextStepToken } from "@/lib/conditions/next-step";
import type { Condition } from "@/lib/types/conditions";
import { cn } from "@/lib/utils";
import {
  ClipboardList,
  Clock,
  FileCheck,
  Info,
  Landmark,
  type LucideIcon,
  Mail,
  MessageSquare,
} from "lucide-react";

const ICON: Record<NextStepIcon, LucideIcon> = {
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
 */
export function NextStepCell({ condition }: { condition: Condition }) {
  const token = nextStepToken(condition);
  if (token === null) {
    return <span className="pt-0.5 text-sm text-muted-foreground">—</span>;
  }
  const Icon = ICON[token.icon];
  return (
    <span
      className={cn(
        "flex items-start gap-1.5 pt-0.5 text-sm",
        token.tone === "action" ? "text-primary" : "text-muted-foreground",
      )}
    >
      <Icon className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
      <span>{token.text}</span>
    </span>
  );
}
