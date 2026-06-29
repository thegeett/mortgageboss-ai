"use client";

/**
 * The shared inline edit-in-place row (LP-56, generalized LP-80.5).
 *
 * One row of labelled inputs that tracks dirty state and saves only the changed
 * fields. Reused by the stated-financials editor and the Subject Property / Loan
 * editors so all three share one editing mechanism. A `select` kind covers the
 * enum/picker fields (property type, occupancy, program, purpose, lender).
 */

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
import { Check, Trash2 } from "lucide-react";
import { useId, useState } from "react";

export type FieldKind = "text" | "money" | "int" | "bool" | "select";

export interface FieldDef {
  key: string;
  label: string;
  kind: FieldKind;
  /** For `kind: "select"` — the choices (a leading "—" empty option is added). */
  options?: { value: string; label: string }[];
}

export type RowValues = Record<string, string | boolean | null>;

/** Convert an edited form value into the JSON the API expects (empty → null). */
export function toApi(kind: FieldKind, value: string | boolean | null): unknown {
  if (kind === "bool") return Boolean(value);
  if (typeof value === "string" && value.trim() === "") return null;
  return value;
}

/** One editable row: local-state inputs + Save (only changed fields) + optional Remove. */
export function EditableRow({
  fields,
  initial,
  onSave,
  onRemove,
  busy,
  saveLabel = "Save",
}: {
  fields: FieldDef[];
  initial: RowValues;
  onSave: (changed: Record<string, unknown>) => void;
  /** Omit to hide the remove button (e.g. singleton property / loan rows). */
  onRemove?: () => void;
  busy: boolean;
  saveLabel?: string;
}) {
  const rowId = useId();
  const [values, setValues] = useState<RowValues>(initial);
  const dirty = fields.some((f) => values[f.key] !== initial[f.key]);

  function save() {
    const changed: Record<string, unknown> = {};
    for (const f of fields) {
      if (values[f.key] !== initial[f.key]) changed[f.key] = toApi(f.kind, values[f.key] ?? null);
    }
    if (Object.keys(changed).length > 0) onSave(changed);
  }

  return (
    <div className="flex flex-wrap items-end gap-2 rounded-lg border border-gray-200/80 p-2.5">
      {fields.map((f) => (
        <label
          key={f.key}
          htmlFor={`${rowId}-${f.key}`}
          className="flex min-w-[7rem] flex-1 flex-col gap-1 text-xs text-gray-500"
        >
          {f.label}
          {f.kind === "bool" ? (
            <input
              id={`${rowId}-${f.key}`}
              type="checkbox"
              checked={Boolean(values[f.key])}
              onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.checked }))}
              className="h-5 w-5 self-start rounded border-gray-300"
            />
          ) : f.kind === "select" ? (
            <Select
              id={`${rowId}-${f.key}`}
              value={(values[f.key] as string | null) ?? ""}
              onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))}
              className="h-8 text-sm"
            >
              <option value="">—</option>
              {(f.options ?? []).map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </Select>
          ) : (
            <Input
              id={`${rowId}-${f.key}`}
              value={(values[f.key] as string | null) ?? ""}
              inputMode={f.kind === "money" || f.kind === "int" ? "decimal" : "text"}
              onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))}
              className="h-8 text-sm"
            />
          )}
        </label>
      ))}
      <Button
        type="button"
        size="sm"
        variant="outline"
        disabled={!dirty || busy}
        onClick={save}
        className="gap-1"
      >
        {busy ? <Spinner className="h-3.5 w-3.5" /> : <Check className="h-3.5 w-3.5" />}
        {saveLabel}
      </Button>
      {onRemove && (
        <button
          type="button"
          onClick={onRemove}
          disabled={busy}
          aria-label="Remove row"
          className="rounded p-1.5 text-gray-400 transition-colors hover:text-destructive focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
        >
          <Trash2 className="h-4 w-4" />
        </button>
      )}
    </div>
  );
}
