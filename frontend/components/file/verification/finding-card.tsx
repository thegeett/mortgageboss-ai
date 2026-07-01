"use client";

/**
 * One finding in the verification tab (LP-81 + LP-88) — the trust + disposition unit.
 *
 * Shows a **templated headline** for known types (reads identically every run; the AI's
 * free-form wording is secondary detail), the severity / type / confidence, the
 * **source-origin** (deterministic rule = stable/certain vs AI cross-source = the novel
 * frontier, LP-86), the lender **overlay** that adjusted it (LP-80), and the **source
 * location** (click → the document page + verbatim snippet — the trust mechanism). Open
 * findings carry the full action set: Apply, Override (required reason), Add note, plus
 * **Accept-risk** (acknowledge a real finding — FHA compensating-factors / subject-to-repair,
 * LP-84/85) and **Request-docs** (create a needs item). Resolved findings show their
 * disposition + reason/record (history — never silently dropped).
 */

import { ViewFixDialog } from "@/components/file/verification/view-fix-dialog";
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
import {
  Check,
  ChevronDown,
  FileText,
  MessageSquarePlus,
  Send,
  ShieldCheck,
  Sparkles,
  Wrench,
  X,
} from "lucide-react";
import { type ReactNode, useId, useState } from "react";

interface Note {
  note: string;
  at?: string;
}

type FormKind = "override" | "note" | "accept" | "request";

