"use client";

import { UnresolvedAlert } from "@/components/file/calculators/unresolved-alert";

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
    <Card className="border-border/80">
      <CardHeader className="space-y-1 pb-4">
        <CardTitle className="flex items-center gap-2 text-base font-semibold text-foreground">
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
        <p className="pl-9 text-xs text-muted-foreground">
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
    <div className="space-y-4">
      {data.findings.unresolved && <UnresolvedAlert breakdown={data.findings.breakdown} />}
      {data.gated && <GatedBanner reason={data.gate_reason} />}

      {/* THE MATH ON THE LEFT, THE RESULT ON THE RIGHT — the mockup's
          arrangement (LP-UI-045). It ran down the page before: ratios, then
          three sections, then the formula, so the answer was above the working
          and the arithmetic that produces it was a screen below. Reading it
          meant scrolling between the number and the numbers it came from.

          Single column below `lg`, where two would make each too narrow to hold
          a label, a figure and its source on one line. */}
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_19rem]">
        <div className="min-w-0 space-y-4">
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
        </div>

        <ResultPanel data={data} />
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------- //
// The result, beside the math that produced it
// --------------------------------------------------------------------------- //

/**
 * The answer, the arithmetic that reached it, and where it sits against the cap.
 *
 * One panel rather than three stacked pieces (a ratio tile, a limit bar and a
 * formula receipt a screen apart): the figure means nothing without the division
 * that produced it, and the division means nothing without the limit it is being
 * judged against. The mockup puts all three together for that reason.
 *
 * STICKY on a wide screen, so the answer stays on screen while a processor reads
 * down the twenty-odd lines that feed it. That is the whole point of putting it
 * beside the math instead of after it.
 */
function ResultPanel({ data }: { data: DtiCalculation }) {
  return (
    <div className="space-y-3 lg:sticky lg:top-3 lg:self-start">
      <BackEndTile back={data.back_end_dti} limit={data.limit} />
      <FormulaReceipt data={data} />
      <RatioTile label="Front-end DTI" value={data.front_end_dti} hint="housing ÷ income" />
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
    <div className="rounded-lg border border-border bg-muted/60 px-4 py-3">
      <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </div>
      <div className="mt-1 text-3xl font-semibold tabular-nums text-foreground">
        {formatPercent(value)}
      </div>
      <div className="mt-0.5 text-xs text-muted-foreground">{hint}</div>
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
        <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
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
            over ? "text-destructive" : "text-foreground",
          )}
        >
          {formatPercent(back)}
        </span>
        {limit.back_end_max !== null && (
          <span className="whitespace-nowrap text-sm text-muted-foreground">
            / {formatPercent(limit.back_end_max)} limit
          </span>
        )}
      </div>
      {cap ? (
        <div className="mt-2">
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-border">
            <div
              className={cn("h-full rounded-full", over ? "bg-destructive" : "bg-success")}
              style={{ width: `${fill}%` }}
            />
          </div>
          <div className="mt-1 text-[11px] text-muted-foreground">
            {limit.source === "overlay"
              ? `Lender overlay${limit.lender_slug ? ` · ${limit.lender_slug}` : ""}`
              : "Program default"}
          </div>
        </div>
      ) : (
        <div className="mt-1 text-xs text-muted-foreground">No program limit set</div>
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
      <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {title}
      </h4>
      <div className="rounded-lg border border-border">
        {items.length === 0 && emptyHint ? (
          <p className="px-3 py-2.5 text-sm text-muted-foreground">{emptyHint}</p>
        ) : (
          items.map((item) => <LineRow key={item.key} item={item} {...controls} />)
        )}
        <div className="flex items-center justify-between border-t border-border bg-muted/60 px-3 py-2">
          <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Subtotal
          </span>
          <span className="text-sm font-semibold tabular-nums text-foreground">
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
    <div className="flex items-center justify-between gap-3 border-t border-border px-3 py-2 text-sm first:border-t-0">
      <div className="flex min-w-0 flex-col">
        <span className="truncate text-foreground-2">{item.label}</span>
        <span className="text-[11px] text-muted-foreground">
          {/* LP-569 review — this chain and the amount-styling chain below MUST test in the same
              order. They disagreed (overridden→excluded→unknown here, unknown→excluded→overridden
              there), so a row that was both rendered struck through with a caption reading
              "overridden", and the reason never appeared — the silently-vanishing debt the
              exclusion was built to prevent. An override now re-includes the line, so the two are
              mutually exclusive at the source; keeping the order identical stops a future change
              from re-opening the gap. */}
          {item.excluded ? (
            <span className="text-muted-foreground">
              not counted — {item.excluded_reason ?? "excluded"}
            </span>
          ) : item.overridden ? (
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
              onEdit(item.key);
            }}
            className={cn(
              "group inline-flex items-center gap-1.5 rounded px-1 py-0.5 tabular-nums hover:bg-muted",
              // Same order as the caption chain above — see the note there.
              item.excluded
                ? "font-medium text-muted-foreground line-through"
                : item.overridden
                  ? "font-semibold text-primary"
                  : item.unknown
                    ? "font-medium text-warning"
                    : "font-medium text-foreground",
            )}
          >
            {item.unknown && !item.excluded ? "Unknown" : formatMoneyPrecise(item.amount)}
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

// --------------------------------------------------------------------------- //
// The explicit formula + the unresolved-findings alert
// --------------------------------------------------------------------------- //

/** LP-375: the DTI is FAIL-CLOSED — a required housing input is unknown, so no confident ratio is shown
 * (a $0 there would read confidently too-low). The display agrees with the engine's gate. */
function GatedBanner({ reason }: { reason?: string | null }) {
  return (
    <div
      role="alert"
      className="flex items-start gap-2 rounded-lg border border-warning/40 bg-warning/5 px-3 py-2.5 text-sm text-foreground-2"
    >
      <Lock className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
      <div className="space-y-2">
        <span>
          <span className="font-medium text-foreground">The DTI can't be computed yet</span> —{" "}
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
              "inline-flex items-center gap-1.5 rounded-md border border-warning/40 bg-card px-2.5 py-1 text-xs font-medium text-foreground-2 hover:bg-warning/10 disabled:opacity-50",
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
          <p className="mt-1.5 text-background/75">
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
    <div className="rounded-lg border border-dashed border-input bg-muted/80 p-3">
      <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
        The formula
      </div>
      <p className="mt-1.5 font-mono text-xs leading-relaxed text-foreground-2">
        {data.back_end_formula}
      </p>
      <p className="mt-1 font-mono text-xs leading-relaxed text-foreground">
        = ({formatMoneyPrecise(data.housing_payment)} + {formatMoneyPrecise(data.monthly_debts)}) ÷{" "}
        {formatMoneyPrecise(data.gross_monthly_income)} ={" "}
        <span className="font-semibold">{formatPercent(data.back_end_dti)}</span>
      </p>
    </div>
  );
}
