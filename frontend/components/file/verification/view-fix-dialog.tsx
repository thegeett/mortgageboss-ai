"use client";

/**
 * View fix (LP-97) — the itemized before/after impact preview for an apply-spec finding.
 *
 * A DRY-RUN: it fetches the preview (the backend simulates the real apply→recompute in a
 * rolled-back savepoint, so what's shown MATCHES what Apply does) and lays out the new math —
 * the change, each affected debt line (the NEW one highlighted), the totals with deltas, the
 * income, and the recomputed DTI with any limit crossing. "Apply fix" commits the real apply;
 * Cancel is a no-op (nothing persisted).
 */

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { InlineErrorState } from "@/components/ui/error-state";
import { SkeletonText } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { useApplyPreview } from "@/lib/api/verification";
import { formatMoney, formatPercent } from "@/lib/format";
import type { DtiCalculation } from "@/lib/types/dti";
import type { VerificationFinding } from "@/lib/types/verification";
import { cn } from "@/lib/utils";
import { ArrowRight, Check } from "lucide-react";

function delta(before: string, after: string): string {
  const d = Number(after) - Number(before);
  const sign = d > 0 ? "+" : "";
  return `${sign}${formatMoney(String(d))}`;
}

function StatusPill({ status }: { status: string }) {
  const over = status === "over";
  return (
    <span
      className={cn(
        "rounded-full px-1.5 py-0.5 text-[11px] font-semibold",
        over ? "bg-destructive/10 text-destructive" : "bg-success/10 text-success",
      )}
    >
      {over ? "Over limit" : status === "pass" ? "Within limit" : "Unknown"}
    </span>
  );
}

/** The DTI before/after table — each debt line (the new one highlighted), totals, income, ratio. */
function DtiImpact({ before, after }: { before: DtiCalculation; after: DtiCalculation }) {
  const beforeKeys = new Set(before.debt_items.map((i) => i.key));

  function Row({
    label,
    beforeVal,
    afterVal,
    highlight = false,
    strong = false,
  }: {
    label: React.ReactNode;
    beforeVal: string;
    afterVal: string;
    highlight?: boolean;
    strong?: boolean;
  }) {
    const changed = beforeVal !== afterVal;
    return (
      <div
        className={cn(
          "grid grid-cols-[1fr_auto_auto] items-center gap-x-3 px-2 py-1 text-xs",
          highlight && "rounded bg-primary/5",
          strong && "border-t border-gray-200 font-semibold",
        )}
      >
        <span className={cn("truncate", strong ? "text-gray-900" : "text-gray-600")}>{label}</span>
        <span className="tabular-nums text-gray-400">{formatMoney(beforeVal)}</span>
        <span
          className={cn("tabular-nums", changed ? "font-medium text-gray-900" : "text-gray-400")}
        >
          {formatMoney(afterVal)}
          {changed && (
            <span className="ml-1 text-[10px] font-normal text-primary">
              {delta(beforeVal, afterVal)}
            </span>
          )}
        </span>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-gray-200">
      <div className="grid grid-cols-[1fr_auto_auto] gap-x-3 border-b border-gray-100 px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-gray-400">
        <span>Debts &amp; housing</span>
        <span className="text-right">Before</span>
        <span className="text-right">After</span>
      </div>
      <Row
        label="Housing (PITI)"
        beforeVal={before.housing_payment}
        afterVal={after.housing_payment}
      />
      {after.debt_items.map((item) => {
        const isNew = !beforeKeys.has(item.key);
        const prior = before.debt_items.find((b) => b.key === item.key);
        return (
          <Row
            key={item.key}
            label={
              <span className="flex items-center gap-1">
                {item.label}
                {isNew && (
                  <span className="rounded bg-primary/10 px-1 text-[9px] font-semibold text-primary">
                    NEW
                  </span>
                )}
              </span>
            }
            beforeVal={isNew ? "0" : (prior?.amount ?? "0")}
            afterVal={item.amount}
            highlight={isNew}
          />
        );
      })}
      <Row
        label="Total monthly debts"
        beforeVal={before.monthly_debts}
        afterVal={after.monthly_debts}
        strong
      />
      <Row
        label="Qualifying income"
        beforeVal={before.gross_monthly_income}
        afterVal={after.gross_monthly_income}
      />
      <div className="flex items-center justify-between gap-2 border-t border-gray-200 px-2 py-2">
        <span className="text-xs font-semibold text-gray-900">Back-end DTI</span>
        <div className="flex items-center gap-2 text-sm">
          <span className="tabular-nums text-gray-400">{formatPercent(before.back_end_dti)}</span>
          <ArrowRight className="h-3.5 w-3.5 text-gray-400" />
          <span
            className={cn(
              "font-semibold tabular-nums",
              after.limit.status === "over" ? "text-destructive" : "text-gray-900",
            )}
          >
            {formatPercent(after.back_end_dti)}
          </span>
        </div>
      </div>
      {before.limit.status !== after.limit.status && (
        <div className="flex items-center justify-center gap-2 border-t border-gray-100 bg-gray-50/70 px-2 py-1.5 text-[11px]">
          <StatusPill status={before.limit.status} />
          <ArrowRight className="h-3 w-3 text-gray-400" />
          <StatusPill status={after.limit.status} />
        </div>
      )}
    </div>
  );
}

export function ViewFixDialog({
  open,
  onOpenChange,
  fileId,
  finding,
  onApply,
  busy = false,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  fileId: string;
  finding: VerificationFinding;
  onApply: () => void;
  busy?: boolean;
}) {
  const preview = useApplyPreview(fileId, finding.id, open);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle className="text-base">Apply this fix?</DialogTitle>
          <DialogDescription>
            A preview of exactly what will change — computed as a dry-run. Nothing is saved until
            you confirm.
          </DialogDescription>
        </DialogHeader>

        {preview.isPending ? (
          <SkeletonText lines={5} />
        ) : preview.isError || !preview.data ? (
          <InlineErrorState
            message="Couldn't compute the impact preview."
            onRetry={() => void preview.refetch()}
          />
        ) : (
          <div className="space-y-3">
            <div className="rounded-md border border-primary/20 bg-primary/5 px-2.5 py-2 text-xs text-gray-700">
              <span className="font-medium text-gray-900">The change:</span> {preview.data.summary}
            </div>
            {preview.data.dti_before && preview.data.dti_after ? (
              <DtiImpact before={preview.data.dti_before} after={preview.data.dti_after} />
            ) : (
              <p className="text-xs text-gray-500">
                This change doesn&rsquo;t move the DTI or LTV.
              </p>
            )}
          </div>
        )}

        <DialogFooter>
          <Button
            type="button"
            variant="ghost"
            className="h-8 text-xs"
            disabled={busy}
            onClick={() => onOpenChange(false)}
          >
            Cancel
          </Button>
          <Button
            type="button"
            className="h-8 gap-1 text-xs"
            disabled={busy || preview.isPending || preview.isError}
            onClick={() => {
              onApply();
              onOpenChange(false);
            }}
          >
            {busy ? <Spinner className="h-3 w-3" /> : <Check className="h-3 w-3" />}
            Apply fix
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
