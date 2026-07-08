# LP-119/120/121 — round-3 fixes: close the re-inversions + seed/DB drift before wiring

**Type:** Fix-up (round 3) · **Epic:** Phase 3.5 / Epic B · **Depends:** LP-119, LP-120, LP-121, LP-122R
**Status:** complete · **Date:** 2026-07-08

## What this is

A third read-only review (after two hardening rounds + LP-122R) found **no live HIGH-severity defect** —
the honesty contract held. But it caught **two contract RE-INVERSIONS** (our own prior fixes overshot
into the OPPOSITE failure) and a systemic **seed/DB drift** (seed-data changes shipped without data
migrations, so existing DBs are stale). These are closed here, before the runner is wired into any caller.

### Two meta-lessons (now standing policy)

- **A. Test honesty-layer fixes from BOTH directions.** A fix that trades "too strict" for "too loose"
  hasn't fixed anything — the honesty layer needs the *precise* condition. Every fix here is tested
  against the failure it targets AND the opposite failure it must not create.
- **B. Seed-data change ⇒ data migration.** Seeding is INSERT-ONLY (existing rule_ids are skipped), so
  changing a column value or shape in the seed never reaches an existing DB by re-seeding. LP-122R did
  this correctly for `validated`; the earlier FIX-6 / FIX-3b did not — hence the drift. Codified in
  `rule_registry.seed_verification_rules` + `generate_rule_seed` docstrings.

## The fixes

### Contract re-inversions (the important ones)

