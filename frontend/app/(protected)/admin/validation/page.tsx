"use client";

/**
 * The rule/calculator validation aid (LP-89) — the developer's tool for Priya's session.
 *
 * Lays out EVERY grounded-starter item (rules + calculator methodologies) with its citation +
 * current value, filterable by program / category / status, and records Priya's verdict per
 * item as she gives it (validated / corrected-to-X / remove / add-new). HONEST: every item
 * defaults to "grounded_starter" — the aid CAPTURES her judgment, it does not validate. A
 * corrected value applies because she said so (recorded with attribution).
 */

import { StatusToken, figureToneClass } from "@/components/status-token";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { InlineErrorState } from "@/components/ui/error-state";
import { Input } from "@/components/ui/input";
import { SkeletonText } from "@/components/ui/skeleton";
import { useRecordVerdict, useValidationInventory } from "@/lib/api/validation-aid";
import { VALIDATION_STATUS, resolveStatus } from "@/lib/status";
import { useAuthStore } from "@/lib/stores/auth-store";
import type {
  InventoryItem,
  ValidationInventory,
  ValidationStatus,
} from "@/lib/types/validation-aid";
import { cn } from "@/lib/utils";
import { Plus } from "lucide-react";
import { useMemo, useState } from "react";

export default function ValidationAidPage() {
  const role = useAuthStore((state) => state.user?.role);
  const { data, isPending, isError, refetch } = useValidationInventory();

  if (role !== "admin") {
    return (
      <div className="rounded-lg border border-dashed border-input bg-card px-6 py-16 text-center text-sm text-muted-foreground">
        The validation aid is available to admins only.
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <header>
        {/* The same section heading the other two admin screens use. A 2xl title
            with an icon square made this page look like a different product from
            Lenders, which sits one item above it in the same column. */}
        <h2 className="text-label uppercase text-muted-foreground">
          Rule &amp; calculator validation
        </h2>
        <p className="mt-1 max-w-prose text-sm text-muted-foreground">
          Every rule and calculator methodology is a <strong>grounded starter</strong> — researched
          against the real sources but <strong>not yet validated</strong> by Priya. Walk these with
          her and record her verdict per item. Nothing is &ldquo;validated&rdquo; until she says so.
        </p>
      </header>

      {isPending ? (
        <SkeletonText lines={8} />
      ) : isError || !data ? (
        <InlineErrorState message="Couldn't load the inventory." onRetry={() => void refetch()} />
      ) : (
        <Inventory data={data} />
      )}
    </div>
  );
}

function Inventory({ data }: { data: ValidationInventory }) {
  const [program, setProgram] = useState<string>("all");
  const [category, setCategory] = useState<string>("all");
  const [statusFilter, setStatusFilter] = useState<string>("all");

  const categories = useMemo(
    () => Array.from(new Set(data.items.map((i) => i.category))).sort(),
    [data.items],
  );

  const shown = data.items.filter(
    (i) =>
      (program === "all" || (i.program ?? "agnostic") === program) &&
      (category === "all" || i.category === category) &&
      (statusFilter === "all" || i.validation_status === statusFilter),
  );

  return (
    <div className="space-y-4">
      {/* A STRIP, not five cards. Five bordered boxes give five numbers equal
          weight and a card's worth of chrome each; on a screen whose point is
          "how much of this has a human actually confirmed", the numbers should
          read as one sentence. Tones come from VALIDATION_STATUS so the counts
          and the rows below cannot disagree about what a status looks like. */}
      <div className="flex flex-wrap items-baseline gap-x-8 gap-y-2 border-b border-border pb-3">
        <Count label="Total" value={data.total} className="text-foreground" />
        <Count
          label={VALIDATION_STATUS.grounded_starter.label}
          value={data.grounded_starter}
          className={figureToneClass(VALIDATION_STATUS.grounded_starter.tone)}
        />
        <Count
          label={VALIDATION_STATUS.validated.label}
          value={data.validated}
          className={figureToneClass(VALIDATION_STATUS.validated.tone)}
        />
        <Count
          label={VALIDATION_STATUS.corrected.label}
          value={data.corrected}
          className={figureToneClass(VALIDATION_STATUS.corrected.tone)}
        />
        <Count
          label={VALIDATION_STATUS.flagged_remove.label}
          value={data.flagged_remove}
          className={figureToneClass(VALIDATION_STATUS.flagged_remove.tone)}
        />
      </div>

      {/* Filters for a systematic walkthrough. */}
      <div className="flex flex-wrap items-center gap-3 text-xs">
        <Filter
          label="Program"
          value={program}
          onChange={setProgram}
          options={["all", "conventional", "fha", "agnostic"]}
        />
        <Filter
          label="Category"
          value={category}
          onChange={setCategory}
          options={["all", ...categories]}
        />
        <Filter
          label="Status"
          value={statusFilter}
          onChange={setStatusFilter}
          // DERIVED from the vocabulary, not restated beside it. VALIDATION_STATUS
          // is exhaustive over `ValidationStatus`, so a fifth status is a compile
          // error there — and a hardcoded list here would stay green while
          // silently offering no way to filter for it.
          options={["all", ...(Object.keys(VALIDATION_STATUS) as ValidationStatus[])]}
        />
        <span className="ml-auto text-muted-foreground">
          {shown.length} of {data.total}
        </span>
      </div>

      <ul className="space-y-2">
        {shown.map((item) => (
          <ItemRow key={item.item_id} item={item} />
        ))}
      </ul>

      <AddNew />
    </div>
  );
}

function Filter({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: string[];
}) {
  return (
    <label className="flex items-center gap-1.5 text-muted-foreground">
      {label}
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded border border-input bg-card px-1.5 py-0.5 text-field md:text-xs"
      >
        {options.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
    </label>
  );
}

/** One number in the strip. */
function Count({
  label,
  value,
  className,
}: {
  label: string;
  value: number;
  className?: string;
}) {
  return (
    <div>
      <p className={cn("tabular text-xl font-medium", className)}>{value}</p>
      <p className="text-xs text-muted-foreground">{label}</p>
    </div>
  );
}

function ItemRow({ item }: { item: InventoryItem }) {
  const record = useRecordVerdict();
  const [mode, setMode] = useState<"correct" | "remove" | null>(null);
  const [value, setValue] = useState(item.verdict?.corrected_value ?? item.value ?? "");
  const [note, setNote] = useState(item.verdict?.note ?? "");

  const submit = (kind: "validated" | "corrected" | "flagged_remove") => {
    record.mutate(
      {
        item_id: item.item_id,
        kind,
        corrected_value: kind === "corrected" ? value : null,
        note: note || null,
      },
      { onSuccess: () => setMode(null) },
    );
  };

  return (
    <li className="rounded-lg border border-border px-3 py-2.5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="font-mono text-[11px] text-muted-foreground">{item.item_id}</span>
            {item.program && (
              <Badge variant="secondary" className="font-normal">
                {item.program}
              </Badge>
            )}
            <Badge variant="outline" className="font-normal text-muted-foreground">
              {item.category}
            </Badge>
            {item.to_verify && (
              <span className="rounded bg-warning/10 px-1 py-px text-[10px] font-medium text-warning">
                to verify
              </span>
            )}
          </div>
          <p className="mt-0.5 text-sm text-foreground">{item.description}</p>
          <p className="mt-0.5 text-[11px] text-muted-foreground">
            {item.value !== null && (
              <span className="font-medium text-foreground-2">
                {item.op ? `${item.op} ` : ""}
                {item.value}
                {item.unit ? ` ${item.unit}` : ""}
              </span>
            )}
            {item.citation && <span> · {item.citation}</span>}
          </p>
          {/* THE REVIEWER'S OWN WORDS, on any verdict carrying them. This
              rendered only when there was a CORRECTED VALUE, so a rule flagged
              for removal showed the flag and lost the reason — and the reason a
              rule is wrong is worth more than the flag. */}
          {item.verdict?.corrected_value ? (
            <p className="mt-0.5 text-[11px] text-warning">
              Corrected to {item.verdict.corrected_value}
            </p>
          ) : null}
          {item.verdict?.note ? (
            <p className="mt-0.5 max-w-prose text-[11px] italic text-foreground-2">
              &ldquo;{item.verdict.note}&rdquo;
            </p>
          ) : null}
        </div>
        {/* Three channels, not a tinted word: `grounded_starter` and `validated`
            must be distinguishable at a glance, and grey-versus-green is one
            channel. `resolveStatus` keeps a status this build has not heard of
            visible rather than blank. */}
        <StatusToken
          meta={resolveStatus(VALIDATION_STATUS, item.validation_status)}
          className="shrink-0"
        />
      </div>

      {/* The verdict capture. */}
      <div className="mt-2">
        {mode === null ? (
          <div className="flex flex-wrap items-center gap-1.5">
            <Button
              variant="outline"
              className="text-xs"
              disabled={record.isPending}
              onClick={() => submit("validated")}
            >
              Validate
            </Button>
            <Button variant="outline" className="text-xs" onClick={() => setMode("correct")}>
              Correct…
            </Button>
            <Button
              variant="ghost"
              className="text-xs text-muted-foreground"
              onClick={() => setMode("remove")}
            >
              Flag remove…
            </Button>
          </div>
        ) : (
          <div className="flex flex-wrap items-center gap-1.5">
            {mode === "correct" && (
              <Input
                value={value}
                onChange={(e) => setValue(e.target.value)}
                aria-label="Corrected value"
                placeholder="new value"
                className="h-7 w-28 md:text-xs"
              />
            )}
            <Input
              value={note}
              onChange={(e) => setNote(e.target.value)}
              aria-label="Verdict note"
              placeholder={mode === "remove" ? "why remove?" : "note (optional)"}
              className="h-7 w-56 md:text-xs"
            />
            <Button
              className="text-xs"
              disabled={record.isPending}
              onClick={() => submit(mode === "correct" ? "corrected" : "flagged_remove")}
            >
              Save
            </Button>
            <Button
              variant="ghost"
              className="text-xs text-muted-foreground"
              onClick={() => setMode(null)}
            >
              Cancel
            </Button>
          </div>
        )}
      </div>
    </li>
  );
}

function AddNew() {
  const record = useRecordVerdict();
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [note, setNote] = useState("");

  if (!open) {
    return (
      <Button variant="outline" size="sm" onClick={() => setOpen(true)}>
        <Plus className="mr-1.5 h-4 w-4" /> Add a rule Priya says is missing
      </Button>
    );
  }
  return (
    <div className="space-y-2 rounded-lg border border-primary/30 bg-primary/5 p-3">
      <Input
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        aria-label="New rule title"
        placeholder="The missing rule / check"
        className="h-8"
      />
      <Input
        value={note}
        onChange={(e) => setNote(e.target.value)}
        aria-label="New rule description"
        placeholder="What it should check (Priya's words)"
        className="h-8"
      />
      <div className="flex items-center gap-1.5">
        <Button
          size="sm"
          disabled={!title.trim() || record.isPending}
          onClick={() =>
            record.mutate(
              { kind: "add_new", title, note: note || null },
              {
                onSuccess: () => {
                  setOpen(false);
                  setTitle("");
                  setNote("");
                },
              },
            )
          }
        >
          Capture proposal
        </Button>
        <Button
          size="sm"
          variant="ghost"
          className="text-muted-foreground"
          onClick={() => setOpen(false)}
        >
          Cancel
        </Button>
      </div>
    </div>
  );
}