export function FindingCard({
  finding,
  fileId,
  busy = false,
  onApply,
  onOverride,
  onNote,
  onAcceptRisk,
  onRequestDocs,
}: {
  finding: VerificationFinding;
  fileId?: string;
  busy?: boolean;
  onApply?: () => void;
  onOverride?: (reason: string) => void;
  onNote?: (note: string) => void;
  onAcceptRisk?: (reason: string) => void;
  onRequestDocs?: (note: string) => void;
}) {
  const fieldId = useId();
  const [expanded, setExpanded] = useState(false);
  const [form, setForm] = useState<FormKind | null>(null);
  const [text, setText] = useState("");
  const [viewFixOpen, setViewFixOpen] = useState(false);

  const red = finding.status === "red";
  const resolved = finding.resolution_status !== "open";
  const headline = findingHeadline(finding);
  const detail = findingDetail(finding);
  const details = finding.details as {
    reasoning?: string;
    notes?: Note[];
    overlay_applied?: string | null;
    docs_requested?: { needs_item_id?: string } | null;
    why_it_matters?: string | null;
    suggested_fix?: string | null;
    guidance_starter?: boolean;
  };
  const reasoning = details.reasoning ?? null;
  const notes = (details.notes ?? []).filter(Boolean);
  const overlay = details.overlay_applied ?? null;
  const docsRequested = Boolean(details.docs_requested);
  const deterministic = finding.origin === "deterministic_rule";
  const hasSource = finding.source_page !== null || Boolean(finding.source_snippet);
  // The AI-generated why/fix (LP-96). The block renders ONLY when populated, so the card still
  // looks complete + intentional when it's absent (LP-95 graceful degradation). It is visually
  // distinct + warned because it's the AI's fallible explanation, not the deterministic core.
  const whyItMatters = details.why_it_matters?.trim() || null;
  const suggestedFix = details.suggested_fix?.trim() || null;
  const guidanceStarter = details.guidance_starter !== false; // grounded-starter by default
  // The full "what we found" (the deterministic explanation) + the collapsed one-liner. For a
  // templated AI finding the one-liner is the AI's specifics (`detail`); for a deterministic
  // finding the headline already carries the specifics, so the one-liner is omitted (no dup).
  const whatWeFound = reasoning ?? detail ?? headline;
  const collapsedWhat = detail ?? (reasoning && reasoning !== headline ? reasoning : null);
  const authority = `${findingTypeLabel(finding)} · ${deterministic ? "deterministic rule" : "AI cross-source"}`;

  function openForm(kind: FormKind) {
    setForm(kind);
    setText("");
  }

  function submit() {
    const value = text.trim();
    // Override requires a reason; accept-risk + request-docs + note allow empty.
    if (form === "override") {
      if (!value) return;
      onOverride?.(value);
    } else if (form === "note") {
      if (!value) return;
      onNote?.(value);
    } else if (form === "accept") {
      onAcceptRisk?.(value);
    } else if (form === "request") {
      onRequestDocs?.(value);
    }
    setForm(null);
    setText("");
  }

  const FORM_META: Record<FormKind, { label: string; submit: string; placeholder: string }> = {
    override: {
      label: "Reason for dismissing (required)",
      submit: "Override",
      placeholder: "e.g. already disclosed on the 1003; documented separately",
    },
    note: { label: "Note", submit: "Save note", placeholder: "Add context for the file…" },
    accept: {
      label: "Compensating factor / accepted-risk rationale (optional)",
      submit: "Accept risk",
      placeholder: "e.g. 6 months reserves; subject-to-repair re-inspection scheduled",
    },
    request: {
      label: "What to request (optional)",
      submit: "Request docs",
      placeholder: "e.g. the 2024 W-2; a letter of explanation",
    },
  };

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
            {resolved && (
              <Badge
                variant="outline"
                className="shrink-0 border-success/40 font-normal text-success"
              >
                {humanize(finding.resolution_status)}
              </Badge>
            )}
          </div>

          {/* Collapsed one-line "What we found" — the specifics, kept scannable (single line). */}
          {collapsedWhat && (
            <p className="mt-0.5 line-clamp-1 text-xs text-gray-500">{collapsedWhat}</p>
          )}

          <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-gray-400">
            <span>{findingTypeLabel(finding)}</span>
            <span>· {formatPercent(String(finding.confidence * 100))} confidence</span>
            {/* Source-origin (LP-86): deterministic = stable/certain; AI = the novel frontier. */}
            <span
              className={cn(
                "rounded px-1 py-px font-medium",
                deterministic ? "bg-primary/10 text-primary" : "bg-info/10 text-info",
              )}
            >
              {deterministic ? "deterministic" : "AI · novel"}
            </span>
            {/* Lender overlay provenance (LP-80) — lender-specific result. */}
            {overlay && (
              <span className="rounded bg-gray-100 px-1 py-px font-medium text-gray-500">
                {overlay} overlay
              </span>
            )}
            {docsRequested && (
              <span className="inline-flex items-center gap-0.5 rounded bg-info/10 px-1 py-px font-medium text-info">
                <Send className="h-2.5 w-2.5" /> docs requested
              </span>
            )}
            {/* Progressive disclosure — one "Details" affordance reveals the full four-part
                (What we found / Why it matters / Suggested fix / Source). Open findings only;
                resolved findings render compact. */}
            {!resolved && (
              <button
                type="button"
                onClick={() => setExpanded((e) => !e)}
                className="inline-flex items-center gap-0.5 text-primary hover:underline"
                aria-expanded={expanded}
              >
                <FileText className="h-3 w-3" />
                {hasSource && finding.source_page !== null
                  ? `Details · source p.${finding.source_page}`
                  : "Details"}
                <ChevronDown
                  className={cn("h-3 w-3 transition-transform", expanded && "rotate-180")}
                />
              </button>
            )}
          </div>

          {/* The four-part detail on expand. What-we-found + Source are DETERMINISTIC (always
              shown); Why-it-matters + Suggested-fix are AI slots (LP-96) that render ONLY when
              populated — so today the card looks complete with just the deterministic content. */}
          {expanded && !resolved && (
            <div className="mt-2 space-y-2 rounded-md border border-gray-100 bg-gray-50/70 px-2.5 py-2">
              <FindingSection title="What we found">
                <p className="text-gray-600">{whatWeFound}</p>
              </FindingSection>

              {/* The AI-generated Why-it-matters + Suggested-fix (LP-96) — VISUALLY DISTINCT from
                  the deterministic core (tinted + bordered + iconned) and WARNED, because it's the
                  AI's fallible explanation. Renders only when populated (graceful — LP-95). */}
              {(whyItMatters || suggestedFix) && (
                <div className="rounded-md border border-warning/40 bg-warning/5 px-2.5 py-2">
                  <div className="flex items-center gap-1 text-[10px] font-medium text-warning">
                    <Sparkles className="h-3 w-3 shrink-0" />
                    AI-generated — verify before relying on this; it may be wrong.
                  </div>
                  {whyItMatters && (
                    <div className="mt-1.5">
                      <h5 className="text-[10px] font-semibold uppercase tracking-wide text-gray-500">
                        Why it matters
                      </h5>
                      <p className="mt-0.5 text-xs text-gray-700">{whyItMatters}</p>
                    </div>
                  )}
                  {suggestedFix && (
                    <div className="mt-1.5">
                      <h5 className="text-[10px] font-semibold uppercase tracking-wide text-gray-500">
                        Suggested fix
                      </h5>
                      <p className="mt-0.5 text-xs text-gray-700">{suggestedFix}</p>
                    </div>
                  )}
                  {guidanceStarter && (
                    <p className="mt-1.5 text-[10px] text-gray-400">
                      Grounded starter — pending expert review.
                    </p>
                  )}
                </div>
              )}

              <FindingSection title="Source">
                {hasSource ? (
                  <div className="space-y-0.5">
                    {finding.source_page !== null && (
                      <p className="text-gray-500">Document page {finding.source_page}</p>
                    )}
                    {finding.source_snippet && (
                      <p className="font-mono text-gray-600">
                        &ldquo;{finding.source_snippet}&rdquo;
                      </p>
                    )}
                    <p className="text-gray-400">{authority}</p>
                  </div>
                ) : (
                  <p className="text-gray-400">No single document line — {authority}.</p>
                )}
              </FindingSection>
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

          {/* The full action set (open findings only). */}
          {!resolved && (onApply || onOverride || onNote || onAcceptRisk || onRequestDocs) && (
            <div className="mt-2.5">
              {form === null ? (
                <div className="flex flex-wrap items-center gap-1.5">
                  {/* Apply-spec findings get "View fix" — a detailed before/after impact preview
                      (LP-97) — instead of a bare Apply. The dialog's "Apply fix" runs the real
                      apply (onApply); the preview is a dry-run that matches it. */}
                  {onApply && canApply(finding) && fileId && (
                    <Button
                      type="button"
                      size="sm"
                      className="h-7 gap-1 text-xs"
                      disabled={busy}
                      onClick={() => setViewFixOpen(true)}
                    >
                      <Wrench className="h-3 w-3" /> View fix
                    </Button>
                  )}
                  {onAcceptRisk && (
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      className="h-7 gap-1 text-xs"
                      disabled={busy}
                      onClick={() => openForm("accept")}
                    >
                      <ShieldCheck className="h-3 w-3" /> Accept risk
                    </Button>
                  )}
                  {onRequestDocs && (
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      className="h-7 gap-1 text-xs"
                      disabled={busy || docsRequested}
                      onClick={() => openForm("request")}
                    >
                      <Send className="h-3 w-3" /> {docsRequested ? "Requested" : "Request docs"}
                    </Button>
                  )}
                  {onOverride && (
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      className="h-7 text-xs"
                      disabled={busy}
                      onClick={() => openForm("override")}
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
                      onClick={() => openForm("note")}
                    >
                      <MessageSquarePlus className="h-3 w-3" /> Add note
                    </Button>
                  )}
                </div>
              ) : (
                <div className="space-y-1.5">
                  <label htmlFor={fieldId} className="text-[11px] font-medium text-gray-500">
                    {FORM_META[form].label}
                  </label>
                  <Textarea
                    id={fieldId}
                    value={text}
                    onChange={(e) => setText(e.target.value)}
                    rows={2}
                    className="text-sm"
                    placeholder={FORM_META[form].placeholder}
                  />
                  <div className="flex items-center gap-1.5">
                    <Button
                      type="button"
                      size="sm"
                      className="h-7 gap-1 text-xs"
                      disabled={busy || (form === "override" && text.trim() === "")}
                      onClick={submit}
                    >
                      {busy ? <Spinner className="h-3 w-3" /> : <Check className="h-3 w-3" />}
                      {FORM_META[form].submit}
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

          {/* Resolved renders COMPACT: the disposition + what was done (the audit trail). */}
          {resolved && (
            <p className="mt-1.5 text-[11px] text-gray-500">
              {finding.resolution_status === "applied" ? (
                <span className="text-gray-400">Applied — incorporated into the file.</span>
              ) : finding.resolution_status === "overridden" ||
                finding.resolution_status === "accepted_risk" ? (
                <>
                  <span className="text-gray-400">
                    {finding.resolution_status === "accepted_risk" ? "Accepted: " : "Reason: "}
                  </span>
                  {finding.resolution_note ?? "—"}
                </>
              ) : (
                <span className="text-gray-400">{humanize(finding.resolution_status)}</span>
              )}
            </p>
          )}
        </div>
      </div>

      {/* View fix — the itemized before/after impact preview (LP-97). Only for apply-spec
          findings; "Apply fix" runs the real apply (onApply). */}
      {fileId && onApply && canApply(finding) && (
        <ViewFixDialog
          open={viewFixOpen}
          onOpenChange={setViewFixOpen}
          fileId={fileId}
          finding={finding}
          onApply={onApply}
          busy={busy}
        />
      )}
    </li>
  );
}

/** One labelled section of the expanded four-part card (LP-95). Renders a small heading + body
 * so LP-96's Why-it-matters / Suggested-fix content drops into a clearly-delineated slot. */
function FindingSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div>
      <h5 className="text-[10px] font-semibold uppercase tracking-wide text-gray-400">{title}</h5>
      <div className="mt-0.5 text-xs">{children}</div>
    </div>
  );
}
