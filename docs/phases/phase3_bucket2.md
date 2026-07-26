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
