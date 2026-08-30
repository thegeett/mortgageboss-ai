"use client";

import { UnresolvedAlert } from "@/components/file/calculators/unresolved-alert";

/**
 * The generic transparent calculator card (LP-87) — one component, four calculators.
 *
 * Renders any backend `CalculatorView` (mortgage insurance / self-employed income /
 * reserves / max loan) the LP-76/77 way: a headline number, the auto-populated +
 * inline-overrideable inputs (overrides recompute in real time), the read-only derivation
 * STEPS (the transparent math, shown not hidden), the formula(s), a grounded-starter
 * methodology note, and the unresolved-findings alert. The math is deterministic — this UI
 * only shows the work.
 */

import { figureToneClass, railClass } from "@/components/status-token";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { InlineErrorState } from "@/components/ui/error-state";
import { Input } from "@/components/ui/input";
import { SkeletonText } from "@/components/ui/skeleton";
import {
  useCalculator,
  useClearCalculatorOverride,
  useSetCalculatorOverride,
} from "@/lib/api/calculators";
import { formatMoneyPrecise, humanize } from "@/lib/format";
import { CALCULATOR_STATUS, resolveStatus } from "@/lib/status";
import type { FindingBreakdown } from "@/lib/types/calculators";
import type { CalcLine, CalculatorName, CalculatorView } from "@/lib/types/calculators";
import { cn } from "@/lib/utils";
import { AlertTriangle, Calculator, Check, FlaskConical, Pencil, RotateCcw, X } from "lucide-react";
import { useState } from "react";

export function CalculatorCard({
  fileId,
  calculator,
}: {
  fileId: string;
  calculator: CalculatorName;
}) {
  const { data, isPending, isError, refetch } = useCalculator(fileId, calculator);

  return (
    <Card className="border-border/80">
      <CardHeader className="space-y-1 pb-4">
        <CardTitle className="flex items-center gap-2 text-base font-semibold text-foreground">
          <span className="flex h-7 w-7 items-center justify-center rounded-md bg-primary/10 text-primary">
            <Calculator className="h-4 w-4" />
          </span>
          {data?.title ?? "Calculator"}
          {data?.program && (
            <Badge variant="secondary" className="ml-1 font-medium">
              {humanize(data.program)}
            </Badge>
          )}
        </CardTitle>
        <p className="pl-9 text-xs text-muted-foreground">
          Deterministic math · auto-populated from the file · every input shown and override-able.
        </p>
      </CardHeader>
      <CardContent aria-busy={isPending}>
        {isPending ? (
          <>
            <output className="sr-only">Calculating</output>
            <SkeletonText lines={6} />
          </>
        ) : isError || !data ? (
          <InlineErrorState
            message="Couldn't compute this calculator for the file."
            onRetry={() => void refetch()}
          />
        ) : (
          <CalculatorBody fileId={fileId} calculator={calculator} data={data} />
        )}
      </CardContent>
    </Card>
  );
}

