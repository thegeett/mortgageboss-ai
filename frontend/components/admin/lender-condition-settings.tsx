"use client";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  type LenderConditionSettings as Settings,
  useLenderConditionSettings,
  useSaveLenderConditionSettings,
} from "@/lib/api/lender-settings";
import { getErrorMessage } from "@/lib/errors/api-error";
import { useEffect, useState } from "react";

const LABEL = "text-sm font-semibold text-foreground";

const UPLOAD_FIELDS: { key: string; label: string }[] = [
  { key: "note", label: "A note (comment)" },
  { key: "name_of_source", label: "Name of source" },
  { key: "date_verified", label: "Date verified" },
];

const ROLES: { key: keyof Settings; label: string }[] = [
  {
    key: "lender_orders_final_inspection",
    label: "Lender orders the final inspection / appraisal updates",
  },
  {
    key: "lender_verifies_business_existence",
    label: "Lender verifies business existence for self-employed borrowers",
  },
  {
    key: "lender_orders_title_insurance_payoffs",
    label: "Lender orders title updates, insurance, payoffs (Processor Assist)",
  },
  {
    key: "new_files_lender_processing",
    label: "New files default to “Lender is processing this file” (Underwriting+)",
  },
];

const ZONES = [
  { value: "America/New_York", label: "Eastern (ET)" },
  { value: "America/Chicago", label: "Central (CT)" },
  { value: "America/Denver", label: "Mountain (MT)" },
  { value: "America/Los_Angeles", label: "Pacific (PT)" },
];

/**
 * S3-11 (LP-925): a lender's condition settings — entered once, used on every file with this lender.
 * The plan (who orders what), the drafts (the mortgagee clause) and the package (cutoff, the fields
 * the upload asks for) all read what is saved here. Admin only; the page already gates the role.
 */
export function LenderConditionSettings({ lenderId, name }: { lenderId: string; name: string }) {
  const { data } = useLenderConditionSettings(lenderId);
  const save = useSaveLenderConditionSettings(lenderId);
  const [draft, setDraft] = useState<Settings | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  useEffect(() => setDraft(data ?? null), [data]);
  if (!draft) return null;

  const set = (patch: Partial<Settings>) => setDraft((d) => (d ? { ...d, ...patch } : d));
  const toggleField = (key: string, on: boolean) =>
    set({
      upload_fields: UPLOAD_FIELDS.map((f) => f.key).filter((k) =>
        k === key ? on : draft.upload_fields.includes(k),
      ),
    });
  const onSave = () => {
    setMessage(null);
    const { clause_from_letter: _, ...body } = draft;
    save.mutate(body, {
      onSuccess: () => setMessage("Saved."),
      onError: (e) => setMessage(getErrorMessage(e)),
    });
  };

  return (
    <section aria-labelledby="lender-condition-settings" className="space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 id="lender-condition-settings" className="text-2xl font-semibold text-foreground">
            {name}
          </h2>
          <p className="text-sm text-muted-foreground">
            Lender settings · used on every file with this lender
          </p>
        </div>
        <Button type="button" onClick={onSave} disabled={save.isPending}>
          {save.isPending ? "Saving…" : "Save changes"}
        </Button>
      </div>
      {message ? <p className="text-sm text-muted-foreground">{message}</p> : null}

      <div className="divide-y divide-border rounded-lg border border-border bg-card">
        <SettingRow
          label="Mortgagee clause"
          hint="Filled from the approval letter; used in insurance emails"
        >
          <textarea
            aria-label="Mortgagee clause"
            value={draft.mortgagee_clause ?? ""}
            rows={2}
            onChange={(e) => set({ mortgagee_clause: e.target.value || null })}
            className="w-full resize-y rounded-md border border-input bg-background px-2.5 py-1.5 font-mono text-xs"
          />
          {draft.clause_from_letter ? (
            <p className="mt-1 text-xs text-muted-foreground">
              From the newest approval letter — not saved yet.
            </p>
          ) : null}
        </SettingRow>

        <SettingRow label="Condition upload cutoff" hint="Shown on the package">
          <div className="flex items-center gap-2">
            <Input
              type="time"
              aria-label="Upload cutoff"
              value={draft.upload_cutoff ?? ""}
              onChange={(e) => set({ upload_cutoff: e.target.value || null })}
              className="h-8 w-32"
            />
            <select
              aria-label="Time zone"
              value={draft.upload_cutoff_tz}
              onChange={(e) => set({ upload_cutoff_tz: e.target.value })}
              className="h-8 rounded-md border border-input bg-background px-2 text-sm"
            >
              {ZONES.map((z) => (
                <option key={z.value} value={z.value}>
                  {z.label}
                </option>
              ))}
            </select>
          </div>
        </SettingRow>

        <SettingRow
          label="What the upload asks per condition"
          hint="The package fills these for each condition"
        >
          <div className="flex flex-col gap-2">
            {UPLOAD_FIELDS.map((f) => (
              <label key={f.key} className="inline-flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  className="accent-primary"
                  checked={draft.upload_fields.includes(f.key)}
                  onChange={(e) => toggleField(f.key, e.target.checked)}
                />
                {f.label}
              </label>
            ))}
            <p className="text-xs text-muted-foreground">Sun West asks for all three.</p>
          </div>
        </SettingRow>

        <SettingRow
          label="Who does what at this lender"
          hint="Sets “Lender is doing it” as the default"
        >
          <div className="flex flex-col gap-2">
            {ROLES.map((r) => (
              <label key={r.key} className="inline-flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  className="accent-primary"
                  checked={Boolean(draft[r.key])}
                  onChange={(e) => set({ [r.key]: e.target.checked } as Partial<Settings>)}
                />
                {r.label}
              </label>
            ))}
          </div>
        </SettingRow>
      </div>
    </section>
  );
}

function SettingRow({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="grid gap-2 px-4 py-3 sm:grid-cols-[14rem_1fr]">
      <div>
        <p className={LABEL}>{label}</p>
        {hint ? <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p> : null}
      </div>
      <div>{children}</div>
    </div>
  );
}
