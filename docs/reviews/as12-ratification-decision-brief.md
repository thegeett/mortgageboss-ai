# Decision brief — AS-12 asks a human to ratify every deposit

**Status:** decision needed before any implementation
**Scope:** AS-12 (borrowed funds detection), and by extension every `ships: ratify` judgment rule
**Needs:** a domain ruling (the mortgage question) + a product ruling (the safety/noise trade)

---

## 1. What is happening

AS-12 asks, per bank-statement deposit: *do this deposit's characteristics suggest an undisclosed
BORROWED source?* It is a **judgmental** rule with `ships: ratify`, so the evaluator assigns:

```python
# 3. Ratification-pending verdict ... MANDATORY: always needs_review.
Verdict.NEEDS_REVIEW
```

**Every verdict routes to a human — including a confident "no".** The AI's own answer is written into the
finding's provenance, not into the verdict. So a deposit the model is 95% sure is payroll still lands in
the processor's Needs-attention tab as an item to ratify.

## 2. The evidence

On LF-WCHG, AS-12 produced **10 needs_review findings — 33% of the 30 remaining**. All ten, with the
amounts (from AS-1, which evaluated the same subjects):

| Category | Count | Amounts | What the AI said |
|---|---|---|---|
| `payroll` | 4 | $3,298.74 / $3,311.48 / $3,312.27 / $3,356.56 | *"Direct deposit from 'Sunovion Pharm' to the account holder's name, clearly indicating a payroll payment"* — confidence 0.90–0.95 |
| `transfer_own` | 6 | $1,000 / $2,000 ×4 / $3,000 | *"A2A transfer from Digital Federal Credit Union in the borrower's name to Wells Fargo, appears to be between the borrower's own accounts"* — confidence 0.90 |

**Zero of the ten are borrowed-funds candidates.** Not one gift, loan proceed, unidentified wire or
third-party transfer. Every one is the borrower's salary or their own money moving between their own
accounts — and the model said so, confidently, and was overruled by the mechanism.

This is AFTER the LP-509-A1 fix. Before it, the same rule ran on 57 subjects including ATM fees and
utility bills. A1 fixed the *scope*; this is about what remains in scope.

## 3. THE HEADLINE: AS-12 is missing the materiality threshold its own sibling already has

`txn.amount` appears in AS-12 only under `subject_key_fields` (it identifies WHICH transaction). It is
absent from `load_bearing_tags` and `reasoned_over`, and the spec states **"No numeric threshold"**.

**AS-1 — the sibling rule, same guideline family (Fannie B3-4.2) — already encodes the standard:**

```yaml
large_deposit_threshold: "50% of total monthly qualifying income"
```

and reads `income.qualifying_monthly` as its threshold operand.

### What that means on this file

| | |
|---|---|
| Monthly qualifying income | ≈ **$13,154** (gross) |
| 50% threshold | ≈ **$6,577** |
| Largest deposit of the ten | **$3,356** |

**All ten fall below the threshold.** AS-1 evaluated these same ten deposits and returned `satisfied` on
every one — *because it applies the test*. AS-12 escalated all ten to a human — *because it does not*.

Two rules, same subjects, same guideline, opposite outcomes. The only difference is the materiality test.

⚠️ **Correction to an earlier assessment in this work:** it was first stated that "a threshold would
remove none of this file's ten findings". That was wrong — it assumed a *trivial-deposit floor* (is it
over $100?) rather than a *materiality threshold relative to income*. At the Fannie standard, the
threshold removes all ten on its own.

### AS-12 also contradicts its own prompt

The prompt asks the model to find:

> *"a large round-dollar deposit with no payroll/transfer trace ... or funds appearing just before
> closing with no source"*

It is asked to judge LARGENESS, ROUND-DOLLAR-NESS and PROXIMITY TO CLOSING — and is handed
`apparent_category`, `has_identified_source` and `counterparty`. **No amount. No date.** It cannot
observe any of the three signals it is being asked for.

Note the irony: the six own-transfers are all round-dollar ($1,000–$3,000), exactly the shape the prompt
calls a signal. They are flagged — but not because of that signal, since the model cannot see the
amounts. They are flagged because ratification is unconditional.

## 4. What "monthly qualifying income" means (and why it is fragile)

The income an underwriter is **allowed to count** — the denominator of DTI. Not simply what the borrower
earns; three filters narrow it: **continuity** (likely to continue 3+ years), **averaging** (variable pay
averaged over ~2 years, not taken at its peak), and **documentation**.

The system models the narrowing as three tags:

| Tag | Meaning | Produced by |
|---|---|---|
| `income.stated_monthly` | what the borrower **claims** on the application | parsed (MISMO) |
| `income.documented_monthly` | what the **documents prove** | AI |
| `income.qualifying_monthly` | what is **usable for qualifying** after continuity/averaging | AI (hybrid) |

**It is GROSS, not net** — which explains this file's numbers: the payroll *deposits* are ~$3,300 (net,
what lands in the bank) while gross monthly is ~$13,154. A threshold on gross therefore clears
net-sized deposits comfortably.

⚠️ **The fragility.** `income.qualifying_monthly` is AI-produced and the hardest of the three (continuity
and averaging are judgement calls). And on this very file IN-3 cannot resolve even the simpler
`documented_monthly` — it abstains on conflicting figures across documents (LP-515).

