# LP-UI-018 — The reconciliation ledger

- **Ticket:** LP-UI-018 — the centrepiece
- **Epic:** Ledger redesign → Epic C (Core screens)
- **Status:** Completed
- **Date:** 2026-08-30
- **Depends on:** LP-UI-017 (the read model)
- **ADR:** none new. The comparison rules are ADR-391; this ticket only draws them.

## Summary

Stated against found, side by side, at the top of the file Overview. The product's
whole job is that comparison and it had never appeared on screen *as* a
comparison — the stated figures were on one tab, the extracted ones on another,
and the processor did the join in their head.

Five rows, rail-coded by agreement, each found value carrying the document, page
and the snippet the extraction actually read.

Real output, `LF-XKQ3`:

| | field | stated | found | source |
|---|---|---|---|---|
| Differs | Base monthly income | $16,400.00 | $6,866.67 | `W-2_Thermofisher-PPD_2025.pdf` p.1 |
| Differs | Employer | Swad Mania LLC | Thermofisher Life Science – PPD Development LP | `VOE_…2026-06-05.pdf` p.1 |
| **Agrees** | Checking balance | $35,000.00 | $35,000.00 | `Bank-Statement_Bank-of-America_2026-04.pdf` p.1 |
| Not found | Appraised value | $1,380,000.00 | — | *no appraisal extracted* |
| Not stated | Homeowner's insurance | — | $1,150,000.00 | `Homeowners-Insurance_Liberty-Mutual_2026-07-31.pdf` p.1 |

## What changed

- `components/file/overview/reconciliation-ledger.tsx` (new) — the ledger.
- `lib/types/reconciliation.ts`, `lib/api/reconciliation.ts` (new) — one read.
- `lib/status.ts` — `RECONCILIATION_AGREEMENT`, the sixth domain on the one tone
  vocabulary. Mirrored into `docs/design/ledger/assets/lib/status.ts`, which the
  drift guard requires: an asset left behind is copied forward later and silently
  deletes whatever it is missing.
- `app/(protected)/loan-files/[id]/page.tsx` — ledger first; both
  "coming in Phase N" placeholder cards removed.
- `components/file/overview/overview-placeholder.tsx` — **deleted**, now unused.
  (`TabPlaceholder`, a different component, still serves the Lender package tab.)
- `app/services/reconciliation.py` + its tests — the `unit` field, below.

## The backend change this ticket made, and why it belongs here

017 emitted every value as a *display* string: `"85,087.00"`. Rendering it
surfaced two problems that only exist at the point of drawing.

**Nothing told the UI which rows were money.** `"85087.00"` and an employer's
name are both `str | None`. The browser would have had to infer the unit from the
shape of the string — a second mechanism deciding something the server already
knew when it built the row.

**The one value that reached the browser unformatted proved the point.** The
insurance row passed the extractor's raw `915318` straight through while the
money rows were comma-formatted and the employer row was plain text: three
formats in one response.

So `ReconciliationRow` now carries `unit: money | text`, and money values are sent
**raw** for `formatMoneyPrecise` — the app's single money formatter — to render.
`_money_text` survives for prose, because the sentence explaining why two figures
are not comparable does want its commas.

This is a contract change to a ticket that was reviewed the same night, which is
a real cost. It is here rather than deferred because the gap is only visible from
the consumer, and the alternative was to teach the UI to recognise money by
looking at it.

**It failed silently, exactly as predicted.** `formatMoneyPrecise` returns its
input verbatim when `Number()` can't parse it, so with the old API the ledger
rendered `8,812.50` with no currency symbol and threw nothing. It was a stale
uvicorn — started without `--reload`, so it had never picked the change up — and
the screenshot is the only reason it was caught. A test asserting the currency
symbol is now in place on both sides.

## A20 — the engine is the authority, and I missed it

`AMENDMENTS.md` carried **A20**, written the same night specifically so it would
be honoured here: *where a finding exists for a row, the finding is the authority
and the ledger row defers to it — it shows the finding's verdict and its own
comparison as the evidence beneath.* It was sitting unstaged in the working tree.
I built the ledger painting its own verdict, with no reference to findings at all,
and found the amendment only when staging the commit.

The amendment's reason is not stylistic. LP-80 makes the income variance
**overlay-overrideable per lender by `rule_id`**, and the read model does not
resolve overlays — so for a file under a lender that widened or narrowed the
variance, the ledger compares against the default while the engine compares
against the lender's number. They disagree about the same two numbers, and a
screen preferring its own answer is LP-UI-013 again, inside the centrepiece.

### What the join could honestly cover

Only where a rule asks the **same question of the same two quantities**:

| row | rule | |
|---|---|---|
| `base_monthly_income` | `xsrc.income.stated_vs_documented` | same comparison — this row already imports its threshold |
| `employer` | `xsrc.income.employer_name_consistency` | same question |

