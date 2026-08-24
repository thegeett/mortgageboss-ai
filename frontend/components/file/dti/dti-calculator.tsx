"use client";

/**
 * The DTI calculator (LP-76) — the headline "replace ChatGPT" surface.
 *
 * The value is **transparency**: the two ratios, the full itemized breakdown
 * (income / housing [PITI + MI + HOA] / each debt), the explicit formula, and the
 * effective program limit side-by-side. Every input is auto-populated and
 * override-able inline; overrides recompute in real time (the mutation returns the
 * recomputed calculation). An unresolved-findings alert warns when open findings
 * might make the numbers incomplete. The math is deterministic — this UI only
 * shows the work.
 */

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { InlineErrorState } from "@/components/ui/error-state";
import { Input } from "@/components/ui/input";
import { SkeletonText } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { useClearDtiOverride, useDti, useSetDtiOverride } from "@/lib/api/dti";
import { formatMoneyPrecise, formatPercent, humanize } from "@/lib/format";
import type { DtiCalculation, DtiLimit, DtiLineItem, UnverifiedInput } from "@/lib/types/dti";
import { cn } from "@/lib/utils";
import { AlertTriangle, Calculator, Check, Info, Lock, Pencil, RotateCcw, X } from "lucide-react";
import { useState } from "react";

export function DtiCalculator({ fileId }: { fileId: string }) {
  const { data, isPending, isError, refetch } = useDti(fileId);

  return (
    <Card className="border-gray-200/80 shadow-sm">
      <CardHeader className="space-y-1 pb-4">
        <CardTitle className="flex items-center gap-2 text-base font-semibold text-gray-900">
          <span className="flex h-7 w-7 items-center justify-center rounded-md bg-primary/10 text-primary">
            <Calculator className="h-4 w-4" />
          </span>
          DTI Calculator
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
            <output className="sr-only">Calculating debt-to-income</output>
            <SkeletonText lines={6} />
          </>
        ) : isError || !data ? (
          <InlineErrorState
            message="Couldn't calculate the DTI for this file."
            onRetry={() => void refetch()}
          />
        ) : (
          <DtiBody fileId={fileId} data={data} />
        )}
      </CardContent>
    </Card>
  );
}

function DtiBody({ fileId, data }: { fileId: string; data: DtiCalculation }) {
  const setOverride = useSetDtiOverride(fileId);
  const clearOverride = useClearDtiOverride(fileId);
  const [editingKey, setEditingKey] = useState<string | null>(null);
  const isMutating = setOverride.isPending || clearOverride.isPending;

  const onSave = (fieldKey: string, amount: string) => {
    setOverride.mutate({ fieldKey, input: { amount } });
    setEditingKey(null);
  };
  const onClear = (fieldKey: string) => {
    clearOverride.mutate(fieldKey);
    setEditingKey(null);
  };
  // bug-001 — accepting a stated estimate is an ordinary override, deliberately: it carries the
  // processor's id and a note naming the source, so the file records that a human accepted an
  // estimate rather than the calculator having assumed one.
  const onUseEstimate = (fieldKey: string, amount: string, note: string) => {
    setOverride.mutate({ fieldKey, input: { amount, note } });
  };

  const rowProps = {
    editingKey,
    onEdit: setEditingKey,
    onCancel: () => setEditingKey(null),
    onSave,
    onClear,
    disabled: isMutating,
    // bug-001 — offered ON THE LINE that reads "unknown", which is where a processor is looking when
    // they need it. The gate banner keeps the REASON (the backend already appends the sentence to
    // `gate_reason`); one button, in the place the problem is stated.
    unverified: data.unverified_inputs ?? [],
    onUseEstimate,
  };

  return (
    <div className="space-y-6">
      {data.findings.unresolved && <UnresolvedAlert count={data.findings.open_in_scope_count} />}
      {data.gated && <GatedBanner reason={data.gate_reason} />}

      <HeroRatios data={data} />

      <BreakdownSection
        title="Gross monthly income"
        items={data.income_items}
        subtotal={data.gross_monthly_income}
        emptyHint="No income on file yet — add stated income or override below."
        {...rowProps}
      />
      <BreakdownSection
        title="Housing payment (PITI + MI + HOA)"
        items={data.housing_items}
        subtotal={data.housing_payment}
        {...rowProps}
      />
      <BreakdownSection
        title="Monthly debts"
        items={data.debt_items}
        subtotal={data.monthly_debts}
        emptyHint="No other monthly debts on file."
        {...rowProps}
      />

      <FormulaReceipt data={data} />
    </div>
  );
}

