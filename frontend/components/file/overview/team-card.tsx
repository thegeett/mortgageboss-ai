"use client";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Select } from "@/components/ui/select";
import {
  type AssignablePerson,
  useAddProcessor,
  useAssignable,
  useRemoveMember,
  useSetLoanOfficer,
  useTeam,
} from "@/lib/api/loan-teams";
import { getErrorMessage } from "@/lib/errors/api-error";
import type { TeamMember } from "@/lib/types/loan-file";
import { X } from "lucide-react";
import { useState } from "react";

/**
 * Who works this file (LP-MB-Admin-05, mockup 13).
 *
 * The controls appear only when the server says this person may change the team (`can_change`: an
 * Admin, or the loan officer on their own file); everyone else sees it read-only. The loan officer
 * slot is hidden entirely in a company with nobody holding the Loan officer role (a processing
 * company, whose loan officer is at the broker and stays free text), unless one is already set.
 */
export function TeamCard({ fileId }: { fileId: string }) {
  const team = useTeam(fileId);
  const officers = useAssignable("loan_officer");
  const processors = useAssignable("processor");
  const setLo = useSetLoanOfficer(fileId);
  const add = useAddProcessor(fileId);
  const remove = useRemoveMember(fileId);
  const [error, setError] = useState<string | null>(null);
  const [changingLo, setChangingLo] = useState(false);

  async function run(action: () => Promise<unknown>) {
    setError(null);
    try {
      await action();
    } catch (failure) {
      setError(getErrorMessage(failure));
    }
  }

  const data = team.data;
  const canChange = data?.can_change ?? false;
  const showLoSlot = Boolean(data?.loan_officer) || (officers.data?.length ?? 0) > 0;
  const onTeam = new Set(data?.processors.map((member) => member.user_id) ?? []);
  const addable = (processors.data ?? []).filter((person) => !onTeam.has(person.id));

  return (
    <Card className="border-border/80">
      <CardHeader className="flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-sm font-semibold text-foreground">Team</CardTitle>
        <span className="text-xs text-muted-foreground">Who works this file</span>
      </CardHeader>
      <CardContent className="space-y-4 pt-0">
        {team.isPending ? (
          <p className="text-sm text-muted-foreground" aria-busy>
            Loading…
          </p>
        ) : team.isError || !data ? (
          <p className="text-sm text-muted-foreground" role="alert">
            {getErrorMessage(team.error)}
          </p>
        ) : (
          <>
            {error ? (
              <p role="alert" className="text-sm text-destructive">
                {error}
              </p>
            ) : null}

            {showLoSlot ? (
              <section className="space-y-2" aria-label="Loan officer">
                <h3 className="text-label uppercase text-muted-foreground">Loan officer</h3>
                <div className="flex items-start justify-between gap-3">
                  {data.loan_officer ? (
                    <Person member={data.loan_officer} licensing />
                  ) : (
                    <p className="text-sm text-muted-foreground">No loan officer</p>
                  )}
                  {canChange && !changingLo ? (
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      onClick={() => setChangingLo(true)}
                    >
                      {data.loan_officer ? "Change" : "Assign"}
                    </Button>
                  ) : null}
                </div>
                {canChange && changingLo ? (
                  <Picker
                    label="Choose the loan officer"
                    people={officers.data ?? []}
                    placeholder="Choose a loan officer…"
                    hint="Only active people with the Loan officer role."
                    clearLabel={data.loan_officer ? "No loan officer" : undefined}
                    onPick={(userId) =>
                      run(async () => {
                        await setLo.mutateAsync(userId);
                        setChangingLo(false);
                      })
                    }
                    onCancel={() => setChangingLo(false)}
                  />
                ) : null}
              </section>
            ) : null}

            <section className="space-y-2" aria-label="Processors">
              <h3 className="text-label uppercase text-muted-foreground">Processors</h3>
              {data.processors.length === 0 ? (
                <p className="text-sm text-muted-foreground">No processors</p>
              ) : (
                <ul className="space-y-1">
                  {data.processors.map((member) => (
                    <li key={member.id} className="flex items-center justify-between gap-3">
                      <Person member={member} />
                      {canChange ? (
                        <Button
                          type="button"
                          size="icon-sm"
                          variant="ghost"
                          aria-label={`Remove ${member.name}`}
                          onClick={() => run(() => remove.mutateAsync(member.id))}
                        >
                          <X className="h-3.5 w-3.5" />
                        </Button>
                      ) : null}
                    </li>
                  ))}
                </ul>
              )}
              {canChange ? (
                <Picker
                  label="Add processor"
                  people={addable}
                  placeholder="Add processor…"
                  hint="Only active people with the Processor role."
                  onPick={(userId) => (userId ? run(() => add.mutateAsync(userId)) : undefined)}
                />
              ) : null}
            </section>
          </>
        )}
      </CardContent>
    </Card>
  );
}

function Person({ member, licensing = false }: { member: TeamMember; licensing?: boolean }) {
  const details = [
    member.email,
    licensing && member.nmls_id ? `NMLS ${member.nmls_id}` : null,
    licensing && member.licensed_states.length ? member.licensed_states.join(", ") : null,
  ].filter(Boolean);
  return (
    <div className="min-w-0">
      <p className="text-sm text-foreground">{member.name}</p>
      <p className="truncate text-xs text-muted-foreground">{details.join(" · ")}</p>
    </div>
  );
}

/** A select of people with their current file load; picking one acts at once. */
function Picker({
  label,
  people,
  placeholder,
  hint,
  clearLabel,
  onPick,
  onCancel,
}: {
  label: string;
  people: AssignablePerson[];
  placeholder: string;
  hint: string;
  /** Offer "none" as a choice (clearing the slot). */
  clearLabel?: string;
  onPick: (userId: string | null) => void;
  onCancel?: () => void;
}) {
  const CLEAR = "__none__";
  return (
    <div className="space-y-1">
      <div className="flex items-center gap-2">
        <Select
          aria-label={label}
          className="w-64"
          value=""
          onChange={(event) => {
            const value = event.target.value;
            if (value) onPick(value === CLEAR ? null : value);
          }}
        >
          <option value="">{placeholder}</option>
          {people.map((person) => (
            <option key={person.id} value={person.id}>
              {person.name} · {person.file_count} {person.file_count === 1 ? "file" : "files"}
            </option>
          ))}
          {clearLabel ? <option value={CLEAR}>{clearLabel}</option> : null}
        </Select>
        {onCancel ? (
          <Button type="button" size="sm" variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
        ) : null}
      </div>
      <p className="text-xs text-muted-foreground">{hint}</p>
    </div>
  );
}
