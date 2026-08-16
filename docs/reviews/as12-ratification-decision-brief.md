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

On LF-WCHG, AS-12 produced **10 needs_review findings — 33% of the 30 remaining**. Here is all ten,
from the rule's own load-bearing tags:

| Category | Count | What the AI said |
|---|---|---|
| `payroll` | 4 | *"Direct deposit from 'Sunovion Pharm' to the account holder's name, clearly indicating a payroll payment"* — confidence 0.90–0.95 |
| `transfer_own` | 6 | *"A2A transfer from Digital Federal Credit Union in the borrower's name to Wells Fargo, appears to be between the borrower's own accounts"* — confidence 0.90 |

**Zero of the ten are borrowed-funds candidates.** Not one gift, loan proceed, unidentified wire or
third-party transfer. Every one is the borrower's salary or their own money moving between their own
accounts — and the model said so, confidently, and was overruled by the mechanism.

Note this is AFTER the LP-509-A1 fix. Before it, the same rule ran on 57 subjects including ATM fees and
utility bills. A1 fixed the *scope*; this is about what remains in scope.

## 2b. AS-12 has NO amount threshold — and never sees the amount

`txn.amount` appears in AS-12 only under `subject_key_fields` (it identifies WHICH transaction). It is
absent from both `load_bearing_tags` and `reasoned_over`, and the spec states "No numeric threshold".
AS-1, by contrast, gates on `txn.amount`.

**This contradicts the rule's own criteria.** The prompt asks the model to find:

> *"a large round-dollar deposit with no payroll/transfer trace ... or funds appearing just before
> closing with no source"*

It is asked to judge LARGENESS, ROUND-DOLLAR-NESS and PROXIMITY TO CLOSING, and is handed
`apparent_category`, `has_identified_source` and `counterparty`. No amount. No date. It cannot observe
any of the three signals it is being asked for.

The amounts on LF-WCHG:

| | Amounts |
|---|---|
| 4 x payroll | $3,298.74, $3,311.48, $3,312.27, $3,356.56 — consistent semi-monthly salary |
| 6 x own-transfer | $1,000, $2,000 x4, $3,000 — **all round-dollar** |

⚠️ **A threshold would remove NONE of this file's ten findings** (the smallest is $1,000). This is a real
defect but it is not the lever for the noise in §2 — the category exemption is. Stated explicitly so the
two are not conflated:

1. **Give the model `txn.amount` and the transaction date** — a CORRECTNESS fix. The rule currently asks
   a question it has disabled itself from answering, which likely degrades its judgement on a file that
   does contain a suspicious deposit.
2. **Add a materiality floor** — a NOISE fix for OTHER files. Needs a number from the domain expert, and
   probably a relative one: Fannie B3-4.2 frames large deposits relative to the transaction rather than
   as a fixed dollar figure, so a percentage of the loan amount or of monthly income may be the right
   shape rather than an absolute.

Note the irony: the six round-dollar transfers are exactly the shape the prompt calls a borrowed-funds
signal. They are flagged — but not BECAUSE of that signal, since the model cannot see the amounts. They
are flagged because ratification is unconditional.

## 3. Why the current design exists (the steelman)

This is not an oversight — it is LP-376-B / ADR-378, deliberately:

- An AI verdict must **never auto-assert**. Ratification is the safety substitute for a tag whose
  accuracy is not measured (or is only self-consistency rated).
- The failure it prevents is severe and silent: if a confident "no" auto-cleared, a model that wrongly
  says "no" on a genuinely borrowed deposit would clear it with no human ever seeing it. Undisclosed
  borrowed funds understate the DTI and misstate the source of funds — precisely what the rule exists
  to catch.
- Priya signed off the bar on that understanding (LP-390-7).

Any change here spends real safety. That is the whole difficulty.

## 4. Why it is nevertheless a problem

