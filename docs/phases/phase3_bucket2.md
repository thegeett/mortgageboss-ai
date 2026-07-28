EPIC LP-406 — Bucket 2: Write the four zero-dependency rules

Goal: Ship the only 4 rules whose every input is already produced today — no new producer, no new extractor, no new calibration.
Why now: All four ride producers already live for a sibling rule (IN-5, OC-2, AS-1/9/10, CL-1). Cheapest remaining work in the engine.
DoD: All 4 written, firing on a fixture, and live (or explicitly held with a documented reason).

LP-406-1 — PC-7 (Contract) · 2 pts · build first (cheapest)
Read the spec + rule_tags.csv; confirm every read-tag is produced by the live purchase_agreement path (CL-1's producer)
Write the rule spec (rules are data, not code)
Prove it reaches a real verdict on a fixture — reported, not predicted
Assert absent ≠ empty ≠ unknown; a uniformly-couldnt_check result is a failure
Deterministic → no calibration; activate via the gate if kind permits
Tests + docs/tickets/LP-406-1.md
LP-406-2 — AS-8 (Statement chaining / continuity) · 3 pts
Checks consecutive bank statements form an unbroken sequence (no missing month; ending balance → next opening balance)
Rides AS-1/9/10's already-live statement producers
Calculative/deterministic — arithmetic on balances + date ranges, no AI judgment
Handle the gap cases honestly: a missing month = open; a single statement = not_applicable, not couldnt_check
Prove both the fires-path and the satisfies-path on LF-6T3N
Tests + doc
LP-406-3 — IN-6 (Pay-stub ↔ W-2 coverage) · 3 pts
Checks pay stubs and W-2s reconcile over the same employment period
Rides IN-5's live income producers (documented_monthly, employer_normalized — both measured 100%)
Confirm whether it needs a Priya tolerance (how close must stub-annualized be to W-2?) → if yes, ship validated=false and flag for her
Per-borrower enumeration (reuse LP-389-A's primitive — no second mechanism)
Tests + doc
LP-406-4 — OC-1 (Occupancy) · 3 pts
⚠️ Spec-wording trap (LP-405 finding): its produced AI tag measures declaration consistency, not address signals (the LP-371 D3 caveat) — word the spec to what the tag actually measures, or it becomes structurally dead
Rides OC-2's live producer
Phase 0 must confirm the tag's real semantics before writing the verdict logic
Tests + doc
EPIC LP-407 — Bucket 2.5: Wire the rules whose extractors already exist

Goal: ~10 rules that LP-394 mis-filed as "needs-extractor" — the purchase_agreement, homeowners_insurance, hoa_statement, and property_tax_bill extractors already exist and run. This is tag wiring, not extraction.
Why it matters: More rules per ticket than anything else remaining, and it shrinks the real Bucket 4 gate to five documents (credit, title, appraisal, AUS, MI).
DoD: Each rule either live, or held with a named blocker.

LP-407-1 — Wiring audit (READ-ONLY, do first) · 2 pts
For PC-2/3/4/5/6/8/9 and DT-2/4/5: map rule → read-tag → which existing extractor field supplies it
Resolve the LP-405 flagged assumption: the catch-all Contract tags (seller credit, addenda, personal property, contingency dates) are inferred reachable via purchase_agreement.additional_sections — confirm or refute; typed-core fields are already confirmed
Report which need only a declared tag vs a small extractor extension
Group into wiring waves; report the true rule count
No code change — report only
LP-407-2 — Wire the Contract tags (PC-2/3/4/5/6/8/9) · 5 pts
Declare + produce the tags from the existing purchase_agreement extractor
Reuse the declared-key-resolved-by-registry pattern — no per-rule branch (STOP and REPORT if one is needed)
Prove each tag materializes at the subject its rule reads (the ID-5 structural-death check)
Any extractor extension found in LP-407-1 handled here or split out
Tests + doc
LP-407-3 — Write the Contract rules on the wired tags · 5 pts
Write PC-2/3/4/5/6/8/9 specs against the now-produced tags
Judgmental ones → calibration path (scenario fixture + Priya); structural/calculative → straight to the gate
Report each rule's real verdict on a fixture
Tests + doc
LP-407-4 — Wire + write DT-2/4/5 · 5 pts
The 3 DTI rules that don't need the credit report (unlike DT-1)
Wire their tags from homeowners_insurance / hoa_statement / property_tax_bill (the housing-expense side)
Write the rules; prove they fire
Explicitly note: DT-1 (back-end ratio) is NOT in scope — it's credit-report-gated (LP-405)
Tests + doc
Standalone tickets
LP-408 — Priya's two candidate rules (needs-definition) · 3 pts · blocked on Priya
Rule A: pay-stub-only income (no W-2/1099) → flag; needs her definition of "how recent" a stub must be
Rule B: terminated/lapsed VOE → require offer letter + ≥1 pay stub; needs her definition of "terminated"
Inputs are already extracted — structural (document presence), no new producer
Get both definitions first, then write; ship validated=false until she confirms any threshold
Tests + doc
LP-409 — Correct the roadmap (§13) from LP-405 · 1 pt
Bucket 2: ~10-15 → 4 rules
DTI is extractor-gated (DT-1 reads unproduced credit-report tags) — retract the "~28-rule deterministic wave"
Add Bucket 2.5 (~10 wiring-only rules)
Narrow the real Bucket 4 gate to five documents: credit, title, appraisal, AUS, MI cert
Note LP-394's "~58 needs-extractor" is overstated
Record OC-3 out of Bucket 2 (occupancy.rental_support has no producer — same blocker as IN-14)
Board summary
ticket	pts	depends on	risk
LP-406-1 PC-7	2	—	low
LP-406-2 AS-8	3	—	low
LP-406-3 IN-6	3	—	low (Priya tolerance?)
LP-406-4 OC-1	3	—	med — spec-wording trap
LP-407-1 audit	2	—	low (read-only)
LP-407-2 wire Contract	5	407-1	med
LP-407-3 write Contract	5	407-2	med
LP-407-4 DT-2/4/5	5	407-1	med
LP-408 Priya's 2	3	Priya	low
LP-409 roadmap fix	1	—	—

~34 points, ~10 tickets, ~16 rules — taking you from 24 → ~40 live (~34% of in-scope) with no new extractor.

Start with LP-409 (1 pt — stops you building against a stale plan), then LP-406-1/2 in parallel with LP-407-1's audit.






=======

EPIC LP-407 — Bucket 2.5: wire the rules whose extractors already exist

Audit outcome (LP-407-1): the true wire-and-write count is ~2, not ~10. Four rules need small derived producers; four need an extractor extension; two are confirmed Bucket 4.
Revised DoD: each of the 8 reachable rules live, or held with a named blocker. PC-1/DT-1 excluded (Bucket 4).

✅ LP-407-1 — The four-gate audit · 3 pts · DONE
Audited all 12 candidates against inputs / expressibility / AI-calibration / threshold
Found: ~2 wire-and-write, 4 needs-derived-producer, 4 needs-extractor-extension, 2 Bucket 4
Confirmed the catch-all fields are real; confirmed DT-1 credit-gated; found PC-1 partly reachable

LP-407-2 — Wire tags + build the monthly-conversion producer · 5 pts · NEXT

Unblocks: PC-2, DT-5, DT-2, DT-4

Resolve DT-5's "redundancy caveat" from the audit first — if it duplicates a live rule, that's a boundary to draw, not a free rule
Wire PC-2's tags (contract sale price vs the loan file) from the live purchase_agreement extractor
Wire DT-5's tags from the housing-expense extractors
Build the monthly-conversion producer for DT-2/DT-4 (housing-expense components) — mirrors housing.insurance_monthly
Tags describe, rules judge — no threshold inside a producer (the LP-410 discipline)
Prove each tag materializes at the subject its rule will read (the ID-5 check, before any spec exists)
Report each tag's real value on a fixture
No rules written; additive only

LP-407-3 — Write PC-2, DT-5, DT-2, DT-4 · 5 pts · depends on 407-2
Four trivial deterministic specs branching on the wired/derived tags
Apply the Bucket 2 patterns: applicability predicate for any not_applicable case; per-branch needs_review if an input carries a known FP residue (ADR-325)
Plain-language reasons; interpolate numbers where there's a real operand (the PC-7 pattern)
Report each rule's real verdict on a fixture; activate what clears the gate
Expected: 27 → ~31
LP-407-4 — PC-3: address-normalize tag + rule · 3 pts

Unblocks: PC-3 (does the contract's property address match the file?)

Build the address-normalize derived tag — mirrors id.address_normalized
Watch the known address trap: MISMO stores the first ADDRESS regardless of type, so current_address_line can hold a mailing address. Consult current_address_type; never compare against a mailing address
Write PC-3's spec; activate if it clears
LP-407-5 — Settle the AS-2 / PC-5 boundary, then write PC-5 · 5 pts

Unblocks: PC-5 (does the contract's earnest money match the bank-statement deposit?)

First: the boundary. Live AS-2 currently approximates this cross-document EMD match, and its own spec says the real check is "not cleanly expressible today"
Decide: does PC-5 replace AS-2's approximation, complement it, or does AS-2 narrow its scope? Two rules firing on one finding is processor noise
Then build the EMD-match derived producer and write PC-5
⚠️ Touches a live rule — any AS-2 change needs its own equivalence proof
LP-407-6 — Extend the purchase_agreement extractor · 5 pts · ⚠️ Bucket 4 discipline

Unblocks: PC-4, PC-6, PC-8, PC-9

The audit confirmed seller credit, addenda, personal property, and contingency dates are catch-all only (additional_sections) — not typed-core
Add typed extraction for the four fields
This is an extractor change: there is no independent source-of-truth to catch a misread. Requires a golden-file eval (LP-143 pattern) — non-negotiable
Report extraction accuracy per field before anything consumes it
LP-407-7 — Write PC-4, PC-6, PC-8, PC-9 · 5 pts · depends on 407-6
Four Contract rules (seller credit, addenda, personal property, contingency dates)
Re-run gates 2–4 per rule before writing (relation class, any AI tag, any Priya threshold)
Activate what clears
Expected: ~31 → ~35 if all four clear
Board
ticket	pts	rules	depends on	risk
✅ LP-407-1 audit	3	—	—	done
LP-407-2 wire + producer	5	(unblocks 4)	407-1	low
LP-407-3 write the 4 rules	5	+4	407-2	low
LP-407-4 PC-3	3	+1	—	low-med
LP-407-5 PC-5 + AS-2 boundary	5	+1	—	med — touches a live rule
LP-407-6 extractor extension	5	—	—	high — golden-file needed
LP-407-7 PC-4/6/8/9	5	+4	407-6	med

~31 points, 6 tickets, up to 10 rules → 27 → ~37 live.

Start: LP-407-2. Lowest risk, unblocks four rules, no extractor change, and it follows the LP-410 → rule-ticket shape that worked cleanly in Bucket 2.

Not started yet and deliberately later: LP-407-6, because a mis-read extractor field silently corrupts every rule downstream of it — the exact reason Bucket 4 needs golden-file evals.
