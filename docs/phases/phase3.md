Phase 3 — Verification Engine & Calculators (LP-74 onward)
ARC A — The Vertical Slice (build first → demonstrable to Priya)
LP-74 — Verification Rule Engine: Uniform Rule Structure + Three-Layer Composition
The spine of Phase 3 — the engine before the rule content (the LP-68 of verification).

Define a uniform rule structure (one kind of record for all three layers): stable rule_id, layer (regulatory/investor/overlay), applicability scope (all loans / program / lender), the typed field(s) it reads, threshold-as-data (not hardcoded — the linchpin that makes overlays possible), severity (red/yellow), and metadata (description, source citation).
Build the three-layer composition/resolution: given a file's program + lender, resolve the effective rule set — regulatory + investor(program), then patch with the lender overlay (override thresholds by rule_id, add custom rules) → one flat effective set per file.
Establish that the investor rule is the default and overlays are diffs (only deviate where the lender differs; no overlay → all investor defaults).
Build the deterministic evaluation loop: each rule reads typed fields → compares to its (possibly overlay-patched) threshold → emits a pass/fail finding. Pure deterministic judgment, auditable.
Accommodate the two-generator model: the engine accepts findings from both deterministic threshold rules (this engine) and the AI cross-source layer (LP-78) — both feed one findings model.
Ship with a few sample rules (e.g., a DTI threshold rule, a recency rule) to prove the engine end-to-end — the real ~60/~50 content comes in Arc B.
Backend only; tenant-scoped; per-file verification runs against shared rule definitions.
Tests (composition, override-by-id, custom-rule-add, evaluation, sample rules); docs + ADR; docs/tickets/LP-74.md.

LP-75 — Findings Model Extension: Confidence, Resolution States & Blocking
Extend the LP-66 Finding model into the verification findings system.