// --------------------------------------------------------------------------- //
// The headline ratios + the limit side-by-side
// --------------------------------------------------------------------------- //

function HeroRatios({ data }: { data: DtiCalculation }) {
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <RatioTile label="Front-end DTI" value={data.front_end_dti} hint="housing ÷ income" />
      <BackEndTile back={data.back_end_dti} limit={data.limit} />
    </div>
  );
}

function RatioTile({
  label,
  value,
  hint,
}: {
  label: string;
  value: string | null;
  hint: string;
}) {
  return (
    <div className="rounded-lg border border-gray-200 bg-gray-50/60 px-4 py-3">
      <div className="text-xs font-medium uppercase tracking-wide text-gray-400">{label}</div>
      <div className="mt-1 text-3xl font-semibold tabular-nums text-gray-900">
        {formatPercent(value)}
      </div>
      <div className="mt-0.5 text-xs text-gray-400">{hint}</div>
    </div>
  );
}

function BackEndTile({ back, limit }: { back: string | null; limit: DtiLimit }) {
  const over = limit.status === "over";
  const known = limit.status !== "unknown";
  const pct = back !== null ? Number(back) : null;
  const cap = limit.back_end_max !== null ? Number(limit.back_end_max) : null;
  const fill = pct !== null && cap && cap > 0 ? Math.min((pct / cap) * 100, 100) : 0;

  return (
    <div
      className={cn(
        "rounded-lg border px-4 py-3",
        over ? "border-destructive/40 bg-destructive/5" : "border-primary/30 bg-primary/5",
      )}
    >
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium uppercase tracking-wide text-gray-500">
          Back-end DTI
        </span>
        {known && (
          <span
            className={cn(
              "inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold",
              over ? "bg-destructive/10 text-destructive" : "bg-success/10 text-success",
            )}
          >
            {over ? "Over limit" : "Within limit"}
          </span>
        )}
      </div>
      <div className="mt-1 flex flex-wrap items-baseline gap-x-2">
        <span
          className={cn(
            "text-3xl font-semibold tabular-nums",
            over ? "text-destructive" : "text-gray-900",
          )}
        >
          {formatPercent(back)}
        </span>
        {limit.back_end_max !== null && (
          <span className="whitespace-nowrap text-sm text-gray-400">
            / {formatPercent(limit.back_end_max)} limit
          </span>
        )}
      </div>
      {cap ? (
        <div className="mt-2">
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-gray-200">
            <div
              className={cn("h-full rounded-full", over ? "bg-destructive" : "bg-success")}
              style={{ width: `${fill}%` }}
            />
          </div>
          <div className="mt-1 text-[11px] text-gray-400">
            {limit.source === "overlay"
              ? `Lender overlay${limit.lender_slug ? ` · ${limit.lender_slug}` : ""}`
              : "Program default"}
          </div>
        </div>
      ) : (
        <div className="mt-1 text-xs text-gray-400">No program limit set</div>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------- //
// The itemized breakdown (the transparency)
// --------------------------------------------------------------------------- //

interface RowControls {
  /** bug-001 — figures the file STATES for a gated input, keyed by the line they would fill. Offered
   *  ON THE LINE, next to the "unknown" that explains why the DTI is gated: that is where a processor
   *  is looking when they need it. The gate banner still carries the reason. */
  unverified?: UnverifiedInput[];
  onUseEstimate?: (fieldKey: string, amount: string, note: string) => void;
  editingKey: string | null;
  onEdit: (key: string) => void;
  onCancel: () => void;
  onSave: (key: string, amount: string) => void;
  onClear: (key: string) => void;
  disabled: boolean;
}

function BreakdownSection({
  title,
  items,
  subtotal,
  emptyHint,
  ...controls
}: {
  title: string;
  items: DtiLineItem[];
  subtotal: string;
  emptyHint?: string;
} & RowControls) {
  return (
    <section>
      <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-gray-400">{title}</h4>
      <div className="rounded-lg border border-gray-200">
        {items.length === 0 && emptyHint ? (
          <p className="px-3 py-2.5 text-sm text-gray-400">{emptyHint}</p>
        ) : (
          items.map((item) => <LineRow key={item.key} item={item} {...controls} />)
        )}
        <div className="flex items-center justify-between border-t border-gray-200 bg-gray-50/60 px-3 py-2">
          <span className="text-xs font-semibold uppercase tracking-wide text-gray-500">
            Subtotal
          </span>
          <span className="text-sm font-semibold tabular-nums text-gray-900">
            {formatMoneyPrecise(subtotal)}
          </span>
        </div>
      </div>
    </section>
  );
}

function LineRow({
  item,
  editingKey,
  onEdit,
  onCancel,
  onSave,
  onClear,
  disabled,
  unverified,
  onUseEstimate,
}: { item: DtiLineItem } & RowControls) {
  const editing = editingKey === item.key;
  // LP-627 (corrected) — EVERY offer for this line, not the first.
  //
  // The backend emits one per SOURCE and, since LP-627, property taxes can have two: the application's
  // stated figure and the home-value estimate's. `.find` rendered whichever came first and silently
  // dropped the other — so the AVM offer that had been there all along disappeared the moment MISMO
  // stated a figure, and the surviving button read "Use the estimate" over the borrower's own
  // self-report. That is the opposite of what the backend comment says it is offering, and it
  // mislabels a self-report as an estimate.
  const suggestions = unverified?.filter((u) => u.field_key === item.key) ?? [];
  const [draft, setDraft] = useState<string>(item.amount);

  return (
    <div className="flex items-center justify-between gap-3 border-t border-gray-100 px-3 py-2 text-sm first:border-t-0">
      <div className="flex min-w-0 flex-col">
        <span className="truncate text-gray-700">{item.label}</span>
        <span className="text-[11px] text-gray-400">
          {/* LP-569 review — this chain and the amount-styling chain below MUST test in the same
              order. They disagreed (overridden→excluded→unknown here, unknown→excluded→overridden
              there), so a row that was both rendered struck through with a caption reading
              "overridden", and the reason never appeared — the silently-vanishing debt the
              exclusion was built to prevent. An override now re-includes the line, so the two are
              mutually exclusive at the source; keeping the order identical stops a future change
              from re-opening the gap. */}
          {item.excluded ? (
            <span className="text-gray-500">
              not counted — {item.excluded_reason ?? "excluded"}
            </span>
          ) : item.overridden ? (
            <span className="text-primary">
              overridden · auto {formatMoneyPrecise(item.auto_amount)}
            </span>
          ) : item.unknown ? (
            <span className="text-warning">
              unknown — missing or unusable input (fail-closed, never assumed $0)
            </span>
          ) : (
            humanize(item.source)
          )}
        </span>
        {onUseEstimate &&
          !item.overridden &&
          suggestions.map((suggestion) => (
            <UseEstimateButton
              key={`${suggestion.field_key}:${suggestion.source_label}`}
              suggestion={suggestion}
              onUse={onUseEstimate}
              disabled={disabled}
              className="mt-1 self-start"
            />
          ))}
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
              onEdit(item.key);
            }}
            className={cn(
              "group inline-flex items-center gap-1.5 rounded px-1 py-0.5 tabular-nums hover:bg-gray-100",
              // Same order as the caption chain above — see the note there.
              item.excluded
                ? "font-medium text-gray-400 line-through"
                : item.overridden
                  ? "font-semibold text-primary"
                  : item.unknown
                    ? "font-medium text-warning"
                    : "font-medium text-gray-900",
            )}
          >
            {item.unknown && !item.excluded ? "Unknown" : formatMoneyPrecise(item.amount)}
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

// --------------------------------------------------------------------------- //
// The explicit formula + the unresolved-findings alert
// --------------------------------------------------------------------------- //

/** LP-375: the DTI is FAIL-CLOSED — a required housing input is unknown, so no confident ratio is shown
 * (a $0 there would read confidently too-low). The display agrees with the engine's gate. */
function GatedBanner({ reason }: { reason?: string | null }) {
  return (
    <div
      role="alert"
      className="flex items-start gap-2 rounded-lg border border-warning/40 bg-warning/5 px-3 py-2.5 text-sm text-gray-700"
    >
      <Lock className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
      <div className="space-y-2">
        <span>
          <span className="font-medium text-gray-900">The DTI can't be computed yet</span> —{" "}
          {reason?.replace(/^calculation gated \(fail-closed\):\s*/, "") ??
            "a required housing input is unknown"}
          . It's shown as gated rather than a confident ratio resting on a missing value.
        </span>
      </div>
    </div>
  );
}

/**
 * bug-001 — accept a figure the file states for a gated input, in one click.
 *
 * The gate is CORRECT and this does not weaken it: the calculator still reads only the tax bill, and
 * clicking here writes a normal processor OVERRIDE — carrying who did it and a note naming the
 * source. The difference between this and letting the calculator read the estimate quietly is the
 * whole point: one is a decision on the record, the other is an assumption nobody made.
 *
 * The tooltip carries the reason rather than the button label, because the label has to be short and
 * the reason is the part a processor must not miss.
 */
function UseEstimateButton({
  suggestion,
  onUse,
  disabled,
  className,
}: {
  suggestion: UnverifiedInput;
  onUse: (fieldKey: string, amount: string, note: string) => void;
  disabled?: boolean;
  className?: string;
}) {
  const note = `Accepted ${suggestion.source_label}'s figure of $${suggestion.annual_amount}/yr — not a verified tax bill.`;
  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            disabled={disabled}
            onClick={() => onUse(suggestion.field_key, suggestion.monthly_amount, note)}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-md border border-warning/40 bg-white px-2.5 py-1 text-xs font-medium text-gray-700 hover:bg-warning/10 disabled:opacity-50",
              className,
            )}
          >
            <Info className="h-3.5 w-3.5 text-warning" aria-hidden />
            {/* LP-627 (corrected) — NAME THE SOURCE. With one offer "the estimate" was unambiguous;
                with two it is both ambiguous and, over the application's stated figure, wrong — a
                borrower's self-report is not an estimate. The source_label the backend already sends
                ("the application" / "the home value estimate") is what distinguishes them. */}
            Use {suggestion.source_label}'s figure (${suggestion.monthly_amount}/mo)
          </button>
        </TooltipTrigger>
        <TooltipContent className="max-w-xs">
          <p>{suggestion.sentence}</p>
          <p className="mt-1.5 text-gray-300">
            Using it records an override in your name — the file will still show this figure is an
            estimate, and the tax bill is still outstanding.
          </p>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

function FormulaReceipt({ data }: { data: DtiCalculation }) {
  return (
    <div className="rounded-lg border border-dashed border-gray-300 bg-gray-50/80 p-3">
      <div className="text-[11px] font-semibold uppercase tracking-wide text-gray-400">
        The formula
      </div>
      <p className="mt-1.5 font-mono text-xs leading-relaxed text-gray-600">
        {data.back_end_formula}
      </p>
      <p className="mt-1 font-mono text-xs leading-relaxed text-gray-900">
        = ({formatMoneyPrecise(data.housing_payment)} + {formatMoneyPrecise(data.monthly_debts)}) ÷{" "}
        {formatMoneyPrecise(data.gross_monthly_income)} ={" "}
        <span className="font-semibold">{formatPercent(data.back_end_dti)}</span>
      </p>
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
        <span className="font-medium text-gray-900">
          {count} unresolved finding{count === 1 ? "" : "s"}
        </span>{" "}
        — this calculation may be incomplete until they're applied or overridden.
      </span>
    </div>
  );
}
