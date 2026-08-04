# Priya's domain rulings — August 2026

The resident domain expert ("sister") answered six outstanding questions in substantial detail. This file
**records** them — it does not implement them. Each ruling is kept in **her own framing**, because the nuance
(*"the label alone is not enough"*, *"do not average a one-time award"*) is exactly the part that matters when
someone builds it. **Do not convert a ruling into an implementation while reading it** — several change how
rules are STORED, and a half-applied design is worse than a recorded one.

> ⚠️ **Provenance.** These are her rulings as of **2026-08**, citing agency guidance that has effective dates
> and CHANGES. A future reader must re-check the agency source before relying on a value. Where a ruling
> SUPERSEDES an earlier one, that is called out (Ruling 2).

**Index:** [1 Earnings classification](#ruling-1--earnings-classification) · [2 Declining income
(SUPERSEDES LP-393-6)](#ruling-2--declining-income--supersedes-lp-393-6) · [3 NSF / overdraft](#ruling-3--nsf--overdraft-an-internal-policy-not-an-agency-rule)
· [4 Agency differences (architectural)](#ruling-4--agency-differences-architectural) · [5 Reserve
eligibility](#ruling-5--reserve-eligibility) · [6 Gift funds](#ruling-6--gift-funds) · [Open items](#still-open)

---

## Ruling 1 — Earnings classification

**Question asked.** How should the pay-stub earnings lines (base vs variable vs non-cash) be classified for
qualifying income — is it a lookup on the line's text label?

**Her answer (her framing).** ⚠️ **"Do not classify solely from the text label."** She gave a **decision
procedure**, not a label list — a fail-closed cascade:

```
if not cash payment                                                  -> NONCASH_BENEFIT, qualifying_amount = 0
elif guaranteed AND fixed AND not performance-dependent              -> FIXED_BASE_INCOME
elif depends on performance / productivity / discretion / annual plan results
                                                                     -> VARIABLE_EMPLOYMENT_INCOME
else                                                                 -> UNKNOWN
                                                                        request_employer_earning_code_definition = true
```

⚠️ **The `UNKNOWN` branch is load-bearing.** An unrecognised label must **NOT** silently become base income — it
falls to `UNKNOWN` and **requests the employer's earning-code definition**. This is the fail-closed procedure and
it is the point of the ruling.

**Production defaults for the real labels found in the corpus** (defaults, not a substitute for the procedure):

| label | classification | treatment |
|---|---|---|
| Annual Incentive Plan Bonus | VARIABLE / BONUS | average with history + trend; confirm continuance |
| Physician Quality Bonus | VARIABLE / QUALITY_INCENTIVE | analyse separately from base; **must not be merged into base merely because it appears every period** |
| Productivity Pay | VARIABLE / PRODUCTIVITY_INCENTIVE | **variable UNLESS the employer verifies it is guaranteed — the label alone is not enough** |
| Recognition Bonus | VARIABLE / DISCRETIONARY, recurrence UNKNOWN_OR_ONE_TIME | **normally EXCLUDE.** *"Do not average a one-time award merely because it appears in year-to-date wages."* |
| Basic Life Imputed | NONCASH_FRINGE / IMPUTED_LIFE_INSURANCE | **qualifying income = 0**; excluded from gross cash earnings |

**Same non-cash treatment applies to:** Taxable Excess Life · Spouse Supplemental Life Imputed · Group Term Life
· GTL Imputed · Domestic Partner Imputed — *"unless payroll documentation proves an actual cash payment was
made."*

**Each variable component is analysed on its own.** *"Treat each as a separate component because their stability
and likelihood of continuance may differ"* — so **NOT** a single base/variable split; each variable component is
analysed separately.

**Affects.** IN-10, IN-11, and any income classifier (the `earnings_lines` consumer LP-448 scoped).

**What remains open.** The classifier is unbuilt. LP-448 concluded this is judgment, not a lookup, and needs
this ruling — now recorded. ⚠️ **`earnings_lines` may be null in the stored corpus** (LP-446 added it; the
stored extractions predate that), so the classifier may have nothing to read until a re-extraction.

---

## Ruling 2 — Declining income ⚠️ SUPERSEDES LP-393-6

**Question asked.** When income declines year-over-year, is that an automatic failure?

**Her answer (her framing).** **Flag for review — but do NOT automatically classify total income as declining.**
Her worked example:

```
base_income_trend   = DECLINING
bonus_income_trend  = INCREASING
total_income_trend  = STABLE
income_review_result = FLAG
```

**Production decision (verbatim).** *"Component-level decline = NEEDS_REVIEW; total qualifying income decline =
separate result. **Do not make 'any year-over-year decrease' an automatic failure.**"*

> ⚠️ **THIS SUPERSEDES the earlier `is_declining` ruling recorded in LP-393-6.**
> - **Superseded (LP-393-6, do NOT follow):** *"any YoY decrease = declining, no materiality threshold"*,
>   applied at the **borrower level** (the `income.is_declining` tag: "a year-over-year decrease" over the
>   borrower's documents — decisions.md ADR context, income_stability prompt).
> - **Current (this ruling):** decline is assessed **per component**; a **component** decline → `NEEDS_REVIEW`;
>   a **total qualifying income** decline is a **separate** result. A year-over-year decrease is **not** an
>   automatic failure. A future reader must follow THIS, not the LP-393-6 framing.

**The false-positive traps she names — exclude drops caused solely by:** partial-year employment · unpaid leave
· payroll timing · a job change. **For salary, compare the verified annual RATE, not W-2 totals. For hourly,
compare rate and normalised hours.**

**Affects.** IN-10, IN-11.

**What remains open.** IN-10/IN-11 currently read a single borrower-level `income.is_declining` AI tag scored
under the superseded framing (LP-393-6, `is_declining` 13/13 at 0.95/0.90 auto). Moving to per-component decline
is a re-architecture + a re-score, not a value change — its own ticket (the LP-448 recalibration question).

---

## Ruling 3 — NSF / overdraft: an INTERNAL policy, not an agency rule

**Question asked.** What is the permissible number of overdrafts/NSFs?

**Her answer (her framing).** *"The agencies do not establish a fixed number of permissible overdrafts. Your
numerical threshold must be labeled as an **internal processing policy**, not an agency eligibility rule."*

| activity in the reviewed period | result |
|---|---|
| none | CLEAR |
| one isolated event | REVIEW_ONLY — *"should not by itself fail the file"* |
| two in the same statement month, **or** events in two or more months | FLAG_PATTERN |
| three or more in the review period | HIGH_PRIORITY_FLAG |
| negative ending balance | HIGH_PRIORITY_FLAG |
| NSF causes a cash-to-close or reserve shortfall | asset-insufficiency finding |
| unpaid overdraft balance or overdraft line | **potential undisclosed liability** |
| event after the latest verified statement | reverification required |

⚠️ **Event TYPE matters, not just the count** — six types to distinguish: `nsf_fee` ·
`overdraft_transfer_from_savings` · `overdraft_line_of_credit_advance` · `returned_payment` ·
`negative_daily_balance` · `negative_ending_balance`.

> *"An automatic transfer from the borrower's own savings is less concerning than a returned mortgage payment or
> repeated use of an overdraft credit line."*

**Affects.** AS-7.

**What remains open.** The AS-7 threshold must be labelled an **internal processing policy** (not agency), and
event TYPE is needed — so the **bank-statement extractor likely needs the event type, not merely a count**
(`stmt.nsf_count` / `txn.is_nsf_or_overdraft` today capture presence/count, not the six-way type). A schema
addition, its own ticket (E4, Geet's decision per the AS-7 gate).

---

## Ruling 4 — Agency differences (architectural)

**Question asked.** When Fannie / Freddie / FHA differ, should the system use the strictest rule?

**Her answer (her framing).** **Store ALL agency rules and select the applicable one. Do NOT use the strictest
globally.**

> *"Using the strictest would incorrectly reject loans that are eligible under the actual program, and make the
> system unable to explain which authority produced the finding."*

**Precedence (highest first):** law/regulation → loan program → agency/investor → underwriting method + AUS
findings → product rules → lender/investor overlays → internal processing policy.

**Her suggested structure — an agency-VERSIONED rule:**

```json
{"rule_family": "STUDENT_LOAN_PAYMENT",
 "versions": [{"authority": "FANNIE_MAE", "effective_from": "2026-01-01", "logic": "..."},
              {"authority": "FREDDIE_MAC", "effective_from": "2026-01-01", "logic": "..."},
              {"authority": "FHA",         "effective_from": "2026-01-01", "logic": "..."}]}
```

**Selector inputs:** agency · program · product · underwriting method · AUS recommendation ·
application/note/case-assignment date · investor · overlay version.

⚠️ **When the agency is not yet selected, return COMPARATIVE results** — `Fannie = X`, `Freddie = Y`,
`FHA = n/a`, `final = UNKNOWN_PENDING_AGENCY_SELECTION`. **Do not silently choose one.**

⚠️ **The warning that lands on the current design:** *"A lender may deliberately adopt a conservative overlay,
but that should be stored as an explicit `LENDER_OVERLAY`, **not disguised as agency policy**."*

**⚠️ Record plainly:** `activation_bars.yaml` holds **ONE threshold per rule and CANNOT express this** (an
agency-versioned rule with a selector). This is an **architectural decision, not a threshold** — six rules are
gated on the DESIGN, not on a number.

**Affects.** CR-9, DT-1, AS-3, PC-4, PR-1, and **CR-7's minimum** — six rules gated on a design decision.

**What remains open.** The agency-versioned rule structure + selector is **described here, implemented nowhere**.
It is E2's question (the agency/overlay design). Until it exists, these six rules cannot encode their (non-flat,
agency-specific) thresholds — the LP-455 finding.

---

## Ruling 5 — Reserve eligibility

**Question asked.** Which assets count as reserves, and what haircut applies to retirement accounts?

**Her answer (her framing).**

**Eligible:** checking/savings 100% · money market 100% · CD 100% (subject to accessibility/penalty) · publicly
traded securities at verified eligible value · vested retirement at verified accessible value · trust at the
borrower's accessible interest · vested life-insurance cash surrender value.

**Excluded (Fannie):** unvested funds · inaccessible retirement · unlisted private stock · unsecured loans ·
interested-party and lender contributions · subject-property cash-out proceeds · **gift of equity**.

⚠️ **Retirement accounts — the haircut is AGENCY-SPECIFIC** (this corrects a widespread "blanket 60/70%"
assumption):

| agency | treatment |
|---|---|
| **Fannie** | ⚠️ **"Do NOT apply a blanket 60% or 70% haircut."** Verified vested accessible balance − account loans − pledged amounts |
| **Freddie** | documented vested balance/percentage; reserves generally need no liquidation |
| **FHA** | **60% × account value − existing loans**, unless documentation establishes a higher available amount |

> *"Withdrawal is not required when the retirement account is used only for reserves."*
> *"Do not store just one adjusted balance."*

**Affects.** AS-4, AS-3.

**What remains open.** This is **Ruling 4's pattern again** — the reserve value depends on the agency, so AS-4/
AS-3 cannot store a single adjusted balance or a single threshold. Gated on the agency-versioned structure
(Ruling 4).

---

## Ruling 6 — Gift funds

**Question asked.** Are gift funds eligible as reserves?

**Her answer (her framing).** Recorded within the reserve treatment: **eligible gift funds are agency- and
transaction-specific; a gift of equity is NOT eligible as reserves under Fannie Mae.**

**Affects.** AS-5.

**What remains open.** AS-5's gift DESIGN (a descriptive tag vs a conclusion) is still undecided (below).

---

## Still open

- **AS-5's gift design** — tag vs conclusion — still undecided.
- **The agency-versioned rule structure (Ruling 4)** — described here, **implemented nowhere**; no current
  mechanism supports it (`activation_bars.yaml` holds one threshold per rule). Six rules wait on it.
- **AS-7's event types (Ruling 3)** — likely a bank-statement schema addition (the six-way event type).
- **`earnings_lines` population (Ruling 1)** — LP-446 added it; the stored extractions predate that, so the
  classifier may have **nothing to read until a re-extraction** (a budget/corpus blocker, per LP-454/ADR-354).
