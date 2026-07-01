LP-92 — Readable finding labels (the xsrc fix)
Small · frontend-only · safe · do first

Fix the meta-label bug where deterministic cross-source findings display raw rule-ids ("Xsrc Income Employer Count Matches Items")
Teach finding-display.ts about the xsrc. namespace (currently only recognizes cross_source.) — strip/map it like the AI cross-source prefix
Map xsrc.* types to readable category labels (e.g. "Income · Cross-source check"), no raw rule-id-derived strings anywhere
Confirm the readable headline (already stored in message) renders correctly; only the meta label is broken
Backend unchanged (the message is already good) — display-layer only
Test: xsrc.* findings show readable labels in both the collapsed and expanded views


LP-93 — Normalized-substance finding identity + dedup
Medium · backend-primarily · fixes a visible bug

Fix the duplicate-findings bug (same finding, different casing/punctuation shown as two — e.g. "Thermofisher Life Science" vs "THERMOFISHER LIFE SCIENCE")
Compute finding identity on normalized substance: canonical type + subject values case-folded and punctuation-normalized (not the rendered string)
On re-run: same normalized identity → keep the first (with its wording/state), ignore the reworded duplicate
Applies to both deterministic and AI findings
Preserve existing resolutions when the same finding re-detects
Test: two findings differing only in casing/punctuation collapse to one; a genuinely-different subject stays separate; a resolved finding re-detects and keeps its resolution


LP-94 — Re-run behavior: merge + drop-when-no-longer-detected
Medium · backend · changes core lifecycle · depends on LP-93

Change re-run behavior per the locked design: currently-detected findings merge (keep wording/resolution/history; new ones added)
A finding no longer detected on a re-run is now DROPPED (removed) — reverses the earlier "mark as no-longer-detected" behavior
A resolved finding that is re-detected preserves its resolution
Depends on LP-93's stable identity (merge/drop need reliable identity)
Update the §3.8-referenced behavior in code + docs to match (the plan already reflects this)
Test: unchanged re-run merges identically; a fixed issue's finding drops on re-run; a resolved finding re-detects and keeps its resolution state


LP-95 — Finding card restructure: four-part + progressive disclosure
Medium-large · frontend-primarily · the display foundation for the AI content

Restructure the finding card into the four-part layout: What we found / Why it matters / Suggested fix / Source (read the frontend-design skill)
Collapsed by default: headline + readable meta (category/confidence/origin badge) + one-line "what we found" + actions
Expand reveals: full "what we found," the why/fix block, and full source with click-through
Placeholder/graceful handling for why/fix when not yet populated (LP-96 fills them) — the card must degrade gracefully
Resolved findings render compact (what was done + effect)
Reuse the deterministic core (what/source) which already exists; scaffold the why/fix slots
Test: card collapses/expands; the deterministic core shows; empty why/fix degrades gracefully; scannable on a busy file


LP-96 — AI-generated why/fix (generated-once, stored, grounded, warned)
Large · backend (AI generation) + model + frontend (display) · the content layer

Add why_it_matters + remediation fields to the rule/finding model
AI-generate the why/fix — once (per rule type at authoring time; per novel finding at discovery), stored (never regenerated per-run), grounded in the rule's facts (the rule + matched values + citation, not free-form)
Mark as grounded-starter, validate-with-Priya
Display: the why/fix block carries a clear-but-calm "AI-generated · verify before relying on this" label and is visually distinct (tinted/bordered) from the deterministic core
Depends on LP-95 (the card must have the slots to show it)
Test: why/fix generated + stored (not regenerated per run — identical across runs); grounded in the rule; the warning label + visual distinction render; marked starter


LP-97 — View Fix: detailed impact preview
Medium-large · full-stack · depends on the apply-spec model

Findings with an apply-spec show "View fix" instead of a bare Apply
Opens a dialog with a detailed, itemized before/after preview: every affected line (e.g. each monthly debt), totals, income, recomputed DTI/LTV, and any status change (e.g. within-limit → over-limit)
Compute the preview without committing (dry-run the apply → show the delta → confirm)
"Apply fix" in the dialog commits; Cancel does nothing
Findings without an apply-spec keep Override/Accept-risk/Request-docs (nothing to preview)
Note: apply-specs currently exist only for the undisclosed-debt rule — this works for those; authoring more apply-specs is separate/future
Test: View-fix shows the itemized before/after + status change; dry-run doesn't commit; Apply commits + recomputes; Cancel no-ops


LP-98 — Undo for resolved findings + Resolved section
Medium-large · full-stack · the trickiest (reversibility) · do last

Add a RESOLVED section below the open findings, each resolved finding compact (what was done + effect) with an Undo button
Undo on Applied = reverse the data change + recompute (requires the apply to store enough before-state to be reversible — confirm/add this)
Undo on Accept-risk / Override = flip status back to Open (no data to reverse)
Audit the undo (who/when — reuse the value-recording posture)
Depends on LP-97 (apply/reversibility) being solid
Test: Undo-Applied reverses the data + recomputes (DTI back down); Undo-Accept/Override → Open; audit recorded; the Resolved section renders


Suggested sequencing & sizing
TicketSizeRiskDepends onLP-92 readable labelsSLow—LP-93 normalized dedupMMed—LP-94 merge/drop re-runMMedLP-93LP-95 card restructureM-LLow-Med—LP-96 AI why/fixLMedLP-95LP-97 View Fix previewM-LMed—LP-98 UndoM-LHighLP-97
