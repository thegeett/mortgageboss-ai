Nine categories left, covering roughly 120 rules. Here's the honest breakdown.
Done (1 of 10)
Identity (ID-1..ID-10) — nine rules live, ID-10 correctly out-of-scope. Pending LP-323-ID-C (the eval).
Plus two orphans from before the wave system: AS-1 (assets) and OC-2 (occupancy) — built and validated, but their families aren't done.
Remaining (9 categories, ~120 rules)
CategoryRulesNotesIncome (IN)~14Biggest family. Natural wave 2 — exercises consistency, dates, per-borrower judgment, and calculator inputs

Assets (AS)~11 moreAS-1 done; AS-2..AS-12 remain

Credit (CR)~13Blocked — credit report is a blocker document (PDF-only, nested schema, no cross-check)

Property (PR)~8Blocked — appraisal is a blocker document (UAD 2.6/3.6 cutover)

DTI (DT)~7Depends on the calculators; LP-318's Caveat A is relevant

Title (TI)~6

Insurance/Hazard (IH)~8

Condo (CO)~5Priya's team works condos — warrantable vs non-warrantable, not just questionnaire-presence

Purchase/Program + MI + AUS + Fraud + Occupancy remainder (PC/PE/MI/AU/FR/OC)~30Several small families; could be grouped

Plus CL (closing) and DC (disclosures) — mostly out-of-scope per the earlier classification, so they'd resolve to not_applicable rather than needing waves.


2. The remaining waves (~21 tickets)
   CategoryRulesTicketsAssets (AS-2..AS-12)~113DTI~73Title~63Insurance/Hazard~83Condo~53Small families (program/MI/AUS/fraud/occupancy)~306
3. Blocked on blocker documents (~6 tickets + extractors)
   Credit (~13) and Property (~8) cannot activate until the credit report, DU/AUS findings, and appraisal are extractable. PDF-only, deeply nested schemas, no independent cross-check source. Needs the golden-file eval set (LP-143) built alongside the first extractor. That's 3-4 extractor tickets + 6 wave tickets.
4. The product (unestimated, and the biggest)

The UI — four tabs, finding detail, upload + re-run, resolve/override/waive actions. Doesn't exist. This is the gap between an engine and something Priya can use.
Priya's session — ~40 items by the time all waves land
Breadth validation — everything is validated on LF-6T3N (one conventional purchase) + synthetic. No jumbo, FHA, condo, self-employed, or refinance corpus.
The mortgageboss-synthetic tool completion
