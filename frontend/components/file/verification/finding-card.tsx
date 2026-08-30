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
import { resolutionLabel } from "@/lib/verification/rule-findings";
import {
  Check,
  ChevronDown,
  FileText,
  MessageSquarePlus,
  RotateCcw,
  Send,
  ShieldCheck,
  Sparkles,
  Wrench,
  X,
} from "lucide-react";
import Link from "next/link";
import { type ReactNode, useId, useState } from "react";

/**
 * The finding's SOURCE DOCUMENTS (LP-114 → LP-114.1) — names ALL the documents that derived the
 * finding (a cross-source finding spans several: a pay stub AND a W-2 for one employer), so a
 * processor can verify the judgment against every one. Each name links to open that document — the
 * ?doc= param, which LP-UI-041 redirects to the REVIEWER rather than the details drawer, because a
 * provenance link means "show me the document this came from" — when the file id is known;
 * otherwise it's text.
 * Renders nothing when no source could be attributed (a file-level/computed rule, or no distinctive
 * value to match) — graceful, never a broken "Source:" or a guessed-wrong link.
 */
function SourceDocLink({ fileId, finding }: { fileId?: string; finding: VerificationFinding }) {
  // Prefer the full set (LP-114.1); fall back to the single primary (LP-114) for un-re-run findings.
  const docs =
    finding.source_documents.length > 0
      ? finding.source_documents
      : finding.source_document_filename
        ? [{ id: finding.source_document_id ?? "", filename: finding.source_document_filename }]
        : [];
  if (docs.length === 0) return null;
  const single = docs.length === 1;
  const pageSuffix = single && finding.source_page !== null ? `, p.${finding.source_page}` : "";
  return (
    <span className="inline-flex flex-wrap items-center gap-x-1 gap-y-0.5 text-muted-foreground">
      <FileText className="h-3 w-3 shrink-0 text-muted-foreground" aria-hidden />
      {single ? "Source:" : "Sources:"}{" "}
      {docs.map((doc, index) => {
        const label = `${doc.filename}${pageSuffix}`;
        const canLink = Boolean(fileId && doc.id);
        return (
          <span key={doc.id || doc.filename}>
            {canLink ? (
              <Link
                href={`/loan-files/${fileId}/documents?doc=${doc.id}`}
                className="font-medium text-primary hover:underline"
              >
                {label}
              </Link>
            ) : (
              <span className="font-medium text-foreground-2">{label}</span>
            )}
            {index < docs.length - 1 ? "," : ""}
          </span>
        );
      })}
    </span>
  );
}

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
  onUndo,
}: {
  finding: VerificationFinding;
  fileId?: string;
  busy?: boolean;
  onApply?: () => void;
  onOverride?: (reason: string) => void;
  onNote?: (note: string) => void;
  onAcceptRisk?: (reason: string) => void;
  onRequestDocs?: (note: string) => void;
  onUndo?: () => void;
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
  const hasSourceDoc =
    finding.source_documents.length > 0 || Boolean(finding.source_document_filename);
  const hasSource = finding.source_page !== null || Boolean(finding.source_snippet) || hasSourceDoc; // LP-114/.1
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
  // The applied effect shown in the Resolved section (LP-98) — derived from the recorded change.
  const appliedRecord = finding.applied_record as {
    action?: string;
    monthly_payment?: string;
    to?: string;
  } | null;
  const appliedEffect =
    appliedRecord?.action === "add_liability" && appliedRecord.monthly_payment
      ? `Applied · added $${appliedRecord.monthly_payment}/mo obligation`
      : appliedRecord?.action === "correct_income" && appliedRecord.to
        ? `Applied · income corrected to $${appliedRecord.to}/mo`
        : "Applied — incorporated into the file.";

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
      // LP-584 — renamed HERE TOO, deliberately. Leaving the legacy card on "Override" while the
      // rule findings say "Not an issue" would give one action two names in two lists, which is the
      // exact confusion the "Apply" rename (LP-580) existed to remove.
      label: "Why is this not an issue? (required)",
      submit: "Not an issue",
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
    <li className="rounded-lg border border-border px-3 py-2.5">
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
            <span className="text-sm font-medium text-foreground">{headline}</span>
            {resolved && (
              <Badge
                variant="outline"
                className="shrink-0 border-success/40 font-normal text-success"
              >
                {resolutionLabel(finding.resolution_status)}
              </Badge>
            )}
          </div>

          {/* Collapsed one-line "What we found" — the specifics, kept scannable (single line). */}
          {/* A USEFUL multi-line preview (LP-113), not a one-line mid-word cut — these descriptions
              are long, so a single clamped line reads as broken. ``line-clamp-3`` keeps the list
              scannable while giving real context; the FULL text is in the Details expansion below. */}
          {collapsedWhat && (
            <p className="mt-0.5 line-clamp-3 text-xs text-muted-foreground">{collapsedWhat}</p>
          )}

          {/* LP-114.1: name ALL the source documents at a glance (no need to expand Details) — every
              document that derived the finding, each clickable to open it. Hidden when unresolved. */}
          {hasSourceDoc && (
            <p className="mt-1 text-xs">
              <SourceDocLink fileId={fileId} finding={finding} />
            </p>
          )}

          <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-muted-foreground">
            <span>{findingTypeLabel(finding)}</span>
            <span>· {formatPercent(String(finding.confidence * 100))} confidence</span>
            {/* Source-origin (LP-86): deterministic = stable/certain; AI = the novel frontier. */}
            <span
              className={cn(
                "rounded px-1 py-px font-medium",
                deterministic ? "bg-primary/10 text-primary" : "bg-ai/10 text-ai",
              )}
            >
              {deterministic ? "deterministic" : "AI · novel"}
            </span>
            {/* Lender overlay provenance (LP-80) — lender-specific result. */}
            {overlay && (
              <span className="rounded bg-muted px-1 py-px font-medium text-muted-foreground">
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
            <div className="mt-2 space-y-2 rounded-md border border-border bg-muted/70 px-2.5 py-2">
              <FindingSection title="What we found">
                <p className="text-foreground-2">{whatWeFound}</p>
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
                      <h5 className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                        Why it matters
                      </h5>
                      <p className="mt-0.5 text-xs text-foreground-2">{whyItMatters}</p>
                    </div>
                  )}
                  {suggestedFix && (
                    <div className="mt-1.5">
                      <h5 className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                        Suggested fix
                      </h5>
                      <p className="mt-0.5 text-xs text-foreground-2">{suggestedFix}</p>
                    </div>
                  )}
                  {guidanceStarter && (
                    <p className="mt-1.5 text-[10px] text-muted-foreground">
                      Grounded starter — pending expert review.
                    </p>
                  )}
                </div>
              )}

              <FindingSection title="Source">
                {hasSource ? (
                  <div className="space-y-0.5">
                    {/* LP-114.1: name ALL source documents (+ page), each clickable — replacing the
                        bare "Document page N" when we know which documents; falls back to the
                        page-only line when no source document could be resolved. */}
                    {hasSourceDoc ? (
                      <SourceDocLink fileId={fileId} finding={finding} />
                    ) : (
                      finding.source_page !== null && (
                        <p className="text-muted-foreground">Document page {finding.source_page}</p>
                      )
                    )}
                    {finding.source_snippet && (
                      <p className="font-mono text-foreground-2">
                        &ldquo;{finding.source_snippet}&rdquo;
                      </p>
                    )}
                    <p className="text-muted-foreground">{authority}</p>
                  </div>
                ) : (
                  <p className="text-muted-foreground">No single document line — {authority}.</p>
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
                  className="flex items-start gap-1.5 text-[11px] text-muted-foreground"
                >
                  <MessageSquarePlus className="mt-0.5 h-3 w-3 shrink-0 text-muted-foreground" />
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
                      className="gap-1 text-xs"
                      disabled={busy}
                      onClick={() => setViewFixOpen(true)}
                    >
                      <Wrench className="h-3 w-3" /> View fix
                    </Button>
                  )}
                  {onAcceptRisk && (
                    <Button
                      type="button"
                      variant="outline"
                      className="gap-1 text-xs"
                      disabled={busy}
                      onClick={() => openForm("accept")}
                    >
                      <ShieldCheck className="h-3 w-3" /> Accept risk
                    </Button>
                  )}
                  {onRequestDocs && (
                    <Button
                      type="button"
                      variant="outline"
                      className="gap-1 text-xs"
                      disabled={busy || docsRequested}
                      onClick={() => openForm("request")}
                    >
                      <Send className="h-3 w-3" /> {docsRequested ? "Requested" : "Request docs"}
                    </Button>
                  )}
                  {onOverride && (
                    <Button
                      type="button"
                      variant="outline"
                      className="text-xs"
                      disabled={busy}
                      onClick={() => openForm("override")}
                      title="The system got this wrong — dismiss it with a reason"
                    >
                      Not an issue…
                    </Button>
                  )}
                  {onNote && (
                    <Button
                      type="button"
                      variant="ghost"
                      className="gap-1 text-xs text-muted-foreground"
                      disabled={busy}
                      onClick={() => openForm("note")}
                    >
                      <MessageSquarePlus className="h-3 w-3" /> Add note
                    </Button>
                  )}
                </div>
              ) : (
                <div className="space-y-1.5">
                  <label
                    htmlFor={fieldId}
                    className="text-[11px] font-medium text-muted-foreground"
                  >
                    {FORM_META[form].label}
                  </label>
                  <Textarea
                    id={fieldId}
                    value={text}
                    onChange={(e) => setText(e.target.value)}
                    rows={2}
                    placeholder={FORM_META[form].placeholder}
                  />
                  <div className="flex items-center gap-1.5">
                    <Button
                      type="button"
                      className="gap-1 text-xs"
                      disabled={busy || (form === "override" && text.trim() === "")}
                      onClick={submit}
                    >
                      {busy ? <Spinner className="h-3 w-3" /> : <Check className="h-3 w-3" />}
                      {FORM_META[form].submit}
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      className="gap-1 text-xs text-muted-foreground"
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

          {/* Resolved renders COMPACT: the disposition + what was done + Undo (LP-98). */}
          {resolved && (
            <div className="mt-1.5 flex items-start justify-between gap-2">
              <p className="min-w-0 text-[11px] text-muted-foreground">
                {finding.resolution_status === "applied" ? (
                  <span className="text-muted-foreground">{appliedEffect}</span>
                ) : finding.resolution_status === "overridden" ||
                  finding.resolution_status === "accepted_risk" ? (
                  <>
                    <span className="text-muted-foreground">
                      {finding.resolution_status === "accepted_risk" ? "Accepted: " : "Reason: "}
                    </span>
                    {finding.resolution_note ?? "—"}
                  </>
                ) : (
                  <span className="text-muted-foreground">
                    {resolutionLabel(finding.resolution_status)}
                  </span>
                )}
              </p>
              {onUndo && (
                <button
                  type="button"
                  onClick={onUndo}
                  disabled={busy}
                  className="inline-flex shrink-0 items-center gap-0.5 text-[11px] text-primary hover:underline disabled:opacity-50"
                >
                  <RotateCcw className="h-3 w-3" /> Undo
                </button>
              )}
            </div>
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
      <h5 className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
        {title}
      </h5>
      <div className="mt-0.5 text-xs">{children}</div>
    </div>
  );
}
