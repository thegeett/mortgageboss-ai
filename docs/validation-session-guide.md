# Validation Session Guide — capturing Priya's verdicts (LP-89)

How to use the **rule/calculator validation aid** (`/admin/validation`) during the session with
Priya. The aid lays out every grounded-starter item and records her verdict per item. **It captures
her judgment; it does not validate.** Nothing is "validated" until she says so and it's recorded.

## Before the session

- Be an **admin** (the aid is admin-gated, company-scoped).
- Open `/admin/validation`. The header counts show the honest progress: everything starts as
  **grounded starter** (validated = 0). The goal of the session is to move items off "grounded
  starter" by recording her verdicts.

## The inventory

Every item carries: the `rule_id` / methodology id, the program (Conventional / FHA / agnostic), the
category, the human description, the current value + operator + unit, the source citation (the Fannie
B-section / HUD section / Form 1084), and a **to-verify** marker where the citation/value was already
flagged uncertain at build time. The calculator methodologies (PMI rate, FHA annual MIP, the 60%
retirement haircut, the conforming loan limit, the reserve months, the self-employed add-backs) are in
the inventory too.

## How to walk it (systematically)

Use the **filters** (program / category / status) to go category by category — it's far less
overwhelming than 123 items at once. A good order:

1. **DTI + credit** (the most-cited, highest-stakes — the credit-score layering, the DTI ceilings).
2. **Income + assets** (the doc-age, self-employment, reserves, gift rules).
3. **Property + documentation** (Conventional, then the FHA MPR / subject-to-repair items).
4. **FHA-specific** (the tiered MDCS, MIP, the 60% haircut — filter program = fha).
5. **Cross-source** (the identity / undisclosed-debt / red-flag checks).
6. **Calculator methodologies** (filter category = calculator).

For each item, ask Priya: **"Is this right for your lenders / your files?"** Then record:

- **Validate** — she confirms it's correct as-is.
- **Correct…** — she gives a different value/threshold. Enter the new value + a note (her words).
- **Flag remove…** — not applicable / wrong. Enter why.
- **Add a rule Priya says is missing** — a check she names that isn't here. Capture its title + what
  it should check.

The "to verify" items (esp. the FHA derogatory periods, the MIP rate table, the 60% haircut, the loan
limit) are the highest-priority — they were flagged uncertain at build time.

## After the session

- The header counts show what she validated / corrected / flagged. The remaining "grounded starter"
  count is **what still needs validation** — queryable, honest.
- The developer acts on the recorded verdicts: applying corrected thresholds (because **Priya said
  so**, recorded with attribution), removing flagged rules, and adding the proposed ones. The aid is
  the record of her pass; the code changes are the follow-up.

## The honesty rule

The aid never auto-validates. A corrected value applies because Priya said so — the row records her
verdict, the corrected value, the note, the actor, and the timestamp. Until a verdict exists, the item
is grounded-starter. Do not present the rules as "validated" on the strength of the grounding alone.
