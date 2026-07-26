Bucket 1 — Finish the written rules (24 → 34 live, ~10 rules)

These have specs; each needs one specific unblock:

rule(s)	blocked on	ticket type
AS-6	in flight — LP-404 (the rule change) + Priya's bar	nearly done
IN-8, IN-9	a VOE + offer-letter scenario	fixture (LP-393 pattern)
IN-13	an other-income scenario (pension/alimony) + income.type producer	fixture + producer
IN-12	a borrower-level self-employment producer	producer
IN-14	an occupancy.rental_support producer	producer
AS-7	an NSF producer (confirmed orphan)	producer
AS-3	the §3B cash-to-close calculator	calculator (large)
AS-4	Priya's reserve-eligibility definition + prompt fix	domain + prompt
AS-5	the gift-as-tag-vs-conclusion design call	decision

~9 tickets.

Bucket 2 — The unwritten rules whose inputs already exist (~10-15 rules)

Their source documents are already extracted (pay stubs, bank statements, MISMO):

IN-6 (pay-stub ↔ W-2 coverage), AS-8 (statement chaining), OC-1/OC-3 (occupancy)
The DTI and Contract rules that read MISMO fields
The two new candidate rules from Priya's rulings (pay-stub-only → W-2/1099; terminated employment → offer letter + pay stub)

~5-7 tickets, low risk — write, calibrate if judgmental, activate.

Bucket 3 — The deterministic waves (~25-30 rules)

Mostly structural/calculative, activate fast, but each needs its rules written and (where judgmental) a scenario fixture:

DTI (7) — ratios, limits by program
Title (6) — vesting, liens, legal description
Insurance/Hazard (8) — coverage vs loan, dates, mortgagee clause, flood
Program/Conv-FHA (4-5) — program-specific eligibility

~10-12 tickets. Condo (5) also sits here but needs calibration (warrantable vs non-warrantable questionnaire reading).

Bucket 4 — The extractor infrastructure (the real remaining project)

This is where ~58 of the 84 unwritten rules gate. Each blocker document is PDF-only with no independent source-of-truth, so each extractor needs an LP-143 golden-file eval built alongside it:

extractor	rules gated	difficulty
Credit report	13 (largest category)	high — nested tradelines, scores, public records, inquiries
Appraisal	8	high — UAD 2.6 and 3.6 through Nov 2026
DU/AUS findings	4	medium
Title	6	medium
Insurance	8	medium
Condo	5	medium (warrantability)
MI cert	5	medium
Contract	9	medium

~12-15 extractor + eval tickets, then ~25-30 rule-writing tickets riding on them.

Bucket 5 — Judgment-heavy remainder (~10 rules)

Fraud (6), REO (2), LOE (2) — scattered, mostly needing scenarios and calibration. ~4-5 tickets.

Cross-cutting hardening (not new rules, but needed)
Backfill bars for the 11 base rules (the gate-tracking gap — they operate outside the activation machinery)
The loader cross-check (reject ships: auto on a judgmental rule — the IN-7 lie-catching gap)
IN-11's over-fire (fires on any income lacking history, not just variable)
IN-7's kind reclassification (if Priya wants it auto)
The D5 scope fix (widen stmt_facts to investment statements so AS-6 covers brokerage accounts)
Phase 7 security hardening (~3-4 weeks) — MFA, rate limiting, malware scanning, audit logging — required before any real-PII staging
The honest total
bucket	rules	tickets	risk
1 — finish written	+10	~9	low-med
2 — inputs exist	+12	~6	low
3 — deterministic waves	+28	~12	low-med
4 — extractors + rules	+43	~40	high
5 — judgment remainder	+10	~5	med
hardening	0	~8	—

Roughly 80 tickets to 118 in-scope rules (plus Phase 7 security as a separate track).

The shape of it
The first ~50% of remaining rules is fast (Buckets 1-3, ~55 rules, ~27 tickets, low risk) — proven patterns, mostly structural.
The last ~40% is the real project (Bucket 4, ~43 rules behind extractors) — carrying the majority of the effort and nearly all the risk, because those documents have nothing to cross-check a misread against.
The machinery is done. Calibration loop, scenario fixtures, activation gate, discrepancy-surfacing — all proven. Nothing left is a mystery; everything is a known type of work.
The sequencing I'd recommend
Finish AS-6 (LP-404 + Priya's bar) — you're one ticket away
Bucket 1's cheap unblocks — the fixtures (VOE/offer-letter, other-income) and the base-rule hardening
A deterministic wave — DTI or Title — fast coverage, ~20% → ~40%
Then commit to the Credit extractor (Phase 0 scoping first) — the largest single category and the gateway to the extractor phase
Bucket 4 in earnest — one extractor + its evals + its rules at a time
Phase 7 security — before Priya touches real files in staging

The strategic truth from the census: you can't finish this without the extractors, and they're the biggest block, not the smallest. Everything before them is momentum; they're the mountain.