Three rows deliberately get nothing. `xsrc.asset.stated_missing_document` asks
whether a stated asset has a supporting document *at all* — this ledger's
`missing` case, not its value comparison; mapping it would make a row reporting
two different balances defer to a rule about presence.
`xsrc.income.employer_count_matches_items` counts employers, where this row
compares names. And `appraised_value` and `homeowner's insurance` have no rule
asking their question at all — which is exactly where the read model earns its
keep, since the `not_stated` direction has no finding anywhere in the product.

### Two filters that carry as much weight as the join

**Origin.** The same `Finding` table holds the legacy AI cross-source sweep. A row
deferring to an AI finding would put LP-375's one structural separation *inside*
the redesign's centrepiece, so the query takes `DETERMINISTIC_RULE` only. All 64
`xsrc.*` findings in this database are deterministic; the filter is there for the
day one isn't.

**Resolution.** A finding that was APPLIED or OVERRIDDEN has been answered, and
the row goes back to reporting its own comparison rather than re-asking.

### Verified against real data

`xsrc.income.employer_name_consistency` has 45 findings in this database, and
`LF-96SV`'s Employer row now carries two of them — the rule's own words, linked to
the Verification tab, with the stated-vs-found comparison intact beneath.

`xsrc.income.stated_vs_documented` has **zero** findings anywhere in this database,
which is worth saying plainly: the rule whose threshold LP-UI-017 imports has never
fired here, so the income row's deference is built and unit-tested but has never
been exercised against real data.

## Three places the mockup was not followed

**No "Re-verify" button.** The mockup puts one in the section header. Verification
is the AI/rule pass (`useRunVerification`); this ledger is a deterministic join
computed fresh on every read, with nothing to re-run. Wiring that button here
would fire one mechanism from the header of another — and the standing rule is
that the governed findings and the legacy AI sweep are never merged or summed
(LP-375). The section has nothing to re-run and so has no button.

**Differing rows are all one tone.** The mockup tints "Checking balance" red and
"Bonus income" amber — two severities of disagreement. That severity does not
exist in the read model, and the thing that owns it is `finding_blocking.py`.
LP-UI-013 shipped a dashboard that re-derived exactly this judgement from enums
and disagreed with the file screen in both directions. Inventing it again, on the
same screen as the findings that own it, is the same defect with better colours.
Every disagreement is `attention`; the **word** says which kind.

**The page is shown but is not a link target.** The acceptance criterion asks the
source link to "open the document at the right page". `?doc=` (LP-114) opens the
drawer — metadata and extracted fields. There is no page canvas anywhere in the
product: no `pdfjs`, no `react-pdf`, no `#page=` anchor, and document bytes are
reachable only through the auth'd `/download`. **LP-UI-030 builds that canvas**,
so this criterion depends on Epic E, not on 017. Adding `&page=` now would put a
parameter in the URL bar that nothing reads.

What ships instead is the evidence itself: the page number beside the filename and
the snippet under it — the text the extraction actually read, which is the thing a
processor would open the page to check. LP-UI-029 measured that coverage at
1,443/1,456 (99.1%) of valued fields. **When LP-UI-030 lands, the link target
changes here.**

## Degrading on a sparse file

`LF-HWKM` has no extractions at all. Every row would be a sourceless "Not found" —
true, and useless: it reports one missing-documents problem five times as if it
were five discrepancies with the application. The ledger detects that nothing has
a source and says so in one sentence instead. The Needs list directly below
already names the documents to collect, so the two read as one thought.

## Tests

18 component tests and 7 DB-backed service tests. Eleven mutations verified to
fail: ignoring the unit, dropping the empty-state guard, counting every row as
agreeing, a source link that forgets its document id, the ledger's verdict
overriding the engine's, a dropped "+N more", a verdict linking to the wrong
screen, and — on the join — dropping the origin filter, dropping the resolved
filter, hard-coding the count, and attaching one verdict to every row.

The mutation harness passed `$C.test.tsx` where `$C` already ended in `.tsx`, so
the first run of all four "mutations" tested a file that does not exist and
reported nothing. A mutation run that finds no tests looks exactly like a mutation
run that finds no failures.

Frontend: 635 pass, tsc and biome clean. Backend below.

## Open, and owed by someone else

- **The partial-year W-2 rule** the 017 review added declines to compute rather
  than annualising, and how to average a part-year W-2 with a YTD stub is
  underwriting judgement. That is a question for the domain expert — it should not
  be inferred by either of us.
- **A double full stop in the engine's message.** `XSRC_INCOME_EMPLOYER_NAME`'s
  template ends `...: {employer}.` and the employer value already ends in a
  period, so the ledger renders "AMBIOPHARM , INC..". The message is quoted
  verbatim on purpose — two phrasings of one ruling is how a processor ends up
  unsure whether they are looking at one problem or two — so the fix belongs in
  the rule template, not here.
