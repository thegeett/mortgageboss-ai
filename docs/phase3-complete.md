# Phase 3 Complete — Verification Engine & Calculators (the V1 summary)

What V1 verification delivers, what remains grounded-starter pending Priya, and the path to Phase 4.

## What V1 delivers

- **The deterministic rule engine** (LP-74): a uniform rule structure, threshold-as-data, three-layer
  composition (regulatory + investor[program] + lender overlay), pure read→compare→emit evaluation.
- **The full rule set** (LP-82..86): ~120 grounded-starter rules — Conventional (income/asset/credit/
  DTI/property/doc) + FHA (credit/DTI/income/asset/MIP/property-MPR/doc) + 18 deterministic cross-source
  checks graduated from the AI discovery layer.
- **The AI cross-source discovery layer** (LP-78/78.1) — the novel-discrepancy frontier, cached + stable.
- **The six calculators** (LP-76/77/87): DTI, LTV, MI/MIP, self-employed income, reserves, max-loan —
  transparent (the math shown), auto-populated, overrideable (recompute flows), findings-coupled,
  deterministic.
- **Lender overlays + the admin UI** (LP-80/87): per-lender deviations, edited without code, effect-legible.
- **The confidence dial** (LP-79) + **findings + resolution** (LP-75): Apply / Override / Note /
  Accept-risk / Request-docs, with stable templated wording + source location.
- **The full verification tab** (LP-88): stats row, severity/category filter pills, run-history version
  selector, the six calculators via progressive disclosure, source-origin + lender-specific results.
- **Hardening** (LP-89): the stuck-RUNNING watchdog, real-stack worker integration testing, performance
  under the full rule load, error-path robustness.

## What is grounded-starter (pending Priya)

Every rule + calculator methodology is **grounded-starter** — researched against the real sources but
**not yet validated** by the domain expert. The **validation aid** (LP-89) is the tool to capture her
verdicts; her session is the validation. Until a verdict is recorded, an item's `validation_status` is
`grounded_starter`. Nothing is claimed "validated" on the strength of the grounding alone.

## The path to Phase 4

- Run the demo (`docs/demo-script.md`) + the validation session (`docs/validation-session-guide.md`);
  act on the recorded verdicts.
- Phase 4 — communication: Request-docs already creates a needs item (the seam); the full borrower
  communication flow (sending requests, tracking replies) is Phase 4.
- The V2 deferrals (`docs/v2-deferrals.md`) capture the explicit V1 boundaries.