**Ratification fatigue destroys the control it implements.** Ten items per file where zero are plausible
teaches a processor that AS-12 is noise. Once they click through it reflexively, the ratification is a
rubber stamp — and the safety the design paid for is gone anyway, except now it is *also* invisible,
because the audit trail says a human reviewed it.

A control a human stops reading is worse than no control, because it looks like assurance.

## 5. The options

**A — Status quo.** Every verdict ratified. Maximum safety on paper. ~10 rows/file of near-certain noise;
fatigue risk as above.

**B — A confident "no" auto-satisfies.** Only `yes`, `unknown`, or below-confidence-floor answers route
to a human. Would take these 10 to ~0. **Risk:** a wrong confident "no" silently clears a real borrowed
deposit — the exact failure the design prevents. Should not be done on an unmeasured tag; the codebase's
own gate philosophy is "never trust what you haven't measured".

**C — Scope it out deterministically, before the AI is asked.** An applicability predicate excluding
deposits whose `apparent_category` is structurally not a borrowed-funds candidate. Scope-false →
`not_applicable`, which never persists. **This is exactly what LP-509-A1 did** for money-out
transactions — the same shape, the same rule.

  ⚠️ A point that matters for judging C's risk: AS-12 *reasons over* `apparent_category`. If the AI
  mislabels a disguised wire as "payroll", AS-12 would not have caught it anyway — it reads the same
  tag. So excluding payroll costs no real coverage that the rule currently provides. It also removes an
  AI call per deposit, so it is cheaper as well as quieter.

**D — Aggregate the presentation.** Keep all evaluations; collapse them into one UI row ("10 deposits
reviewed, none suspicious — expand"). The frontend already has `groupBySameReason` for exactly this.
Changes nothing in the engine; changes what the processor faces. Complements A, B or C.

## 6. Recommendation

**C, plus D. Not B — at least not yet.**

C is the option consistent with how this codebase already solves this problem, and it is the one that
costs the least safety: it removes deposits the rule was never able to judge independently anyway
(because it reads the same tag it would need to distrust). D then makes whatever remains legible.

B is the one that genuinely trades safety for quiet, and it should be earned by measurement — the
accuracy of `as.borrowed_funds` on "no" answers specifically — not assumed.

Sequence: decide C's exemption list (§7), implement C, apply D, and revisit B only if the volume is
still unacceptable and a measurement exists.

## 7. What needs deciding — the actual questions

**Domain (needs the mortgage expert, not an engineer):**

1. **Is a payroll deposit from the borrower's verified employer ever a borrowed-funds concern?**
   My understanding is no, but this is the exemption that does the work and it should be ruled on, not
   assumed.

2. **Is an own-account transfer ever a borrowed-funds concern?** ⚠️ **This one is genuinely harder and I
   do not think it is safe to assume no.** The transfer itself is traceable, but the money in the
   *other* account may itself have been borrowed. `txn.has_identified_source` establishes the immediate
   source, not the ultimate one. Excluding `transfer_own` may lose real coverage in a way excluding
   `payroll` does not. **6 of the 10 are this category**, so the answer decides most of the benefit.

3. Does a large round-dollar own-account transfer shortly before closing change the answer to (2)?

**Product / risk:**

4. Should a confident "no" from a judgment rule ever auto-clear, or is ratification absolute? This
   generalises well beyond AS-12 — it is the shape of every `ships: ratify` rule.

5. What is an acceptable number of ratifications per file? "As few as are real" is not an answer a rule
   can be written against.

## 8. If C is chosen, the implementation is small

An `applicability` predicate on AS-12's judgment block, the same mechanism LP-509-A1 used:

```yaml
applicability: {tag: txn.apparent_category, op: ne, value: payroll}
```

The predicate DSL currently supports only `eq` / `ne` against a single value, so a multi-category
exemption (payroll AND transfer_own) needs either a derived boolean tag or a small DSL extension —
worth knowing before scoping, but not a blocker.

The §8 honesty contract still applies: an ABSENT or `unknown` category must abstain (`couldnt_check`),
never be silently exempted. Only a confidently-known safe category is scoped out.