- **"Warning", singular.** `FINDING_SEVERITY` is the seventh status domain and
  the one LP-UI-005 missed; `finding.status` had no meta map at all, just
  `const red = finding.status === "red"` written out where needed. The shipped
  labels are "Blocking" and "Warnings" (finding-filters, verification-stats),
  where they count a set; a single row's verdict needs the singular. That is a
  pluralisation, not a re-opening of LP-583/LP-581's wording.
- `LF-96SV` reads `Ambio, Inc.` against `AMBIOPHARM , INC.` and calls it a
  disagreement, which is correct — they are different companies. Noting it only
  because an earlier build compared against `Ambio, DBA Ambio, Inc` and got it
  wrong; the newest-document fix changed which evidence the row cites.

## Review pass — the ledger deferred to a rule the engine had retired

Reviewed on request from the session running the epic. Two defects, both in the
A20 deference itself.

### The employer row deferred to a rule that cannot fire

`_ROW_RULE["employer"] → xsrc.income.employer_name_consistency`. That rule asks
the employer row's question exactly — *"documented employer not among the stated
employers"* — which is why it was mapped, and the mapping is still wrong:
**LP-606 retired it.** It is not in `CROSS_SOURCE_RULES` and cannot fire again.

Every one of the 45 findings behind it is historical. A row deferring to it
renders a verdict from a rule this codebase deliberately removed — forever on the
files that already have one, never on a file processed since.

And it was retired for **A20's own reason**. Its `_norm` folds case and
whitespace and nothing else, so on a real file it emitted
`yellow "Documented employer not among the stated employers: SUMITOMO PHARMA
AMERICAS INC."` while IN-5 said `satisfied` — one trailing letter apart. A20
exists so the ledger and the engine cannot say different things about one
question; this mapping put the ledger on the losing side of a disagreement the
engine had already settled, using the answer that lost.

**IN-5 is not the substitute.** It compares employer names ACROSS DOCUMENT
SOURCES (paystub / W-2 / VOE); this row compares the APPLICATION against a
document. Different two quantities, so mapping it would repeat the same mistake
facing the other way. The employer row keeps its own verdict — which is also the
better one, since this module's matcher handles company suffixes (ADR-391) and
the retired rule's could not tell a spelling variant from a different company.

A test now asserts every rule in `_ROW_RULE` is one the engine still runs, so a
retirement elsewhere fails here rather than going quiet.

The hand-off's two A20 tests used the employer row as their example, so they
moved to the income row — the mapping that is actually live. Property unchanged,
example replaced, same call as LP-UI-014's toggle test. That also answers point 1
of the hand-off: the income deference now has coverage that exercises it, which
is not the same as production data but is more than it had.

### The verdict owned the rail and not the value beside it

The hand-off found this in one channel — an empty cell rendering "Warning"
instead of "Not found" — and said the split looked easy to get wrong elsewhere.
It was wrong in the cell immediately next to it: the found value's colour came
from `row.agreement`, the ledger's own comparison, not from the verdict.

So a row the engine has PASSED could render a green rail, a green glyph, and an
amber number: the overruled answer put back in a channel a reader takes for the
verdict, and a row saying both things at once. Now keyed on the verdict where one
exists, and on the ledger's own comparison where none does.

### On the hand-off's own points

- **The mutation harness that tested a nonexistent file.** The observation
  generalises further than the typo: *a run finding no tests is indistinguishable
  from a run finding no failures*, and both print reassuringly. The habit that
  makes it safe is reading the counts, not the exit code — every mutation in this
  review is recorded as `N failed, M passed`, and a mutation that reports `0
  failed` against a file with tests is the signal to stop and look. I checked my
  own runs here for the same shape.
- **Changing LP-UI-017's contract the same night it was reviewed.** The right
  call, and the reasoning holds: `unit` on the row and raw money values move the
  formatting decision to the one place that owns money formatting. Discovering it
  at the consumer is not a process failure — it is where the requirement became
  visible. Worth keeping the failure mode on record though: the ledger printed
  `8,812.50` with no currency symbol and threw nothing, against a stale uvicorn
  with no `--reload`. A contract change that degrades silently is one only a
  screenshot catches, which is an argument for the test that now pins it.
- **Not building the three ACs.** Each argued rather than dropped, and the
  page-canvas one is right on the facts — an AC that depends on Epic E is not
  this ticket's to satisfy.
- **The double stop in "AMBIOPHARM , INC.."** — no longer reachable from the
  ledger, since the employer row no longer renders that rule's message. Left
  alone deliberately: it is a retired rule's template, and editing the copy of a
  rule that can never fire again is churn.

### Verification

Backend `ruff` and `mypy` clean over 448 files, **6,007 pass** with the two known
`.env` failures. Frontend `tsc` and `biome` clean over 231 files, **639 pass**,
build compiles. Both fixes mutation-checked:

| mutation | result |
| --- | --- |
| map the employer row back to the retired rule | 2 tests fail |
| colour the value from the ledger's own agreement | 1 test fails |
