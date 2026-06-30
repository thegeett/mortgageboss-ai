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

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { InlineErrorState } from "@/components/ui/error-state";
import { Input } from "@/components/ui/input";
import { SkeletonText } from "@/components/ui/skeleton";
import { useRecordVerdict, useValidationInventory } from "@/lib/api/validation-aid";
import { useAuthStore } from "@/lib/stores/auth-store";
import type { InventoryItem, ValidationInventory } from "@/lib/types/validation-aid";
import { cn } from "@/lib/utils";
import { FlaskConical, Plus } from "lucide-react";
import { useMemo, useState } from "react";

const STATUS_BADGE: Record<string, string> = {
  grounded_starter: "border-gray-200 text-gray-400",
  validated: "border-success/40 text-success",
  corrected: "border-warning/50 text-warning",
  flagged_remove: "border-destructive/40 text-destructive",
};

export default function ValidationAidPage() {
  const role = useAuthStore((state) => state.user?.role);
  const { data, isPending, isError, refetch } = useValidationInventory();

  if (role !== "admin") {
    return (
      <div className="rounded-lg border border-dashed border-gray-300 bg-white px-6 py-16 text-center text-sm text-gray-500">
        The validation aid is available to admins only.
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="flex items-center gap-2 text-2xl font-bold tracking-tight text-gray-900">
          <FlaskConical className="h-6 w-6 text-primary" />
          Rule &amp; calculator validation
        </h2>
        <p className="mt-1 max-w-3xl text-sm text-gray-500">
          Every rule and calculator methodology is a <strong>grounded starter</strong> — researched
          against the real sources but <strong>not yet validated</strong> by Priya. Walk these with
          her and record her verdict per item. Nothing is &ldquo;validated&rdquo; until she says so.
        </p>
      </div>

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
      {/* Counts (the honest progress: how much still needs validation). */}
      <div className="grid grid-cols-5 gap-2">
        {[
          { label: "Total", value: data.total, tone: "text-gray-900" },
          { label: "Grounded starter", value: data.grounded_starter, tone: "text-gray-500" },
          { label: "Validated", value: data.validated, tone: "text-success" },
          { label: "Corrected", value: data.corrected, tone: "text-warning" },
          { label: "Flagged remove", value: data.flagged_remove, tone: "text-destructive" },
        ].map((t) => (
          <div
            key={t.label}
            className="rounded-lg border border-gray-200 bg-white px-2 py-1.5 text-center"
          >
            <div className={cn("text-lg font-semibold tabular-nums leading-none", t.tone)}>
              {t.value}
            </div>
            <div className="mt-0.5 text-[10px] font-medium uppercase tracking-wide text-gray-400">
              {t.label}
            </div>
          </div>
        ))}
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
          options={["all", "grounded_starter", "validated", "corrected", "flagged_remove"]}
        />
        <span className="ml-auto text-gray-400">
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
    <label className="flex items-center gap-1.5 text-gray-500">
      {label}
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded border border-gray-200 bg-white px-1.5 py-0.5 text-xs"
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
    <li className="rounded-lg border border-gray-200 px-3 py-2.5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="font-mono text-[11px] text-gray-400">{item.item_id}</span>
            {item.program && (
              <Badge variant="secondary" className="font-normal">
                {item.program}
              </Badge>
            )}
            <Badge variant="outline" className="font-normal text-gray-400">
              {item.category}
            </Badge>
            {item.to_verify && (
              <span className="rounded bg-warning/10 px-1 py-px text-[10px] font-medium text-warning">
                to verify
              </span>
            )}
          </div>
          <p className="mt-0.5 text-sm text-gray-800">{item.description}</p>
          <p className="mt-0.5 text-[11px] text-gray-400">
            {item.value !== null && (
              <span className="font-medium text-gray-600">
                {item.op ? `${item.op} ` : ""}
                {item.value}
                {item.unit ? ` ${item.unit}` : ""}
              </span>
            )}
            {item.citation && <span> · {item.citation}</span>}
          </p>
          {item.verdict?.corrected_value && (
            <p className="mt-0.5 text-[11px] text-warning">
              Priya corrected → {item.verdict.corrected_value}
              {item.verdict.note ? ` (${item.verdict.note})` : ""}
            </p>
          )}
        </div>
        <Badge
          variant="outline"
          className={cn("shrink-0 font-normal", STATUS_BADGE[item.validation_status])}
        >
          {item.validation_status.replace("_", " ")}
        </Badge>
      </div>

      {/* The verdict capture. */}
      <div className="mt-2">
        {mode === null ? (
          <div className="flex flex-wrap items-center gap-1.5">
            <Button
              size="sm"
              variant="outline"
              className="h-7 text-xs"
              disabled={record.isPending}
              onClick={() => submit("validated")}
            >
              Validate
            </Button>
            <Button
              size="sm"
              variant="outline"
              className="h-7 text-xs"
              onClick={() => setMode("correct")}
            >
              Correct…
            </Button>
            <Button
              size="sm"
              variant="ghost"
              className="h-7 text-xs text-gray-500"
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
                className="h-7 w-28 text-xs"
              />
            )}
            <Input
              value={note}
              onChange={(e) => setNote(e.target.value)}
              aria-label="Verdict note"
              placeholder={mode === "remove" ? "why remove?" : "note (optional)"}
              className="h-7 w-56 text-xs"
            />
            <Button
              size="sm"
              className="h-7 text-xs"
              disabled={record.isPending}
              onClick={() => submit(mode === "correct" ? "corrected" : "flagged_remove")}
            >
              Save
            </Button>
            <Button
              size="sm"
              variant="ghost"
              className="h-7 text-xs text-gray-500"
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
        className="h-8 text-sm"
      />
      <Input
        value={note}
        onChange={(e) => setNote(e.target.value)}
        aria-label="New rule description"
        placeholder="What it should check (Priya's words)"
        className="h-8 text-sm"
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
        <Button size="sm" variant="ghost" className="text-gray-500" onClick={() => setOpen(false)}>
          Cancel
        </Button>
      </div>
    </div>
  );
}
