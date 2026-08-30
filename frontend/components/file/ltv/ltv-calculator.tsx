"use client";

import { UnresolvedAlert } from "@/components/file/calculators/unresolved-alert";

/**
 * The LTV calculator (LP-77) — the second qualification pillar (equity / risk),
 * the parallel to the DTI calculator (LP-76). Same transparent, auto-populated,
 * override-able, findings-coupled, deterministic model — applied to the three LTV
 * ratios.
 *
 * The new substance is made visible: the **lesser-of** value basis (a purchase
 * lends against the lower of price and appraisal) and the **HELOC credit limit**
 * (HCLTV counts the full line, not the drawn balance). The loan purpose drives the
 * denominator and the limit (refinance-aware).
 */

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { InlineErrorState } from "@/components/ui/error-state";
import { Input } from "@/components/ui/input";
import { SkeletonText } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { useClearLtvOverride, useLtv, useSetLtvOverride } from "@/lib/api/ltv";
import { formatMoneyPrecise, formatPercent, humanize } from "@/lib/format";
import type { LtvCalculation, LtvLimit, LtvLineItem } from "@/lib/types/ltv";
import { cn } from "@/lib/utils";
import {
  AlertTriangle,
  Building2,
  Check,
  HelpCircle,
  Pencil,
  RotateCcw,
  Scale,
  X,
} from "lucide-react";
import { useState } from "react";

/** The subject-property line whose basis source we make explicit (LP-90 / LP-90.1). */
const LTV_APPRAISED_VALUE_KEY = "ltv.appraised_value";

export function LtvCalculator({ fileId }: { fileId: string }) {
  const { data, isPending, isError, refetch } = useLtv(fileId);

  return (
    <Card className="border-border/80">
      <CardHeader className="space-y-1 pb-4">
        <CardTitle className="flex flex-wrap items-center gap-2 text-base font-semibold text-foreground">
          <span className="flex h-7 w-7 items-center justify-center rounded-md bg-primary/10 text-primary">
            <Building2 className="h-4 w-4" />
          </span>
          LTV Calculator
          {data?.program && (
            <Badge variant="secondary" className="font-medium">
              {humanize(data.program)}
            </Badge>
          )}
          {data?.purpose && (
            <Badge variant="outline" className="font-medium text-foreground-2">
              {humanize(data.purpose)}
            </Badge>
          )}
        </CardTitle>
        <p className="pl-9 text-xs text-muted-foreground">
          Equity vs. risk — LTV / CLTV / HCLTV, deterministic and itemized.
        </p>
      </CardHeader>
      <CardContent aria-busy={isPending}>
        {isPending ? (
          <>
            <output className="sr-only">Calculating loan-to-value</output>
            <SkeletonText lines={6} />
          </>
        ) : isError || !data ? (
          <InlineErrorState
            message="Couldn't calculate the LTV for this file."
            onRetry={() => void refetch()}
          />
        ) : (
          <LtvBody fileId={fileId} data={data} />
        )}
      </CardContent>
    </Card>
  );
}

function LtvBody({ fileId, data }: { fileId: string; data: LtvCalculation }) {
  const setOverride = useSetLtvOverride(fileId);
  const clearOverride = useClearLtvOverride(fileId);
  const [editingKey, setEditingKey] = useState<string | null>(null);
  const isMutating = setOverride.isPending || clearOverride.isPending;

  const rowProps = {
    editingKey,
    onEdit: setEditingKey,
    onCancel: () => setEditingKey(null),
    onSave: (fieldKey: string, amount: string) => {
      setOverride.mutate({ fieldKey, input: { amount } });
      setEditingKey(null);
    },
    onClear: (fieldKey: string) => {
      clearOverride.mutate(fieldKey);
      setEditingKey(null);
    },
    disabled: isMutating,
  };

  return (
    <TooltipProvider delayDuration={150}>
      <div className="space-y-6">
        {data.findings.unresolved && <UnresolvedAlert breakdown={data.findings.breakdown} />}

        <div className="grid gap-3 sm:grid-cols-3">
          <LtvHeroTile ltv={data.ltv} limit={data.limit} />
          <RatioTile label="CLTV" value={data.cltv} hint="+ second & HELOC drawn" />
          <RatioTile label="HCLTV" value={data.hcltv} hint="+ full HELOC credit line" />
        </div>

        <ValueBasisCallout data={data} />

        <BreakdownSection title="Loan amounts" items={data.loan_items} {...rowProps} />
        <BreakdownSection
          title="Property value"
          items={data.value_items}
          appraisedValueSource={data.appraised_value_source}
          {...rowProps}
        />

        <FormulaReceipt data={data} />
      </div>
    </TooltipProvider>
  );
}

// --------------------------------------------------------------------------- //
// The ratios + the limit side-by-side
// --------------------------------------------------------------------------- //

function RatioTile({ label, value, hint }: { label: string; value: string | null; hint: string }) {
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

function LtvHeroTile({ ltv, limit }: { ltv: string | null; limit: LtvLimit }) {
  const over = limit.status === "over";
  const known = limit.status !== "unknown";
  const pct = ltv !== null ? Number(ltv) : null;
  const cap = limit.ltv_max !== null ? Number(limit.ltv_max) : null;
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
          LTV
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
          {formatPercent(ltv)}
        </span>
        {limit.ltv_max !== null && (
          <span className="whitespace-nowrap text-sm text-muted-foreground">
            / {formatPercent(limit.ltv_max)} limit
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
            {limit.purpose_basis === "cash_out" ? " · cash-out" : ""}
          </div>
        </div>
      ) : (
        <div className="mt-1 text-xs text-muted-foreground">No program limit set</div>
      )}
    </div>
  );
}

