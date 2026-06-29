"use client";

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
import type { CalcLine, CalculatorName, CalculatorView } from "@/lib/types/calculators";
import { cn } from "@/lib/utils";
import { AlertTriangle, Calculator, Check, FlaskConical, Pencil, RotateCcw, X } from "lucide-react";
import { useState } from "react";

const STATUS_TONE: Record<string, string> = {
  required: "text-warning",
  not_required: "text-gray-500",
  sufficient: "text-success",
  insufficient: "text-danger",
  declining: "text-warning",
  over: "text-danger",
  pass: "text-success",
};

export function CalculatorCard({
  fileId,
  calculator,
}: {
  fileId: string;
  calculator: CalculatorName;
}) {
  const { data, isPending, isError, refetch } = useCalculator(fileId, calculator);

  return (
    <Card className="border-gray-200/80 shadow-sm">
      <CardHeader className="space-y-1 pb-4">
        <CardTitle className="flex items-center gap-2 text-base font-semibold text-gray-900">
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
        <p className="pl-9 text-xs text-gray-500">
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

  const tone = (data.status && STATUS_TONE[data.status]) || "text-gray-900";

  return (
    <div className="space-y-5">
      {data.findings.unresolved && <UnresolvedAlert count={data.findings.open_in_scope_count} />}

      {/* Headline number */}
      <div className="rounded-lg border border-gray-200 bg-gray-50/50 px-4 py-3">
        <div className="text-[11px] font-semibold uppercase tracking-wide text-gray-400">
          {data.headline_label}
        </div>
        <div className={cn("mt-0.5 text-2xl font-semibold tabular-nums", tone)}>
          {data.headline ?? "—"}
        </div>
      </div>

      {/* Overrideable inputs */}
      {data.inputs.length > 0 && (
        <section>
          <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-gray-400">
            Inputs
          </h4>
          <div className="rounded-lg border border-gray-200">
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
          <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-gray-400">
            The math
          </h4>
          <div className="rounded-lg border border-gray-200">
            {data.steps.map((step, i) => (
              <div
                key={`${step.label}-${i}`}
                className={cn(
                  "flex items-center justify-between gap-3 border-t border-gray-100 px-3 py-2 text-sm first:border-t-0",
                  step.emphasis && "bg-gray-50/70",
                )}
              >
                <span
                  className={cn("text-gray-600", step.emphasis && "font-semibold text-gray-900")}
                >
                  {step.label}
                </span>
                <span
                  className={cn(
                    "tabular-nums text-gray-700",
                    step.emphasis && "font-semibold text-gray-900",
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
      <div className="rounded-lg border border-dashed border-gray-300 bg-gray-50/80 p-3">
        <div className="text-[11px] font-semibold uppercase tracking-wide text-gray-400">
          The formula
        </div>
        {data.formulas.map((f) => (
          <p key={f} className="mt-1.5 font-mono text-xs leading-relaxed text-gray-600">
            {f}
          </p>
        ))}
      </div>

      {/* The grounded-starter methodology note */}
      {data.methodology.starter && (
        <div className="flex items-start gap-2 rounded-lg border border-primary/30 bg-primary/5 px-3 py-2.5 text-xs text-gray-600">
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
    <div className="flex items-center justify-between gap-3 border-t border-gray-100 px-3 py-2 text-sm first:border-t-0">
      <div className="flex min-w-0 flex-col">
        <span className="truncate text-gray-700">{item.label}</span>
        <span className="text-[11px] text-gray-400">
          {item.overridden ? (
            <span className="text-primary">
              overridden · auto {formatMoneyPrecise(item.auto_amount)}
            </span>
          ) : (
            humanize(item.source)
          )}
        </span>
      </div>

      {editing ? (
        <div className="flex items-center gap-1">
          <span className="text-gray-400">$</span>
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
            className="h-8 w-28 text-right text-sm tabular-nums"
          />
          <Button
            size="icon"
            variant="ghost"
            className="h-8 w-8 text-success"
            aria-label="Save override"
            disabled={disabled}
            onClick={() => onSave(item.key, draft)}
          >
            <Check className="h-4 w-4" />
          </Button>
          <Button
            size="icon"
            variant="ghost"
            className="h-8 w-8 text-gray-400"
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
              "group inline-flex items-center gap-1.5 rounded px-1 py-0.5 tabular-nums hover:bg-gray-100",
              item.overridden ? "font-semibold text-primary" : "font-medium text-gray-900",
            )}
          >
            {formatMoneyPrecise(item.amount)}
            <Pencil className="h-3 w-3 text-gray-300 group-hover:text-gray-500" />
          </button>
          {item.overridden && (
            <Button
              size="icon"
              variant="ghost"
              className="h-7 w-7 text-gray-400 hover:text-gray-700"
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

function UnresolvedAlert({ count }: { count: number }) {
  return (
    <div
      role="alert"
      className="flex items-start gap-2 rounded-lg border border-warning/40 bg-warning/5 px-3 py-2.5 text-sm text-gray-700"
    >
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
      <span>
        <span className="font-medium">
          {count} unresolved finding{count === 1 ? "" : "s"}
        </span>{" "}
        — this calculation may be incomplete until they're applied or overridden.
      </span>
    </div>
  );
}
