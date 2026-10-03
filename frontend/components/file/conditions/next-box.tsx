"use client";

import { ItemLinkActions } from "@/components/file/conditions/item-links";
import { Button } from "@/components/ui/button";
import { useConditionPackage } from "@/lib/api/conditions";
import { goesInPackage, nextAction } from "@/lib/conditions/next-action";
import type { Condition } from "@/lib/types/conditions";
import { cn } from "@/lib/utils";
import { Mail, Package } from "lucide-react";

const TONE = {
  action: "border-primary/35 bg-primary/5",
  waiting: "border-input bg-muted/40",
  blocking: "border-warning/45 bg-warning/10",
  done: "border-input bg-muted/40",
} as const;

/**
 * LP-958 — the top of the drawer: what to do next, and the control that does it (`nextAction`).
 *
 * For a condition that goes in the package it also says what happens after — build and upload, Mark
 * submitted, record the answer — because the owner's "what next?" was asked at exactly that point and
 * the three steps live on three different controls.
 *
 * The lender's short name and the ready count are the package's (`useConditionPackage`), the same
 * numbers the package panel prints, so the box and the panel cannot disagree about either.
 */
export function NextBox({
  fileId,
  condition,
  onShowPackage,
  onOpenDraft,
  onRecordAnswer,
}: {
  fileId: string;
  condition: Condition;
  onShowPackage?: () => void;
  onOpenDraft?: (draftId: string) => void;
  onRecordAnswer: () => void;
}) {
  const pkg = useConditionPackage(fileId);
  const next = nextAction(condition, {
    lender: pkg.data?.lender_short ?? null,
    readyCount: pkg.data?.ready_count ?? null,
  });
  if (next === null) return null;
  const todo = next.do;
  const item =
    todo?.kind === "item" ? condition.items.find((each) => each.id === todo.itemId) : undefined;
  const lender = pkg.data?.lender_short || "the lender";

  return (
    <section
      aria-label="Next"
      className={cn("flex flex-col gap-2.5 rounded-lg border p-3", TONE[next.tone])}
    >
      <p className="text-xs font-semibold uppercase tracking-wide text-primary">Next</p>
      <p className="text-sm font-medium text-foreground">{next.text}</p>

      {item ? <ItemLinkActions fileId={fileId} condition={condition} item={item} /> : null}
      {todo?.kind === "package" && onShowPackage ? (
        <Button type="button" size="sm" className="w-fit" onClick={onShowPackage}>
          <Package className="h-3.5 w-3.5" aria-hidden />
          Open the lender package
        </Button>
      ) : null}
      {todo?.kind === "draft" && onOpenDraft ? (
        <Button type="button" size="sm" className="w-fit" onClick={() => onOpenDraft(todo.draftId)}>
          <Mail className="h-3.5 w-3.5" aria-hidden />
          Open the email
        </Button>
      ) : null}
      {todo?.kind === "record" ? (
        <Button type="button" size="sm" className="w-fit" onClick={onRecordAnswer}>
          Record the lender’s answer
        </Button>
      ) : null}

      {todo?.kind === "package" && goesInPackage(condition) ? (
        <ol className="flex flex-col gap-1 border-t border-input pt-2.5 text-xs text-foreground-2">
          <li>1. Build the package, download it, and upload it in {lender}’s portal.</li>
          <li>2. Mark it submitted: this condition becomes Sent to lender.</li>
          <li>3. When {lender} answers, record the lender’s answer here.</li>
        </ol>
      ) : null}
    </section>
  );
}