- **FIX 1 — nested required-input: the RELEVANT elements must have the data (neither `all` nor `any`).**
  The prior round swapped `all`→`any`, so a nested required-input was satisfied if *any* element carried
  the leaf — a 2-borrower file where the co-borrower's income wasn't extracted went READY on the
  primary's data alone (evaluator runs on incomplete household data → false-green). The engine now
  distinguishes three per-branch states (`_Leaf`): an element with an **empty** sub-collection is SKIPPED
  (nothing to check — a co-borrower with no income items must not sink the rule); an element with a
  **non-empty** sub-collection whose leaf is absent is ABSENT (fail-closed → couldn't-check). Runnable
  only when every element that HAS the sub-collection carries the leaf. Latent today (AS-5 is single-level
  `assets[].is_gift`) but correct before the per-borrower income/asset family is built.
  *Tested both directions:* co-borrower with no income + primary full → READY; co-borrower with income
  but `monthly_amount` absent → COULDN'T-CHECK. (`test_r3fix1_nested_required_input_relevant_element_both_directions`)

- **FIX 2 — exhaustive `else` in the seed's purpose→scope mapping.** The `if/elif` handled only the four
  `PurposeScope` members with no `else`, so a *new* member would seed a purpose-LESS scope → the engine
  reads "no constraint → applies to all" → false-green nationwide (the FIX-3/4 whitelist failure, one
  layer up). Now an unhandled member `raise`s at seed time — an enum that grows must break seeding, not
  misapply rules. `None` (applies to every purpose) stays an explicit, handled case.
  (`test_r3fix2_unhandled_purpose_raises`)

### Seed/DB drift — data migrations + discipline

- **FIX 3 — confidence_mode data migration (`certain` → the FIX-6 vocabulary).** FIX 6 renamed the
  deterministic value but insert-only re-seed left 122 existing rows at `"certain"` while the runner
  emits `"deterministic"`. Migration `c9a3e7f1b5d8` renames every `"certain"` row to `"deterministic"`.
  Verified on the live dev DB: `{certain:122, computed:11, None:7}` → `{deterministic:122, computed:11,
  None:7}`. (Seed-source guard: `test_r3fix3_seed_confidence_mode_vocab`.)

- **FIX 4 — applicability-shape data migration (legacy flat → wire format).** FIX-3b moved rules to the
  wire shape + `extra="forbid"`, but only AS-5 got a rewrite migration, leaving flat rows (e.g.
  `xsrc.terms.price_vs_contract = {"purpose": "purchase"}`) that silently degrade to couldn't-check when
  wired. **Decision (per the ticket's guidance):** repair each legacy-shape row in place — the one with
  KNOWN intent (PC-2 → purchase) is translated to correct wire scope `{"scope": {"loan_purpose":
  ["purchase"]}}`; any other not-yet-built legacy row is nulled (universal → authored properly when its
  rule is built). Valid wire shapes and NULLs are untouched, so the migration **no-ops on a fresh DB**.
  Verified on the dev DB: the single flat row (`price_vs_contract`) → wire; zero legacy-shape rows remain;
  AS-5 intact. (Same migration `c9a3e7f1b5d8`; seed-source guard:
  `test_r3fix4_seed_has_no_flat_applicability`.)

  *Why translate PC-2 rather than null it:* its intent is unambiguous (purchase), so the wire scope
  preserves correct classification (doesn't-apply on a refi) instead of over-applying as universal. PC-2
  itself remains **not built** — only its applicability shape is corrected.

- **Discipline — "seed-data change ⇒ data migration"** is now written at the drift root
  (`rule_registry.seed_verification_rules`) and in `generate_rule_seed`'s module docstring, referencing
  the LP-122R validated migration as the pattern. This is the durable fix that prevents round 4.

### Trust-surface correctness (cheap now, serves LP-162)

- **FIX 5 — distinguish applicability-couldn't-check from evaluator-couldn't-check.** `RuleOutcome` gained
  `source: OutcomeSource` (`applicability` | `evaluator`). Both couldn't-check kinds stay in one bucket
  but are now distinguishable: "missing inputs → upload/fix the file" (applicability) vs "had the data,
  couldn't reach a verdict / rule not built" (evaluator). Directly serves the LP-162 grouping.
  (`test_r3fix5_couldnt_check_kinds_are_distinguishable_by_source`)

- **FIX 10 — provisional only on real verdicts.** `provisional` ("verdict pending validation") is now
  stamped only on FINDING / SATISFIED. A doesn't-apply or couldn't-check made no verdict, so badging it
  provisional would mislead. (`test_r3fix10_only_verdict_outcomes_are_provisional`)

- **FIX 6A — enforce refi `loan_purpose` co-emission structurally.** The prior round removed the
  refinance_type-on-purchase engine guard, making correctness depend on the seed always co-emitting
  `loan_purpose:[refinance]` beside `refinance_type`. Now `_enforce_refi_scope_invariant` makes it
  STRUCTURAL — any builder that constrains `refinance_type` gets `loan_purpose:[refinance]` co-emitted (a
  refi scope cannot exist without it), and a contradictory explicit `loan_purpose` raises. Not restored as
  an engine special-case — enforced at construction. (`test_r3fix6a_*`)

- **FIX 6B — enforce the validated-no-threshold criterion in code.** `_VALIDATED_NO_THRESHOLD` was a
  hardcoded set not checked to be threshold-free; a threshold-bearing rule_id added to it would seed
  `validated=true` beside an unconfirmed threshold. Now a member with non-empty params raises at seed
  time — `validated=true` is legal only for genuinely threshold-free rules (the LP-122R criterion,
  enforced). (`test_r3fix6b_validated_no_threshold_rejects_a_threshold_rule`)

### Cleanup

- **FIX 7 — structural None-guard, single lookup.** Replaced `assert result is not None` (stripped under
  `python -O`) with a structural bind: `evaluator = get_evaluator(id); if evaluator is None: <couldn't-check>;
  else evaluator.evaluate(...)`. One registry lookup instead of two (`get_evaluator` + `evaluate_rule`).
  (`test_r3fix7_run_rule_engine_uses_no_assert`)
- **FIX 8 — corrected the evaluator-contract docstring.** It said evaluators produce "finding/satisfied
  ONLY — never couldn't-check", contradicting the LP-121 fix that added `Verdict.COULDNT_CHECK`. Now
  documents the couldn't-check escape hatch and when to use it (data present but undeterminable — not to
  skip an unwritten check).
- **FIX 9 — annotated `_NON_DETERMINATION_SOURCES`.** Noted that `UNMAPPED` is the load-bearing member and
  the `ABSENT_*` members are belt-and-suspenders (normally caught earlier by the `node.absent` branch), so
  a maintainer doesn't trim that branch trusting this set as sole authority.

## Scope held

Not wired to the live path (these fixes *prepare* for wiring); AS-5 stays the only built rule; no live
verification-path behaviour changed. Seed regenerated (140 rows). Both data migrations verified against
the live dev DB. `tests/verification` + `tests/services/test_rule_registry` green (245); ruff + mypy clean.

## Follow-ups

- **Wiring** the runner into a caller is the next step (a later ticket), now that the drift is repaired and
  the re-inversions are closed.
- **Nested-`entity_exists` / `min_count` schema** still needs resolving before the per-borrower income/asset
  rule family (their triggers may need shapes the schema doesn't yet express) — FIX 1's relevant-element
  logic is the required-input half of that family's needs.
- **Test DB uses `create_all`, not migrations** (`tests/conftest.py`), so FIX 3/4 are guarded at the
  seed-source level in tests + verified on the dev DB manually; if migration-run-in-tests is added later,
  a DB-level post-migration assertion can be added.