function CalculatorBody({
  fileId,
  calculator,
  data,
}: {
  fileId: string;
  calculator: CalculatorName;
  data: CalculatorView;
}) {
  const setOverride = useSetCalculatorOverride(fileId, calculator);
  const clearOverride = useClearCalculatorOverride(fileId, calculator);
  const [editingKey, setEditingKey] = useState<string | null>(null);
  const busy = setOverride.isPending || clearOverride.isPending;

  const onSave = (key: string, amount: string) => {
    setOverride.mutate(
      { fieldKey: key, input: { amount } },
      { onSuccess: () => setEditingKey(null) },
    );
  };

  // Falls back to `neutral`, not the default `attention`: a calculator status
  // this build does not recognise is not evidence of a problem, and the default
  // would paint an amber warning across a DTI/LTV figure that is perfectly fine.
  // `neutral` also covers the no-status case, so no ternary is needed.
  const status = resolveStatus(CALCULATOR_STATUS, data.status, "neutral");
  const tone = figureToneClass(status.tone);

  return (
    <div className="space-y-5">
      {data.findings.unresolved && <UnresolvedAlert breakdown={data.findings.breakdown} />}

      {/* Headline number */}
      <div className="rounded-lg border border-border bg-muted/50 px-4 py-3">
        <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
          {data.headline_label}
        </div>
        <div className={cn("mt-0.5 text-2xl font-semibold tabular-nums", tone)}>
          {data.headline ?? "—"}
        </div>
      </div>

      {/* Overrideable inputs */}
      {data.inputs.length > 0 && (
        <section>
          <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Inputs
          </h4>
          <div className="rounded-lg border border-border">
            {data.inputs.map((item) => (
              <LineRow
                key={item.key}
                item={item}
                editing={editingKey === item.key}
                disabled={busy}
                onEdit={() => setEditingKey(item.key)}
                onCancel={() => setEditingKey(null)}
                onSave={onSave}
                onClear={(key) => clearOverride.mutate(key)}
              />
            ))}
          </div>
        </section>
      )}

      {/* The transparent derivation steps */}
      {data.steps.length > 0 && (
        <section>
          <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            The math
          </h4>
          <div className="rounded-lg border border-border">
            {data.steps.map((step, i) => (
              <div
                key={`${step.label}-${i}`}
                className={cn(
                  "flex items-center justify-between gap-3 border-t border-border px-3 py-2 text-sm first:border-t-0",
                  step.emphasis && "bg-muted/70",
                )}
              >
                <span
                  className={cn(
                    "text-foreground-2",
                    step.emphasis && "font-semibold text-foreground",
                  )}
                >
                  {step.label}
                </span>
                <span
                  className={cn(
                    "tabular-nums text-foreground-2",
                    step.emphasis && "font-semibold text-foreground",
                  )}
                >
                  {step.value}
                </span>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* The formula(s) */}
      <div className="rounded-lg border border-dashed border-input bg-muted/80 p-3">
        <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
          The formula
        </div>
        {data.formulas.map((f) => (
          <p key={f} className="mt-1.5 font-mono text-xs leading-relaxed text-foreground-2">
            {f}
          </p>
        ))}
      </div>

      {/* The grounded-starter methodology note */}
      {data.methodology.starter && (
        <div className="flex items-start gap-2 rounded-lg border border-primary/30 bg-primary/5 px-3 py-2.5 text-xs text-foreground-2">
          <FlaskConical className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" />
          <span>
            <span className="font-semibold text-primary">Methodology — starter.</span>{" "}
            {data.methodology.text}
          </span>
        </div>
      )}
    </div>
  );
}

function LineRow({
  item,
  editing,
  disabled,
  onEdit,
  onCancel,
  onSave,
  onClear,
}: {
  item: CalcLine;
  editing: boolean;
  disabled: boolean;
  onEdit: () => void;
  onCancel: () => void;
  onSave: (key: string, amount: string) => void;
  onClear: (key: string) => void;
}) {
  const [draft, setDraft] = useState<string>(item.amount);

  return (
    <div className="flex items-center justify-between gap-3 border-t border-border px-3 py-2 text-sm first:border-t-0">
      <div className="flex min-w-0 flex-col">
        <span className="truncate text-foreground-2">{item.label}</span>
        <span className="text-[11px] text-muted-foreground">
          {item.overridden ? (
            <span className="text-primary">
              {/* WHO, not just that. "Someone changed this number" and "Priya
                  changed this number" are different statements on a compliance
                  file, and the actor was already recorded — it was dropped on
                  the way out of the service (LP-UI-021). No actor recorded is
                  left as a bare "overridden": inventing "unknown" would read as
                  a name nobody checked. */}
              overridden{item.override_by ? ` by ${item.override_by}` : ""} · auto{" "}
              {formatMoneyPrecise(item.auto_amount)}
            </span>
          ) : (
            humanize(item.source)
          )}
        </span>
      </div>

      {editing ? (
        <div className="flex items-center gap-1">
          <span className="text-muted-foreground">$</span>
          <Input
            autoFocus
            value={draft}
            inputMode="decimal"
            aria-label={`Override ${item.label}`}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") onSave(item.key, draft);
              if (e.key === "Escape") onCancel();
            }}
            className="h-8 w-28 text-right tabular-nums"
          />
          <Button
            size="icon"
            variant="ghost"
            className="text-success"
            aria-label="Save override"
            disabled={disabled}
            onClick={() => onSave(item.key, draft)}
          >
            <Check className="h-4 w-4" />
          </Button>
          <Button
            size="icon"
            variant="ghost"
            className="text-muted-foreground"
            aria-label="Cancel"
            onClick={onCancel}
          >
            <X className="h-4 w-4" />
          </Button>
        </div>
      ) : (
        <div className="flex items-center gap-1.5">
          <button
            type="button"
            onClick={() => {
              setDraft(item.amount);
              onEdit();
            }}
            className={cn(
              "group inline-flex items-center gap-1.5 rounded px-1 py-0.5 tabular-nums hover:bg-muted",
              item.overridden ? "font-semibold text-primary" : "font-medium text-foreground",
            )}
          >
            {formatMoneyPrecise(item.amount)}
            <Pencil className="h-3 w-3 text-muted-foreground group-hover:text-foreground" />
          </button>
          {item.overridden && (
            <Button
              size="icon"
              variant="ghost"
              className="text-muted-foreground hover:text-foreground-2"
              aria-label={`Revert ${item.label} to auto`}
              disabled={disabled}
              onClick={() => onClear(item.key)}
            >
              <RotateCcw className="h-3.5 w-3.5" />
            </Button>
          )}
        </div>
      )}
    </div>
  );
}
