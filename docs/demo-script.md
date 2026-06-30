# Phase 3 Demo Script — the verification system (LP-89)

The runbook for demoing the verification system to Priya (the domain expert / first user). The
goal is to show the three proofs, then walk her through the validation aid to capture her verdicts.

> **Honest framing for the room:** the rules + calculator methodologies are **grounded starters**
> — researched against the real sources (Fannie Selling Guide / HUD 4000.1 / Form 1084) but **not
> yet validated** by Priya. Her reactions in this session ARE the validation; the aid records them.

## Setup

1. `uv run alembic upgrade head` (apply all migrations, incl. LP-89's `validation_verdicts`).
2. Seed the demo files: `uv run python -m app.scripts.seed_dev_data`.
3. Start the stack: backend (`uvicorn`), the Celery worker (so "Run verification" works), the frontend.
4. Log in as an **admin** (the validation aid + overlay admin are admin-gated).

## The demo files

| File | Program | Lender | Demonstrates |
|---|---|---|---|
| **File A** (Jordan Rivera) | Conventional | UWM | a fresh file, the needs floor |
| **File B** (Priya Nair) | **FHA** | Sun-West | the FHA rule set + MIP calculator + FHA conditional findings |
| **File C** (Morgan Ellis) | Conventional | UWM | a near-submission file with documents (refinance) |
| **File D** (Casey Demo) | Conventional | — | the real MISMO-imported stated financials |

Run the demo on a Conventional file (A/C) and the FHA file (B) so both programs are shown.

## Proof 1 — DTI with the math shown (beat ChatGPT's black box)

1. Open a Conventional file → the **Verification** tab → the **Calculators** strip.
2. Expand **DTI**. Show the transparent breakdown: every income / housing / debt line, the explicit
   formula, the two ratios, the effective limit side-by-side.
3. Override a line (e.g. exclude a debt paid at closing) → the ratio recomputes instantly.
4. The point: *"this isn't a number from a black box — every input is shown, sourced, and editable."*
   (Automated: `tests/services/test_demo_proofs.py::test_dti_shows_the_transparent_breakdown`.)

## Proof 2 — UWM ≠ Sun-West (lender-overlay enforcement)

1. The SAME borrower numbers produce DIFFERENT verdicts under different lenders. A file at ~47%
   back-end DTI: **UWM** tightens the cap to 45% → **over**; **Sun-West** leaves it at 50% → **pass**.
2. Show the DTI limit on a UWM file (over, "overlay" source) vs a Sun-West file (pass, default).
3. The point: *"the system enforces the LENDER's rules, not a generic guideline — same file, different
   answer per lender."* (Automated:
   `tests/services/test_demo_proofs.py::test_uwm_and_sunwest_produce_different_dti_verdicts_on_the_same_file`.)
4. Then show the **overlay admin** (`/admin/lenders`) — editing UWM's DTI cap, with the effect legible
   (base 50 → effective 45) and a required reason.

## Proof 3 — the end-to-end slice

1. Open a file → the six **calculators** (progressive disclosure) → **Run verification** (the AI
   cross-source pass runs on the worker; the spinner resolves; findings appear).
2. **Resolve a finding**: Apply an undisclosed-debt finding → the DTI recomputes higher (the
   APPLY→recompute interlock). Or Accept-risk an FHA compensating-factors finding; or Request-docs.
3. Show the **stats row**, the **filter pills** (severity/category, composing with the dial), the
   **version selector** (run history), and the **source-origin** badges (deterministic vs AI · novel)
   + the lender overlay shown on findings.

## Proof 4 (FHA) — the FHA program

1. Open File B (FHA) → the **MI/MIP** calculator (UFMIP 1.75%, annual MIP, the LTV-90% duration);
   the **reserves** calculator (the 60% retirement haircut); the FHA findings (the tiered MDCS, the
   compensating-factors mitigable DTI, the MPR subject-to-repair conditional findings).

## Then — the validation session

Switch to `/admin/validation` and walk Priya through the inventory by category (see
`docs/validation-session-guide.md`). Record her verdict per item as she gives it.
