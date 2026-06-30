# Phase 3 Testing Checklist (§3.8) — results (LP-89)

The plan's §3.8 checklist, run + documented. Backend **1366 passing**, frontend **235 passing**;
`ruff` + `mypy --strict` + `biome` + `tsc` + `next build` all clean.

| Checklist item | Status | Where |
|---|---|---|
| The deterministic engine evaluates rules correctly (read → compare → emit) | ✅ | `tests/verification/`, `tests/services/test_verification_engine.py` |
| The full Conventional + FHA rule set loads + is program-gated | ✅ | `tests/verification/test_*_rules*.py` |
| The deterministic cross-source rules fire + are stable (no flicker) | ✅ | `tests/verification/test_cross_source_rules.py` |
| The AI cross-source pass emits findings + the APPLY→recompute loop | ✅ | `tests/services/test_cross_source.py` |
| **Unchanged re-run returns identical findings, no AI call** (LP-78.1/86) | ✅ | caching test in `tests/api/test_verification_endpoints.py` (fingerprint match → cached run) |
| **Worker-backed features tested with the registration guard** (the seam lesson) | ✅ | `tests/tasks/test_task_registration.py` + `tests/integration/test_cross_source_worker.py` (the task runs end-to-end) |
| The six calculators compute transparently + are overrideable | ✅ | `tests/verification/test_calculators_pure.py`, `tests/services/test_calculators.py` |
| Lender overlays adjust the effective thresholds (UWM ≠ Sun-West) | ✅ | `tests/services/test_demo_proofs.py` |
| The dial filters by confidence; the pills filter severity/category | ✅ | `tests/api/test_verification_endpoints.py`, frontend `finding-filters.test.tsx` |
| Findings resolve (Apply / Override / Note / Accept-risk / Request-docs) | ✅ | `tests/api/test_verification_endpoints.py`, frontend `finding-card.test.tsx` |
| **The stuck-RUNNING watchdog** (timed-out run → FAILED, not stuck) | ✅ | `tests/api/test_verification_endpoints.py` (watchdog tests) |
| **Performance under the full rule load** (deterministic pass is fast) | ✅ | `tests/services/test_demo_proofs.py` (< 3s bound) |
| **Error-path robustness** (no data / no docs / FHA / partial — no crash) | ✅ | `tests/services/test_demo_proofs.py` |
| Tenant scoping (cross-company → 404 / 403) | ✅ | throughout (the integration tests) |
| The validation aid (inventory + verdicts + grounded_starter default) | ✅ | `tests/integration/test_validation_aid_api.py` |
| No regression on LP-74..88 | ✅ | the full suite green |

## The two added items (the standing lessons)

1. **Unchanged-re-run-identical-no-AI** — the input fingerprint (LP-78.1) means an unchanged re-run
   returns the cached run without calling the AI; the deterministic cross-source rules (LP-86) are
   byte-identical across runs.
2. **Worker-backed-features-tested** — the worker-seam bugs all passed unit tests. The registration
   guard asserts every task module is registered; the integration test runs the actual task body
   end-to-end (findings persist). Both are standing tests, not one-offs.