Extend the existing LP-66 Finding model (don't build new): add the verification dimensions.
Add a confidence score per finding (drives the aggression dial) — deterministic threshold findings are high-confidence; AI cross-source findings vary.
Add resolution states: APPLIED (incorporated into the file/numbers) or OVERRIDDEN (dismissed with a recorded reason), plus open/unresolved.
Implement blocking behavior: open in-scope findings block the file from being marked ready to submit — nothing silently ignored.
Carry the source location (page + verbatim snippet — the trust/audit mechanism; click a finding → see the document line), building on the per-field source location from extraction.
Ensure a uniform finding shape (type, amount, source document, page, snippet, confidence, reasoning, severity, resolution) so deterministic and AI findings look identical to the UI + resolution flow.
The APPLY → recompute hook: applying a finding changes structured data → downstream deterministic rules/calculators recompute (wired fully in LP-78).
Backend only; tenant-scoped; migration (reviewed, up + down).
Tests (confidence, resolution transitions, blocking, source-location, uniform shape); docs + ADR; docs/tickets/LP-75.md.

LP-76 — DTI Calculator (transparent, auto-populated, override-able)
The headline "replace ChatGPT" win — deterministic, transparent math.

Compute front-end DTI (housing payment / gross monthly income) and back-end DTI (total monthly debts / gross monthly income) — deterministic.
Show the full breakdown: income components itemized, housing components (PITI + MI + HOA) itemized, each debt itemized — the whole derivation, not just a number.
Show the formula explicitly ("Back-end DTI = (PITI + monthly debts) / gross monthly income").
Show program limits side-by-side (Conv 50%; FHA 43% / 50%-with-compensating).
Auto-populate from MISMO stated values + verified document values (starts filled, not blank).
Allow manual override on any field, with an audit log (a debt paid at closing, an income adjustment — logged).
Real-time recalculation as any input changes.
Couple to findings: while any in-scope finding is unresolved, show an alert ("findings unresolved — this calculation may be incomplete") — query open in-scope findings for the file.
Full-stack (the calc logic + the transparent display); frontend-design skill; tenant-scoped; PII masked.
Tests (front/back-end math, breakdown, override + audit, auto-populate, findings-alert coupling); docs + ADR; docs/tickets/LP-76.md.

LP-77 — LTV Calculator (LTV / CLTV / HCLTV, refinance-aware)
The other core calculation, same transparency model.

Compute LTV = loan / lesser of (purchase price, appraised value).
Compute CLTV = combined first + second loans / property value.
Compute HCLTV = for HELOCs, using the credit limit (not the balance).
Show program limits side-by-side.
Auto-populate from MISMO + appraisal data.
Handle refinance scenarios — rate/term vs. cash-out.
Same transparency + manual override + audit log model as DTI.
Couple to findings (the unresolved-findings alert).
Full-stack; frontend-design skill; tenant-scoped.
Tests (LTV/CLTV/HCLTV math, refinance scenarios, override + audit, auto-populate); docs + ADR; docs/tickets/LP-77.md.

LP-78 — Starter Cross-Source Rules (AI-surfaces layer) + APPLY→Recompute Loop
The AI discrepancy detection — starter set — and the interlock with deterministic recompute.

Build one general AI cross-source capability: the AI reads stated MISMO data vs. verified document data and surfaces discrepancies as structured findings with confidence — one pass, not a method per rule (catches known and novel discrepancies).
Encode a starter set of the highest-value comparisons (not the full ~15-20 — that's LP-86): stated income vs. computed-from-pay-stubs (>10% variance), stated employer vs. document employer, stated gift vs. gift letter.
Findings flow into the LP-75 findings model — same shape, resolution, blocking as deterministic findings.
Wire the APPLY → recompute loop: applying a cross-source finding (e.g., adding an undisclosed obligation to liabilities) changes structured data → the deterministic DTI/LTV recompute. The key AI↔deterministic interlock.
Manual trigger + staleness flag (V1): the processor runs the cross-source pass on-demand; mark verification STALE when documents change (cross-source needs both sides present).
Structured-data handoff only (AI emits typed findings; deterministic rules never read AI prose); AI fallibility acceptable because findings are human-reviewed.
Backend + the trigger/staleness wiring; tenant-scoped; PII metadata-only logging; real AI cost/latency noted.
Tests (AI mocked at the boundary): discrepancy surfacing with confidence; APPLY→recompute; manual-trigger + staleness; starter rules. Docs + ADR; docs/tickets/LP-78.md.

LP-79 — Aggression Dial (confidence-threshold gating)
One AI pass, three views — the elegant filter.

Implement the three levels: Conservative / Balanced (default) / Thorough — as confidence cutoffs.
One AI pass, three views: all findings stored with confidence (LP-75); the dial filters at read time — no re-run, no cost to change.
Gate both display AND blocking: a finding below the cutoff is hidden and non-blocking; at/above is shown and must be resolved. ("Resolve all findings" = "at the chosen thoroughness.")
Make it clear the dial never recolors findings (severity is intrinsic) — it changes which findings are in-scope.
Per-file setting with a user-level default + per-file override.
Record the active level at submission on the file (auditability).
Instant re-filter on dial change (no AI re-run).
Full-stack (the cutoff logic + the dial control); frontend-design skill (make the in-scope/blocking change legible — "Thorough surfaced 3 more findings to resolve").
Tests (cutoff filtering, display+blocking gating, per-file override, submission-level recorded, instant re-filter); docs + ADR; docs/tickets/LP-79.md.

LP-80 — Starter Lender Overlays (UWM + Sun-West) + Overlay Enforcement
Minimal overlays for Priya to react to — enforcement now, admin UI later.

Implement the overlay-as-patch enforcement (the mechanism from LP-74): overlays override investor thresholds by rule_id + add custom rules, resolved per file at verification time.
Encode starter UWM + Sun-West overlays — a handful each (e.g., a stricter DTI cap, a credit threshold) as JSON config, with a reason field per override — explicitly "starter values, refine with Priya."
Prove the overlay difference: the same file produces different findings under UWM vs. Sun-West (the enforcement proof + a compelling Priya demo moment).
Overlays are JSON config (hand-editable) for now — the admin editing UI is Arc B (LP-87).
No loosening guard decision noted (overlays typically tighten; lock precedence = overlay value wins where specified).
Backend (enforcement + the starter configs); tenant-scoped; admin-level write (even if hand-edited now).
Tests (override-by-id applied; custom rule added; same file → different findings UWM vs Sun-West; no-overlay → investor defaults); docs + ADR; docs/tickets/LP-80.md.

LP-81 — Minimal Verification Tab UI (the demo surface)
Enough UI to show Priya the slice — DTI/LTV + findings + dial.

The DTI calculator prominent + the LTV alongside (the headline).
A findings list — deterministic + cross-source findings with severity, source, and the source-location (click → snippet).
The aggression dial control.
Core per-finding actions: Override, Mark resolved / APPLY, Add note (the resolution flow).
The unresolved-findings alert on the calculators.
The manual cross-source trigger + the staleness flag ("documents changed — verification out of date; re-run").
Polished enough to demo (frontend-design skill) — NOT the full stats-row / filter-pills / version-selector (those are LP-88).
Full-stack (the read/write APIs + the UI); tenant-scoped (404 cross-company); PII masked.
Tests (renders DTI/LTV + findings + dial; resolution actions; staleness/trigger; tenant-scoped); docs + ADR; docs/tickets/LP-81.md.


End of Arc A — the Priya demo state: open a real file → transparent DTI + LTV (compare to ChatGPT, override) → run cross-source → see real discrepancy findings → toggle the dial → see UWM vs. Sun-West differ. The "replace ChatGPT + catch discrepancies" value, working end-to-end.


ARC B — The Breadth (fill in after the slice is validated with Priya)
LP-82 — Conventional Income & Asset Rules (~20)
Bulk Conventional content — the engine exists; this is rule encoding.

Income rules (~10): pay stub recency, employment stability, income calculations.
Asset rules (~10): reserves, large deposits, gift fund documentation.
AI-assisted-but-human-reviewed encoding (AI drafts from the Fannie Selling Guide; human verifies the logic and the source citations — hallucination risk).
Priya's priority list determines which specific rules.
Each rule: rule_id, typed field(s) read, threshold-as-data, severity, source citation (durable section reference preferred over deep URL).
Promote any needed fields from the extraction catch-all to the typed core as rules require them.
Tests per rule + against the test file; docs + ADR; docs/tickets/LP-82.md.

LP-83 — Conventional Credit/DTI, Property & Documentation Rules (~30)
The rest of the Conventional set.

Credit/DTI rules (~10): DTI limits, front-end ratio, credit thresholds.
Property rules (~10): LTV, property type eligibility, occupancy.
Documentation rules (~10): recency, completeness, cross-document consistency.
Same encoding/verification discipline; Priya's priorities; typed-core promotion as needed.
Tests; docs + ADR; docs/tickets/LP-83.md.

LP-84 — FHA Rules: Income, Assets, Credit/DTI, MIP (~31)
FHA-specific content — meaningfully different from Conventional.

Income (~8): FHA income allowances.
Assets (~8): more permissive gift fund rules.
Credit/DTI (~10): lower credit threshold, higher DTI ceiling.
MIP (~5): upfront MIP, annual MIP for life of loan.
Conservative V1 encoding: flag as red, let the processor "Accept risk" for compensating factors; automatic compensating-factor logic is V2 (deferred).
Tests; docs + ADR; docs/tickets/LP-84.md.

LP-85 — FHA Rules: Property & Documentation (~18)
The rest of FHA.

Property (~10): FHA Minimum Property Standards.
Documentation (~8): FHA-specific addenda.
Conservative encoding (flag + Accept-risk).
Tests; docs + ADR; docs/tickets/LP-85.md.

LP-86 — Full Cross-Source Rule Set (~15-20)
Expand the LP-78 starter set to the full set.

Stated debts cross-checked against the credit report.
Stated owned properties verified against documentation.
Borrower identity consistent across MISMO, ID, credit report.
Stated checking balance vs. most recent bank statement.
The remaining high-value comparisons (~15-20 total).
All feed the findings model + APPLY→recompute loop; confidence-scored for the dial.
Tests (AI mocked at the boundary); docs + ADR; docs/tickets/LP-86.md.

LP-87 — Additional Calculators (MI, self-employed income, reserves, max loan) + Overlay Admin UI
The remaining calculators + making overlays editable without code.

MI factor calculator — PMI (Conv) / MIP (FHA).
Qualifying income for self-employed — two-year averaging with K-1 / Schedule C handling (directly relevant to the test borrower's two businesses).
Reserves requirement calculator.
Maximum loan amount calculator — given income + DTI limit.
Overlay admin UI: a simple admin panel to add/edit lenders, a per-lender overlay form, a visualization of which investor rules are overridden, editable without a developer — admin-access gated (system-wide impact).
The observed-conditions feedback groundwork ("we got this condition from this lender" tracked as data to refine overlays).
Full-stack; frontend-design skill; transparency + override + audit on the calculators.
Tests; docs + ADR; docs/tickets/LP-87.md.

LP-88 — Full Verification Tab UI (complete Wireframe 5)
Expand the minimal LP-81 UI to the full surface.

Stats row: total checks, open red, open yellow, resolved.
Filter pills: all / red / yellow / resolved / by category.
Finding cards: full status / source / action buttons.
Version selector for verification runs (see prior runs).
Full per-finding actions: Request docs, Mark resolved, Accept risk, Add note, Override — all logged to the activity log.
The calculators prominent, the dial, the staleness/manual-trigger — refined.
Full-stack; frontend-design skill; tenant-scoped; PII masked.
Tests; docs + ADR; docs/tickets/LP-88.md.

LP-89 — Phase 3 Testing, Polish & Hardening (the capstone)
Mirrors LP-73 — the real-stack, Priya-validated close.

Priya runs real Conv + FHA files → findings match what she'd flag manually.
DTI matches her ChatGPT result (and shows the math) — the concrete success criterion.
LTV correct including refinance scenarios.
UWM overlay produces different findings than Sun-West for the same file (the enforcement proof).
Cross-source catches real discrepancies on test files.
Real-stack integration testing (the Phase 2 lesson carried forward — exercise the real assembled system + the seams, AI mocked only at the model boundary).
Tenant-isolation pass across all Phase 3 surfaces; polish; seed/fixtures updated to demonstrate verification.
Phase 3 docs + deferred items explicitly recorded: V2 auto-compensating-factors, V2 auto-re-run of cross-source, bounding-box highlighting, full overlay observed-conditions refinement — plus the ongoing Priya domain-tuning (honest scoping: built/tested/hardened ≠ domain-final).
Tests (all green incl. integration); docs + ADR; docs/tickets/LP-89.md.

LP-90 — Expose valuation_amount on the Overview (editable) + make the LTV "Appraised value" source explicit
A focused hidden-field fix. The LTV appraised basis reads `valuation_amount or estimated_value`, but valuation_amount
was never exposed in the read schemas or the Overview editor — so it silently shadowed the editable estimated_value
(editing "Estimated value" didn't move the LTV on any MISMO file). Expose it (PropertyResponse + loan-file PropertyPublic),
make it editable on the Overview (the property PATCH already invalidates dti/ltv/verification — the core fix), and show
the LTV basis source ("from valuation amount" / "from estimated value") with the literal logic in a tooltip.
Flagged for Priya (not done): renaming "Appraised value"; collapsing valuation_amount + estimated_value.
Tests (backend + frontend, all green); ADR-215; docs/tickets/LP-90.md.
