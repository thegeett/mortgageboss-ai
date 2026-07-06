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
import type { LenderOverlayView } from "@/lib/types/overlay-admin";
import { ArrowLeft, ArrowRight, Plus, Trash2 } from "lucide-react";
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

const CAPTION = "text-[11px] font-semibold uppercase tracking-wide text-gray-400";

export default function EditLenderOverlayPage() {
  const { id } = useParams<{ id: string }>();
  const role = useAuthStore((state) => state.user?.role);
  const { data, isPending, isError, refetch } = useLenderOverlay(id);

  if (role !== "admin") {
    return (
      <div className="rounded-lg border border-dashed border-gray-300 bg-white px-6 py-16 text-center text-sm text-gray-500">
        Lender overlays are available to admins only.
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <Link
        href="/admin/lenders"
        className="inline-flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-800"
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
      <div>
        <h2 className="text-2xl font-bold tracking-tight text-gray-900">{view.name}</h2>
        <p className="mt-1 text-sm text-gray-500">
          Overlay overrides — the lender&apos;s deviations from the investor default. Editing a
          threshold changes what enforcement uses for this lender.
        </p>
      </div>

      {/* The overrides */}
      <div className="space-y-3 rounded-lg border border-gray-200 bg-white p-4">
        {rows.length === 0 && (
          <p className="text-sm text-gray-400">No overrides yet — add one below.</p>
        )}
        {rows.map((row) => {
          const base = baseFor(row.rule_id);
          return (
            <div
              key={row.uid}
              className="grid gap-2 border-b border-gray-100 pb-3 last:border-0 sm:grid-cols-12"
            >
              <div className="sm:col-span-5">
                <span className={CAPTION}>Rule id</span>
                <Input
                  value={row.rule_id}
                  readOnly={!row.isNew}
                  placeholder="e.g. conv.dti.back_end_max"
                  aria-label="Rule id"
                  onChange={(e) => setRow(row.uid, { rule_id: e.target.value })}
                  className="mt-0.5 h-8 font-mono text-xs"
                />
                {/* Effect-legible: investor base → lender effective. */}
                {base !== null && (
                  <p className="mt-1 flex items-center gap-1 text-[11px] text-gray-500">
                    base {base} <ArrowRight className="h-3 w-3" />{" "}
                    <span className="font-semibold text-primary">{row.value || "—"}</span>
                  </p>
                )}
              </div>
              <div className="sm:col-span-2">
                <span className={CAPTION}>Value</span>
                <Input
                  value={row.value}
                  inputMode="decimal"
                  aria-label="Override value"
                  onChange={(e) => setRow(row.uid, { value: e.target.value })}
                  className="mt-0.5 h-8 text-right text-sm tabular-nums"
                />
              </div>
              <div className="sm:col-span-4">
                <span className={CAPTION}>Reason</span>
                <Input
                  value={row.reason}
                  placeholder="Why this lender deviates"
                  aria-label="Override reason"
                  onChange={(e) => setRow(row.uid, { reason: e.target.value })}
                  className="mt-0.5 h-8 text-sm"
                />
              </div>
              <div className="flex items-end sm:col-span-1">
                <Button
                  size="icon"
                  variant="ghost"
                  className="h-8 w-8 text-gray-400 hover:text-danger"
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
      <div className="space-y-2 rounded-lg border border-gray-200 bg-gray-50/60 p-4">
        <label htmlFor="change-reason" className="text-xs font-semibold text-gray-700">
          Reason for this change <span className="text-danger">*</span>
        </label>
        <Input
          id="change-reason"
          value={reason}
          placeholder="Required — recorded in the audit trail"
          onChange={(e) => setReason(e.target.value)}
          className="h-9 text-sm"
        />
        {error && <p className="text-sm text-danger">{error}</p>}
        <div className="flex justify-end">
          <Button onClick={onSave} disabled={!reason.trim() || update.isPending}>
            {update.isPending ? "Saving…" : "Save overlay"}
          </Button>
        </div>
      </div>

      {/* The audit trail */}
      {view.audit.length > 0 && (
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-400">
            Audit trail
          </h3>
          <ul className="space-y-2">
            {view.audit.map((entry) => (
              <li
                key={`${entry.at}-${entry.reason}`}
                className="border-l-2 border-gray-200 pl-3 text-sm"
              >
                <div className="text-gray-700">{entry.reason}</div>
                <div className="text-[11px] text-gray-400">{entry.at}</div>
                {entry.changes.map((c) => (
                  <div key={c.field} className="font-mono text-[11px] text-gray-500">
                    {c.field}: {c.from ?? "—"} → {c.to ?? "—"}
                  </div>
                ))}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
