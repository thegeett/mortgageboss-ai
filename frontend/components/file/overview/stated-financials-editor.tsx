"use client";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { type StatedKind, useStatedFinancialsEdit } from "@/lib/api/mismo";
import { getErrorMessage } from "@/lib/errors/api-error";
import type { StatedFinancials } from "@/lib/types/stated-financials";
import { Check, Plus, Trash2 } from "lucide-react";
import { useId, useState } from "react";
import { toast } from "sonner";

type FieldKind = "text" | "money" | "int" | "bool";
interface FieldDef {
  key: string;
  label: string;
  kind: FieldKind;
}

type RowValues = Record<string, string | boolean | null>;

/** Convert an edited form value into the JSON the API expects (empty → null). */
function toApi(kind: FieldKind, value: string | boolean | null): unknown {
  if (kind === "bool") return Boolean(value);
  if (typeof value === "string" && value.trim() === "") return null;
  return value;
}

/** One editable row: local-state inputs + Save (only changed fields) + Remove. */
function EditableRow({
  fields,
  initial,
  onSave,
  onRemove,
  busy,
}: {
  fields: FieldDef[];
  initial: RowValues;
  onSave: (changed: Record<string, unknown>) => void;
  onRemove: () => void;
  busy: boolean;
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
        Save
      </Button>
      <button
        type="button"
        onClick={onRemove}
        disabled={busy}
        aria-label="Remove row"
        className="rounded p-1.5 text-gray-400 transition-colors hover:text-destructive focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
      >
        <Trash2 className="h-4 w-4" />
      </button>
    </div>
  );
}

const LIABILITY_FIELDS: FieldDef[] = [
  { key: "liability_type", label: "Type", kind: "text" },
  { key: "monthly_payment", label: "Monthly", kind: "money" },
  { key: "unpaid_balance", label: "Balance", kind: "money" },
  { key: "holder_name", label: "Holder", kind: "text" },
];
const ASSET_FIELDS: FieldDef[] = [
  { key: "asset_type", label: "Type", kind: "text" },
  { key: "value", label: "Value", kind: "money" },
  { key: "holder_name", label: "Holder", kind: "text" },
];
const INCOME_FIELDS: FieldDef[] = [
  { key: "income_type", label: "Type", kind: "text" },
  { key: "monthly_amount", label: "Monthly", kind: "money" },
  { key: "employment_income", label: "Employment?", kind: "bool" },
];
const EMPLOYER_FIELDS: FieldDef[] = [{ key: "employer_name", label: "Employer", kind: "text" }];

function Group({
  title,
  children,
  onAdd,
  empty = false,
}: { title: string; children: React.ReactNode; onAdd: () => void; empty?: boolean }) {
  return (
    <section className="mt-5 first:mt-0">
      <div className="mb-1.5 flex items-center justify-between">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-gray-400">{title}</h4>
        <button
          type="button"
          onClick={onAdd}
          className="inline-flex items-center gap-1 rounded text-xs font-medium text-primary hover:text-primary/80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <Plus className="h-3.5 w-3.5" />
          Add
        </button>
      </div>
      {empty ? (
        <p className="rounded-lg border border-dashed border-gray-200 px-3 py-2.5 text-xs text-gray-400">
          None imported — use “Add” if any apply.
        </p>
      ) : (
        <div className="space-y-2">{children}</div>
      )}
    </section>
  );
}

/**
 * Edit mode for the stated financials (LP-56) — correct values, add a missed
 * row, remove a spurious one, across income / liabilities / assets / employers,
 * plus the stated loan terms. Each action hits the audited, tenant-scoped edit
 * endpoints and refetches the display.
 */