So a threshold of "50% of qualifying income" inherits that fragility: **when qualifying income is
unknown, AS-12 must abstain rather than default** — which would turn today's 10 ratifications into 10
`couldnt_check`s. Not obviously better. The fallback has to be decided deliberately (see §8, Q6).

## 5. Why the current design exists (the steelman)

Ratification is not an oversight — it is LP-376-B / ADR-378, deliberately:

- An AI verdict must **never auto-assert**. Ratification is the substitute safety for a tag whose
  accuracy is not measured (or only self-consistency rated).
- The failure it prevents is severe and silent: a confident-but-wrong "no" would clear a genuinely
  borrowed deposit with no human ever seeing it. Undisclosed borrowed funds understate the DTI and
  misstate the source of funds — precisely what the rule exists to catch.
- Priya signed off the bar on that understanding (LP-390-7).

Any change to the ratification mechanism itself spends real safety. **A threshold does not** — it is a
scope question, not a trust question.

## 6. Why it is nevertheless a problem

**Ratification fatigue destroys the control it implements.** Ten items per file where zero are plausible
teaches a processor that AS-12 is noise. Once they click through reflexively, the ratification is a
rubber stamp — the safety is gone anyway, and now it is *also* invisible, because the audit trail says a
human reviewed it.

A control a human stops reading is worse than no control, because it looks like assurance.

## 7. The options

**A — Status quo.** Every verdict ratified. ~10 rows/file of near-certain noise; fatigue risk as above.

**B — A confident "no" auto-satisfies.** Only `yes`, `unknown` or below-floor answers reach a human.
**Risk:** a wrong confident "no" silently clears a real borrowed deposit — the exact failure the design
prevents. Should not be done on an unmeasured tag.

**C — Scope by category.** An applicability predicate excluding `payroll` / `transfer_own`. The
LP-509-A1 shape. **Domain risk:** `transfer_own` may hide borrowed funds — the money in the *other*
account could itself have been borrowed, and `has_identified_source` proves the immediate hop, not the
origin. 6 of the 10 are this category.

**D — Aggregate the presentation.** Collapse the rows into one ("10 deposits reviewed, none suspicious —
expand"). The frontend already has `groupBySameReason`. Changes nothing in the engine.

**E — Apply AS-1's materiality threshold.** Give AS-12 the amount, and scope out deposits below 50% of
monthly qualifying income. **Removes all ten on this file.** Uses an existing, agency-sourced number
already encoded in the sibling rule.

## 8. Recommendation

**E first, then D. C only if E is insufficient. Not B.**

E is better than C on three counts:

1. **It sidesteps the hard domain question.** No ruling needed on whether `transfer_own` can hide
   borrowed funds — a $2,000 transfer is immaterial either way at this income.
2. **It rests on agency guidance**, not an invented category list. One number to sign off, already
   present in AS-1, rather than a taxonomy to defend.
3. **It loses no coverage.** A genuinely suspicious $50,000 wire still fires, whatever its category. C by
   contrast permanently blinds the rule to an entire category.

E also fixes the prompt/inputs contradiction in §3 as a side effect: giving the model `txn.amount` (and
the date) lets it actually judge "large", "round-dollar" and "just before closing".

D then makes whatever remains legible. B trades real safety for quiet and should be earned by
measurement — the accuracy of `as.borrowed_funds` on "no" answers specifically — not assumed.

## 9. What needs deciding

**Domain (needs the mortgage expert):**

1. **Confirm the threshold: is 50% of monthly qualifying income the right test for AS-12**, as it already
   is for AS-1? (AS-1's own spec records it as NOT yet Priya-confirmed.)
2. Should the threshold be the same for a **refinance** as a purchase? On a rate/term refi the borrower
   brings no funds to close, so deposit sourcing is arguably less material. LF-WCHG is a refinance.
3. **Is an own-account transfer ever a borrowed-funds concern** — i.e. is C still wanted on top of E?
   The money in the other account may itself have been borrowed.
4. Does a large round-dollar transfer shortly before closing change the answer to (3)?

**Product / risk:**

5. Should a confident "no" from a judgment rule ever auto-clear, or is ratification absolute? This
   generalises to every `ships: ratify` rule.
6. **When `income.qualifying_monthly` is unknown, what should AS-12 do?** Abstain (10 couldnt_checks),
   fall back to `income.documented_monthly`, fall back to a fixed floor, or ratify as today? This is the
   question that decides whether E actually helps in practice, because that input is unreliable today.
7. What is an acceptable number of ratifications per file?

## 10. Implementation sketch

**E** — add `txn.amount` to `reasoned_over` (so the model can judge the signals its prompt names) and an
operand comparing it to `income.qualifying_monthly × 0.5`, mirroring AS-1. The §8 honesty contract still
applies: an ABSENT or `unknown` amount or income must abstain, never be silently exempted.

**C** (if also wanted) — an `applicability` predicate on the judgment block. The predicate DSL supports
only `eq`/`ne` against a single value, so a multi-category exemption needs a derived boolean tag or a
small DSL extension. Worth knowing before scoping; not a blocker.
