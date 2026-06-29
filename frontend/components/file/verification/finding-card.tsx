"use client";

/**
 * One finding in the verification tab (LP-81) — the trust + resolution unit.
 *
 * Shows a **templated headline** for known types (reads identically every run; the
 * AI's free-form wording is secondary detail), the severity / type / confidence, and
 * the **source location** (click → the document page + verbatim snippet — the trust
 * mechanism). Open findings carry the core resolution actions: Apply (incorporate →
 * recompute), Override (with a required reason), Add note. Resolved findings show
 * their resolution + reason/record (history — never silently dropped).
 */

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { Textarea } from "@/components/ui/textarea";
import { formatPercent, humanize } from "@/lib/format";
import type { VerificationFinding } from "@/lib/types/verification";
import { cn } from "@/lib/utils";
import {
  canApply,
  findingDetail,
  findingHeadline,
  findingTypeLabel,
} from "@/lib/verification/finding-display";
import { Check, ChevronDown, FileText, MessageSquarePlus, X } from "lucide-react";
import { useId, useState } from "react";

interface Note {
  note: string;
  at?: string;
}

export function FindingCard({
  finding,
  busy = false,
  onApply,
  onOverride,
  onNote,
}: {
  finding: VerificationFinding;
  busy?: boolean;
  onApply?: () => void;
  onOverride?: (reason: string) => void;
  onNote?: (note: string) => void;
}) {
  const fieldId = useId();
  const [expanded, setExpanded] = useState(false);
  const [form, setForm] = useState<"override" | "note" | null>(null);
  const [text, setText] = useState("");

  const red = finding.status === "red";
  const resolved = finding.resolution_status !== "open";
  const headline = findingHeadline(finding);
  const detail = findingDetail(finding);
  const reasoning = (finding.details as { reasoning?: string }).reasoning ?? null;
  const notes = ((finding.details as { notes?: Note[] }).notes ?? []).filter(Boolean);
  const hasSource = finding.source_page !== null || Boolean(finding.source_snippet);

  function submit() {
    const value = text.trim();
    if (!value) return;
    if (form === "override") onOverride?.(value);
    else if (form === "note") onNote?.(value);
    setForm(null);
    setText("");
  }

  return (
    <li className="rounded-lg border border-gray-200 px-3 py-2.5">
      <div className="flex items-start gap-2.5">
        <span
          className={cn(
            "mt-1.5 h-2 w-2 shrink-0 rounded-full",
            red ? "bg-destructive" : "bg-warning",
          )}
          aria-hidden
        />
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-2">
            <span className="text-sm font-medium text-gray-900">{headline}</span>
            <Badge
              variant="outline"
              className={cn(
                "shrink-0 font-normal",
                resolved ? "border-success/40 text-success" : "text-gray-500",
              )}
            >
              {humanize(finding.resolution_status)}
            </Badge>
          </div>

          {/* The AI's free-form description, secondary to the templated headline. */}
          {detail && <p className="mt-0.5 text-xs text-gray-500">{detail}</p>}

          <div className="mt-1 flex flex-wrap items-center gap-x-2 text-[11px] text-gray-400">
            <span>{findingTypeLabel(finding)}</span>
            <span>· {formatPercent(String(finding.confidence * 100))} confidence</span>
            <span>· {finding.origin === "deterministic_rule" ? "rule" : "AI cross-source"}</span>
            {hasSource && (
              <button
                type="button"
                onClick={() => setExpanded((e) => !e)}
                className="inline-flex items-center gap-0.5 text-primary hover:underline"
                aria-expanded={expanded}
              >
                <FileText className="h-3 w-3" />
                {finding.source_page !== null ? `Source · p.${finding.source_page}` : "Source"}
                <ChevronDown
                  className={cn("h-3 w-3 transition-transform", expanded && "rotate-180")}
                />
              </button>
            )}
          </div>

          {/* Source location — the trust mechanism: the verbatim document line. */}
          {expanded && hasSource && (
            <div className="mt-2 space-y-1 rounded-md bg-gray-50 px-2.5 py-2 text-[11px]">
              {finding.source_page !== null && (
                <p className="text-gray-500">Document page {finding.source_page}</p>
              )}
              {finding.source_snippet && (
                <p className="font-mono text-gray-600">“{finding.source_snippet}”</p>
              )}
              {reasoning && <p className="text-gray-500">{reasoning}</p>}
            </div>
          )}

          {/* Notes (informational annotations). */}
          {notes.length > 0 && (
            <ul className="mt-2 space-y-1">
              {notes.map((n, i) => (
                <li
                  key={`${n.at ?? i}`}
                  className="flex items-start gap-1.5 text-[11px] text-gray-500"
                >
                  <MessageSquarePlus className="mt-0.5 h-3 w-3 shrink-0 text-gray-300" />
                  <span>{n.note}</span>
                </li>
              ))}
            </ul>
          )}

          {/* Resolution actions (open findings only). */}
          {!resolved && (onApply || onOverride || onNote) && (
            <div className="mt-2.5">
              {form === null ? (
                <div className="flex flex-wrap items-center gap-1.5">
                  {onApply && canApply(finding) && (
                    <Button
                      type="button"
                      size="sm"
                      className="h-7 gap-1 text-xs"
                      disabled={busy}
                      onClick={onApply}
                    >
                      {busy ? <Spinner className="h-3 w-3" /> : <Check className="h-3 w-3" />}
                      Apply
                    </Button>
                  )}
                  {onOverride && (
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      className="h-7 text-xs"
                      disabled={busy}
                      onClick={() => {
                        setForm("override");
                        setText("");
                      }}
                    >
                      Override…
                    </Button>
                  )}
                  {onNote && (
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      className="h-7 gap-1 text-xs text-gray-500"
                      disabled={busy}
                      onClick={() => {
                        setForm("note");
                        setText("");
                      }}
                    >
                      <MessageSquarePlus className="h-3 w-3" /> Add note
                    </Button>
                  )}
                </div>
              ) : (
                <div className="space-y-1.5">
                  <label htmlFor={fieldId} className="text-[11px] font-medium text-gray-500">
                    {form === "override" ? "Reason for dismissing (required)" : "Note"}
                  </label>
                  <Textarea
                    id={fieldId}
                    value={text}
                    onChange={(e) => setText(e.target.value)}
                    rows={2}
                    className="text-sm"
                    placeholder={
                      form === "override"
                        ? "e.g. already disclosed on the 1003; documented separately"
                        : "Add context for the file…"
                    }
                  />
                  <div className="flex items-center gap-1.5">
                    <Button
                      type="button"
                      size="sm"
                      className="h-7 gap-1 text-xs"
                      disabled={busy || text.trim() === ""}
                      onClick={submit}
                    >
                      {busy ? <Spinner className="h-3 w-3" /> : <Check className="h-3 w-3" />}
                      {form === "override" ? "Override" : "Save note"}
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      className="h-7 gap-1 text-xs text-gray-500"
                      disabled={busy}
                      onClick={() => setForm(null)}
                    >
                      <X className="h-3 w-3" /> Cancel
                    </Button>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Resolved: the recorded reason (override) for the audit trail. */}
          {resolved && finding.resolution_status === "overridden" && (
            <p className="mt-1.5 text-[11px] text-gray-500">
              <span className="text-gray-400">Reason: </span>
              {finding.resolution_note ?? "—"}
            </p>
          )}
        </div>
      </div>
    </li>
  );
}