export function StatedFinancialsEditor({
  fileId,
  data,
}: {
  fileId: string;
  data: StatedFinancials;
}) {
  const edit = useStatedFinancialsEdit(fileId);
  const termsId = useId();

  const onError = (error: unknown) =>
    toast.error("Couldn't save the change", { description: getErrorMessage(error) });
  const saved = () => toast.success("Saved");

  const updateRow = (kind: StatedKind, id: string, body: Record<string, unknown>) =>
    edit.updateRow.mutate({ kind, id, body }, { onSuccess: saved, onError });
  const removeRow = (kind: StatedKind, id: string) =>
    edit.deleteRow.mutate({ kind, id }, { onSuccess: () => toast.success("Removed"), onError });

  const busy = edit.updateRow.isPending || edit.deleteRow.isPending;

  // Loan terms (a single PATCH on the loan file).
  const [terms, setTerms] = useState({
    note_rate_percent: data.loan_terms.note_rate_percent ?? "",
    amortization_type: data.loan_terms.amortization_type ?? "",
    amortization_months: data.loan_terms.amortization_months?.toString() ?? "",
    lien_priority: data.loan_terms.lien_priority ?? "",
  });
  const saveTerms = () =>
    edit.updateLoanTerms.mutate(
      {
        note_rate_percent: terms.note_rate_percent.trim() || null,
        amortization_type: terms.amortization_type.trim() || null,
        amortization_months: terms.amortization_months.trim() || null,
        lien_priority: terms.lien_priority.trim() || null,
      },
      { onSuccess: saved, onError },
    );

  const primaryBorrowerId = data.borrowers[0]?.id;

  return (
    <div>
      {data.borrowers.map((b) => (
        <Group
          key={b.id}
          title={`Income — ${b.full_name || "Borrower"}`}
          empty={b.income_items.length === 0 && b.employers.length === 0}
          onAdd={() =>
            edit.addIncome.mutate(
              { borrowerId: b.id, body: {} },
              { onSuccess: () => toast.success("Income row added"), onError },
            )
          }
        >
          {b.income_items.map((inc) => (
            <EditableRow
              key={inc.id}
              fields={INCOME_FIELDS}
              initial={{
                income_type: inc.income_type ?? "",
                monthly_amount: inc.monthly_amount ?? "",
                employment_income: inc.employment_income ?? false,
              }}
              onSave={(c) => updateRow("stated-income-items", inc.id, c)}
              onRemove={() => removeRow("stated-income-items", inc.id)}
              busy={busy}
            />
          ))}
          {b.employers.length > 0 &&
            b.employers.map((emp) => (
              <EditableRow
                key={emp.id}
                fields={EMPLOYER_FIELDS}
                initial={{ employer_name: emp.employer_name ?? "" }}
                onSave={(c) => updateRow("stated-employers", emp.id, c)}
                onRemove={() => removeRow("stated-employers", emp.id)}
                busy={busy}
              />
            ))}
        </Group>
      ))}

      <Group
        title="Liabilities"
        empty={data.liabilities.length === 0}
        onAdd={() =>
          edit.addLiability.mutate(
            {},
            { onSuccess: () => toast.success("Liability added"), onError },
          )
        }
      >
        {data.liabilities.map((l) => (
          <EditableRow
            key={l.id}
            fields={LIABILITY_FIELDS}
            initial={{
              liability_type: l.liability_type ?? "",
              monthly_payment: l.monthly_payment ?? "",
              unpaid_balance: l.unpaid_balance ?? "",
              holder_name: l.holder_name ?? "",
            }}
            onSave={(c) => updateRow("stated-liabilities", l.id, c)}
            onRemove={() => removeRow("stated-liabilities", l.id)}
            busy={busy}
          />
        ))}
      </Group>

      <Group
        title="Assets"
        empty={data.assets.length === 0}
        onAdd={() =>
          edit.addAsset.mutate({}, { onSuccess: () => toast.success("Asset added"), onError })
        }
      >
        {data.assets.map((a) => (
          <EditableRow
            key={a.id}
            fields={ASSET_FIELDS}
            initial={{
              asset_type: a.asset_type ?? "",
              value: a.value ?? "",
              holder_name: a.holder_name ?? "",
            }}
            onSave={(c) => updateRow("stated-assets", a.id, c)}
            onRemove={() => removeRow("stated-assets", a.id)}
            busy={busy}
          />
        ))}
      </Group>

      {/* Stated loan terms — a single PATCH on the file. */}
      <section className="mt-5">
        <h4 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-gray-400">
          Loan terms
        </h4>
        <div className="flex flex-wrap items-end gap-2 rounded-lg border border-gray-200/80 p-2.5">
          {(
            [
              ["note_rate_percent", "Note rate %"],
              ["amortization_type", "Amortization"],
              ["amortization_months", "Term (mo)"],
              ["lien_priority", "Lien"],
            ] as const
          ).map(([key, label]) => (
            <label
              key={key}
              htmlFor={`${termsId}-${key}`}
              className="flex min-w-[7rem] flex-1 flex-col gap-1 text-xs text-gray-500"
            >
              {label}
              <Input
                id={`${termsId}-${key}`}
                value={terms[key]}
                onChange={(e) => setTerms((t) => ({ ...t, [key]: e.target.value }))}
                className="h-8 text-sm"
              />
            </label>
          ))}
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={edit.updateLoanTerms.isPending}
            onClick={saveTerms}
            className="gap-1"
          >
            {edit.updateLoanTerms.isPending ? (
              <Spinner className="h-3.5 w-3.5" />
            ) : (
              <Check className="h-3.5 w-3.5" />
            )}
            Save
          </Button>
        </div>
      </section>

      {primaryBorrowerId === undefined && (
        <p className="mt-3 text-xs text-gray-400">Add a borrower to record income or employers.</p>
      )}
    </div>
  );
}