/** The plain-language source of the appraised-value basis (LP-90 transparency). */
function appraisedSourceLabel(source: string | null): string | null {
  if (source === "valuation_amount") return "from valuation amount";
  if (source === "estimated_value") return "from estimated value";
  return null;
}

/**
 * The "(?)" help trigger + a real, accessible tooltip (LP-90.1 — the dead native-`title`
 * tooltip is replaced). The content is the literal logic plus a plain explanation, so the
 * processor sees WHERE the appraised value comes from + WHY. Used in both the Value basis
 * callout and the editable Property-value row, so the source is clear in both places.
 */
function AppraisedSourceTooltip() {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          aria-label="How the appraised value is determined"
          className="inline-flex h-4 w-4 cursor-help items-center justify-center rounded-full text-muted-foreground hover:text-foreground-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <HelpCircle className="h-3.5 w-3.5" />
        </button>
      </TooltipTrigger>
      <TooltipContent>
        <p className="font-mono text-[11px] text-background">
          appraised = valuation_amount or estimated_value
        </p>
        <p className="mt-1 leading-relaxed text-background/75">
          The appraised value basis uses the property valuation amount; if absent, it falls back to
          the estimated value. No appraisal document is on file yet.
        </p>
      </TooltipContent>
    </Tooltip>
  );
}

/** The "lesser of" / appraised-value basis, made explicit (the trust subtlety). */
function ValueBasisCallout({ data }: { data: LtvCalculation }) {
  // Which subject-property field the "Appraised value" came from — shown so the processor
  // sees WHICH value drives the basis (no hidden field). The literal logic is in the tooltip.
  const sourceLabel = appraisedSourceLabel(data.appraised_value_source);
  return (
    <div className="rounded-lg border border-border bg-card px-3 py-2 text-sm">
      <div className="flex items-center gap-2">
        <Scale className="h-4 w-4 shrink-0 text-muted-foreground" />
        <span className="text-muted-foreground">Value basis · {data.value_basis_label}</span>
        <span className="ml-auto font-semibold tabular-nums text-foreground">
          {data.value_basis === null ? "—" : formatMoneyPrecise(data.value_basis)}
        </span>
      </div>
      {sourceLabel && (
        <div className="mt-1 flex items-center gap-1 pl-6 text-[11px] text-muted-foreground">
          Appraised value <span className="font-medium text-muted-foreground">{sourceLabel}</span>
          <AppraisedSourceTooltip />
        </div>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------- //
// The itemized breakdown
// --------------------------------------------------------------------------- //

interface RowControls {
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
  appraisedValueSource = null,
  ...controls
}: {
  title: string;
  items: LtvLineItem[];
  appraisedValueSource?: string | null;
} & RowControls) {
  return (
    <section>
      <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {title}
      </h4>
      <div className="rounded-lg border border-border">
        {items.map((item) => (
          <LineRow
            key={item.key}
            item={item}
            appraisedValueSource={appraisedValueSource}
            {...controls}
          />
        ))}
      </div>
    </section>
  );
}

function LineRow({
  item,
  appraisedValueSource,
  editingKey,
  onEdit,
  onCancel,
  onSave,
  onClear,
  disabled,
}: { item: LtvLineItem; appraisedValueSource: string | null } & RowControls) {
  const editing = editingKey === item.key;
  const [draft, setDraft] = useState<string>(item.amount);

  // The appraised-value row is sourced from valuation_amount / estimated_value — NOT
  // borrower-stated. Show the real provenance + a working tooltip, correcting the old
  // "Stated" mislabel (LP-90.1). Other rows keep their plain humanized source.
  const isAppraised = item.key === LTV_APPRAISED_VALUE_KEY;
  const sourceLabel = isAppraised ? appraisedSourceLabel(appraisedValueSource) : null;

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
          ) : sourceLabel ? (
            <span className="inline-flex items-center gap-1">
              {sourceLabel}
              <AppraisedSourceTooltip />
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
            className="h-8 w-32 text-right tabular-nums"
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

// --------------------------------------------------------------------------- //
// The explicit formulas + the unresolved-findings alert
// --------------------------------------------------------------------------- //

function FormulaReceipt({ data }: { data: LtvCalculation }) {
  const firstLoan = data.loan_items.find((i) => i.key === "ltv.first_loan")?.amount ?? null;
  return (
    <div className="space-y-1.5 rounded-lg border border-dashed border-input bg-muted/80 p-3">
      <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
        The formulas
      </div>
      <p className="font-mono text-xs leading-relaxed text-foreground-2">{data.ltv_formula}</p>
      <p className="font-mono text-xs leading-relaxed text-foreground-2">{data.cltv_formula}</p>
      <p className="font-mono text-xs leading-relaxed text-foreground-2">{data.hcltv_formula}</p>
      <p className="font-mono text-xs leading-relaxed text-foreground">
        LTV = {formatMoneyPrecise(firstLoan)} ÷{" "}
        {data.value_basis === null ? "—" : formatMoneyPrecise(data.value_basis)} ={" "}
        <span className="font-semibold">{formatPercent(data.ltv)}</span>
      </p>
    </div>
  );
}
