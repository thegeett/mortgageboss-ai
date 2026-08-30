"use client";

/**
 * Edit a lender's overlay (LP-87) — the admin UI over LP-80's storage.
 *
 * View each override with its effect made legible (investor base → lender effective), edit the
 * threshold + this override's reason, add/remove overrides, and save with a REQUIRED change
 * reason. The edit is audited (from→to, who, when) — shown in the audit trail below. Admin-only
 * (the backend gates it); a save returns the recomposed effect-legible view.
 */

import { Button } from "@/components/ui/button";
import { InlineErrorState } from "@/components/ui/error-state";
import { Input } from "@/components/ui/input";
import { SkeletonText } from "@/components/ui/skeleton";
import { useLenderOverlay, useUpdateLenderOverlay } from "@/lib/api/overlay-admin";
import { useAuthStore } from "@/lib/stores/auth-store";
import type { LenderOverlayView, OverlayAuditChange } from "@/lib/types/overlay-admin";
import { formatDistanceToNow } from "date-fns";
import { ArrowLeft, Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";

interface Row {
  uid: number;
  rule_id: string;
  value: string;
  reason: string;
  isNew: boolean;
}

const CAPTION = "text-[11px] font-semibold uppercase tracking-wide text-muted-foreground";

/**
 * One change, as a sentence (LP-UI-026).
 *
 * The three cases are genuinely different and a `from → to` renders them
 * identically: adding an override, removing one, and moving one are three things
 * an admin does for three reasons. `field_label` is the rule's description, and
 * falls back to the id — which at least identifies what moved — for a rule the
 * catalog no longer carries.
 */
function describe(change: OverlayAuditChange): string {
  // A rule description is a full sentence ("Income/credit documents are no more
  // than 4 months old on the note date."), and embedding one mid-sentence read
  // "set Income/credit documents are no more ... on the note date. to 90." The
  // trailing stop goes and the name is quoted, so it reads as the name of a thing
  // rather than as a clause that ended early. The rule id needs neither.
  const rule = change.field_label ? `“${change.field_label.replace(/\.$/, "")}”` : change.field;
  if (change.from === null && change.to !== null) return `set ${rule} to ${change.to}`;
  if (change.from !== null && change.to === null) {
    return `removed the override on ${rule}, which was ${change.from}`;
  }
  return `changed ${rule} from ${change.from} to ${change.to}`;
}

/** A stored ISO timestamp as something a person reads. */
function when(iso: string): string {
  try {
    return formatDistanceToNow(new Date(iso), { addSuffix: true });
  } catch {
    // A hand-edited blob can hold anything; the entry is still worth showing.
    return "at an unrecorded time";
  }
}

export default function EditLenderOverlayPage() {
  const { id } = useParams<{ id: string }>();
  const role = useAuthStore((state) => state.user?.role);
  const { data, isPending, isError, refetch } = useLenderOverlay(id);

  if (role !== "admin") {
    return (
      <div className="rounded-lg border border-dashed border-input bg-card px-6 py-16 text-center text-sm text-muted-foreground">
        Lender overlays are available to admins only.
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <Link
        href="/admin/lenders"
        className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="h-4 w-4" /> All lenders
      </Link>
      {isPending ? (
        <SkeletonText lines={6} />
      ) : isError || !data ? (
        <InlineErrorState message="Couldn't load this overlay." onRetry={() => void refetch()} />
      ) : (
        <OverlayEditor view={data} lenderId={id} />
      )}
    </div>
  );
}

function OverlayEditor({ view, lenderId }: { view: LenderOverlayView; lenderId: string }) {
  const update = useUpdateLenderOverlay(lenderId);
  const counter = useRef(0);
  const [rows, setRows] = useState<Row[]>([]);
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);

  // Seed from the (latest saved) server view — re-seeds after a successful save.
  useEffect(() => {
    setRows(
      view.overrides.map((o) => ({
        uid: counter.current++,
        rule_id: o.rule_id,
        value: o.effective_value,
        reason: o.reason ?? "",
        isNew: false,
      })),
    );
    setReason("");
  }, [view]);

  const baseFor = (ruleId: string): string | null =>
    view.overrides.find((o) => o.rule_id === ruleId)?.base_value ?? null;
  const labelFor = (ruleId: string): string | null =>
    view.overrides.find((o) => o.rule_id === ruleId)?.rule_description ?? null;
  const unitFor = (ruleId: string): string | null =>
    view.overrides.find((o) => o.rule_id === ruleId)?.unit ?? null;

  const setRow = (uid: number, patch: Partial<Row>) =>
    setRows((rs) => rs.map((r) => (r.uid === uid ? { ...r, ...patch } : r)));

  const onSave = () => {
    setError(null);
    update.mutate(
      {
        overrides: rows
          .filter((r) => r.rule_id.trim() && r.value.trim())
          .map((r) => ({
            rule_id: r.rule_id.trim(),
            value: r.value.trim(),
            reason: r.reason || null,
          })),
        reason,
      },
      {
        onError: (e: unknown) => {
          const detail =
            (e as { response?: { data?: { error?: { message?: string } } } })?.response?.data?.error
              ?.message ?? "Couldn't save the overlay.";
          setError(detail);
        },
      },
    );
  };

  return (
    <div className="space-y-6">
      <header>
        <h2 className="text-label uppercase text-muted-foreground">{view.name}</h2>
        <p className="mt-1 max-w-prose text-sm text-muted-foreground">
          Where this lender deviates from the investor default. Each override is stored with a
          reason and recorded in the audit trail below.
        </p>
        {/* THE SENTENCE THIS REPLACES SAID "editing a threshold changes what
            enforcement uses for this lender", and that is not true today. The
            rule engine builds its overlays from `SAMPLE_OVERLAYS` and
            `STARTER_OVERLAYS` — hardcoded dicts keyed by slug — and nothing
            constructs a LenderOverlay from `lenders.lender_overlays`, the column
            this editor writes. LP-87 built the editor half of ADR-193's
            deferral; the reading half is not built.

            Verified before writing this, not assumed: `default_registry()` in
            verification/registry.py, and `lender_overlays` appears nowhere in the
            engine. A screen that tells an admin their change is in force when it
            is not is the worst thing this editor could do, so it says what is
            actually true and no more. DELETE THIS NOTICE WHEN THE COLUMN IS
            WIRED — it is a statement about today, not a permanent caveat. */}
        <p className="mt-2 max-w-prose border-l-2 border-l-warning py-1 pl-3 text-sm text-foreground-2">
          <span className="font-medium text-foreground">Recorded, not yet applied.</span> Overrides
          saved here are stored and audited, and the rule engine does not read them yet — it runs
          the investor defaults for every lender. Nothing on a loan file changes until that wiring
          lands.
        </p>
      </header>

      {/* The overrides */}
      <div className="space-y-3 rounded-lg border border-border bg-card p-4">
        {rows.length === 0 && (
          <p className="text-sm text-muted-foreground">No overrides yet — add one below.</p>
        )}
        {rows.map((row) => {
          const base = baseFor(row.rule_id);
          const label = labelFor(row.rule_id);
          const unit = unitFor(row.rule_id);
          return (
            <div
              key={row.uid}
              className="grid gap-2 border-b border-border pb-3 last:border-0 sm:grid-cols-12"
            >
              <div className="sm:col-span-4">
                <span className={CAPTION}>Rule</span>
                <Input
                  value={row.rule_id}
                  readOnly={!row.isNew}
                  placeholder="e.g. conv.dti.back_end_max"
                  aria-label="Rule id"
                  onChange={(e) => setRow(row.uid, { rule_id: e.target.value })}
                  className="mt-0.5 h-8 font-mono md:text-xs"
                />
                {label !== null ? (
                  <p className="mt-1 text-[11px] text-muted-foreground">{label}</p>
                ) : null}
              </div>

              {/* BASE AND EFFECTIVE SIDE BY SIDE, as two columns rather than a
                  caption under the id. The whole point of the screen is that the
                  effect of a change is legible without opening the audit trail,
                  and a value you have to compare against a footnote is not. */}
              <div className="sm:col-span-2">
                <span className={CAPTION}>Agency base</span>
                <p className="mt-0.5 flex h-8 items-center tabular-nums text-foreground-2">
                  {base ?? "—"}
                  {unit ? <span className="ml-1 text-muted-foreground">{unit}</span> : null}
                </p>
              </div>
              <div className="sm:col-span-2">
                <span className={CAPTION}>This lender</span>
                <Input
                  value={row.value}
                  inputMode="decimal"
                  aria-label="Override value"
                  onChange={(e) => setRow(row.uid, { value: e.target.value })}
                  className="mt-0.5 h-8 tabular-nums"
                />
              </div>
              <div className="sm:col-span-3">
                <span className={CAPTION}>Reason</span>
                <Input
                  value={row.reason}
                  placeholder="Why this lender deviates"
                  aria-label="Override reason"
                  onChange={(e) => setRow(row.uid, { reason: e.target.value })}
                  className="mt-0.5 h-8"
                />
              </div>
              <div className="flex items-end sm:col-span-1">
                <Button
                  size="icon"
                  variant="ghost"
                  className="text-muted-foreground hover:text-danger"
                  aria-label="Remove override"
                  onClick={() => setRows((rs) => rs.filter((r) => r.uid !== row.uid))}
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
            </div>
          );
        })}
        <Button
          variant="outline"
          size="sm"
          onClick={() =>
            setRows((rs) => [
              ...rs,
              { uid: counter.current++, rule_id: "", value: "", reason: "", isNew: true },
            ])
          }
        >
          <Plus className="mr-1.5 h-4 w-4" /> Add override
        </Button>
      </div>

      {/* The required change reason + save */}
      <div className="space-y-2 rounded-lg border border-border bg-muted/60 p-4">
        <label htmlFor="change-reason" className="text-xs font-semibold text-foreground-2">
          Reason for this change <span className="text-danger">*</span>
        </label>
        <Input
          id="change-reason"
          value={reason}
          placeholder="Required — recorded in the audit trail"
          onChange={(e) => setReason(e.target.value)}
          className="h-9"
        />
        {error && <p className="text-sm text-danger">{error}</p>}
        <div className="flex justify-end">
          <Button onClick={onSave} disabled={!reason.trim() || update.isPending}>
            {update.isPending ? "Saving…" : "Save overlay"}
          </Button>
        </div>
      </div>

      {/* THE CHANGE HISTORY, AS PROSE. It read `conv.income.credit_doc_age: 90
          → 120` in mono beside a raw ISO timestamp — a diff dump, which is what
          the ticket asks this not to be. Same facts, said as sentences: who,
          what moved, and why. */}
      {view.audit.length > 0 && (
        <section aria-labelledby="overlay-history">
          <h3 id="overlay-history" className="text-label uppercase text-muted-foreground">
            Change history
          </h3>
          <ul className="mt-2 space-y-3">
            {view.audit.map((entry) => (
              <li key={`${entry.at}-${entry.reason}`} className="text-sm">
                <p className="text-foreground-2">
                  <span className="font-medium text-foreground">
                    {entry.actor_name ?? "Someone"}
                  </span>{" "}
                  {entry.changes.length > 0
                    ? entry.changes.map((c, i) => (
                        <span key={c.field}>
                          {i > 0 ? ", and " : ""}
                          {describe(c)}
                        </span>
                      ))
                    : "saved the overlay with no threshold changes"}
                  .
                </p>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  {when(entry.at)} — {entry.reason}
                </p>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
