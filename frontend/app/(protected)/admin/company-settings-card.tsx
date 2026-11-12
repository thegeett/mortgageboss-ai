"use client";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useCompanySettings, useUpdateCompanySettings } from "@/lib/api/company-settings";
import { getErrorMessage } from "@/lib/errors/api-error";
import type { CompanySettings } from "@/lib/types/company-settings";
import { useState } from "react";

/**
 * The company's three settings, on the admin overview (LP-MB-Admin-02, mockup 01).
 *
 * Three checkboxes and one Save, not a Company page: three switches do not earn a screen.
 * Copy is the mockup's. Saving sends all three; the server audits only the ones that changed.
 */
const SETTINGS: { key: keyof CompanySettings; label: string; hint: string }[] = [
  {
    key: "processors_can_create_loans",
    label: "Processors may create loan files",
    hint: "Off: only owners, admins and loan officers create files.",
  },
  {
    key: "processors_can_invite_borrowers",
    label: "Processors may invite borrowers",
    hint: "Takes effect when the borrower portal ships; stored now so the permission exists.",
  },
  {
    key: "restrict_loans_to_team",
    label: "Restrict loan files to their team",
    hint: 'Off: everyone sees every file, as today. On: a file is visible to its team, owners, admins and anyone marked "sees all".',
  },
];

export function CompanySettingsCard() {
  const { data, isPending, isError, error } = useCompanySettings();
  const update = useUpdateCompanySettings();
  // The user's unsaved edits, or null for none. The form shows `draft ?? data`, so it is filled
  // on the same render the data arrives: there is no frame where the form has nothing to show.
  const [draft, setDraft] = useState<CompanySettings | null>(null);
  const shown = draft ?? data;

  const changed =
    data !== undefined && draft !== null && SETTINGS.some(({ key }) => draft[key] !== data[key]);

  return (
    <section aria-labelledby="company-settings-heading" className="space-y-3">
      <h2 id="company-settings-heading" className="text-label uppercase text-muted-foreground">
        Company settings
      </h2>
      <Card className="max-w-3xl p-4">
        {isPending ? (
          <p className="text-sm text-muted-foreground" aria-busy>
            Loading…
          </p>
        ) : isError || shown === undefined ? (
          <p className="text-sm text-muted-foreground" role="alert">
            {getErrorMessage(error)}
          </p>
        ) : (
          <form
            className="space-y-4"
            onSubmit={(event) => {
              event.preventDefault();
              update.mutate(shown, { onSuccess: () => setDraft(null) });
            }}
          >
            {SETTINGS.map(({ key, label, hint }) => (
              <label key={key} className="flex items-start gap-3">
                <input
                  type="checkbox"
                  className="mt-1 accent-primary"
                  checked={shown[key]}
                  onChange={(event) => setDraft({ ...shown, [key]: event.target.checked })}
                />
                <span>
                  <span className="block text-sm text-foreground">{label}</span>
                  <span className="block text-xs text-muted-foreground">{hint}</span>
                </span>
              </label>
            ))}
            <div className="flex items-center justify-end gap-3">
              {update.isError ? (
                <p className="text-xs text-destructive" role="alert">
                  {getErrorMessage(update.error)}
                </p>
              ) : update.isSuccess && !changed ? (
                <output className="text-xs text-muted-foreground">Saved.</output>
              ) : null}
              <Button type="submit" disabled={!changed || update.isPending}>
                {update.isPending ? "Saving…" : "Save settings"}
              </Button>
            </div>
          </form>
        )}
      </Card>
    </section>
  );
}
