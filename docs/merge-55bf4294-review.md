# Review — merge 55bf4294 (bedrock_integration_with_rules_staging → mbai-ui-improvemet-merge)

A merge is reviewed for a different question than a feature commit: not "is this code good"
but "did the merge lose something, and does the result still hold both branches' guarantees".

## Structure, confirmed rather than taken on trust

`55bf4294` has parents `0ff49dc6` (ours) and `951d084d` (theirs); the merge base is `0518c14`.
Both hand repairs are in the amended tree: `rule-finding-row.tsx` carries no `text-gray-400`
class (the one remaining mention is the comment explaining the replacement), and the
`CalcLine` fixture carries `override_by`/`override_note`. One alembic head, `a7c93e12f4b8`.

## Where a merge can lose something, measured

Their branch touched 43 files, ours 435, and **the two overlap in exactly 12** — all frontend.
Every other file in the tree is one side's version verbatim, so no backend file can have been
damaged by the merge itself. That answers the "same question for their backend changes" ask
without inspecting them: there was nothing to resolve.

For each of the 12, every line their branch ADDED relative to the base was checked for
presence in the merge result:

```
  calculator-card.test.tsx      65 added   0 missing
  calculator-card.tsx           50 added   0 missing
  document-dropzone.tsx         30 added   0 missing
  dti-calculator.test.tsx       83 added   0 missing
  dti-calculator.tsx            61 added   0 missing
  ltv-calculator.test.tsx       44 added   0 missing
  ltv-calculator.tsx            53 added   0 missing
  findings-list.test.tsx         1 added   0 missing
  rule-finding-row.tsx          17 added   2 missing  (the two `text-gray-400` classes, replaced)
  verification-panel.test.tsx   41 added   0 missing
  verification-panel.tsx        20 added   2 missing  (two comment lines, reworded)
  verification.ts                9 added   0 missing
```

Run the other way, our own additions are equally intact: the three that did not match verbatim
are `onCancel`/`onClear` on `calculator-card` (now multi-line bodies that also discard the
draft) and the panel's Run button (now `disabled={running || blockedByDocuments}`) — our
markup extended by their behaviour, which is the described resolution.

No test case was dropped either. Each resolved test file holds exactly the union count:

```
  calculator-card.test.tsx     base 4   ours 7   theirs 8   merged 11
  dti-calculator.test.tsx      base 15  ours 19  theirs 20  merged 24
  ltv-calculator.test.tsx      base 10  ours 10  theirs 14  merged 14
  findings-list.test.tsx       base 4   ours 6   theirs 4   merged 6
  verification-panel.test.tsx  base 34  ours 37  theirs 38  merged 41
```

## Line-level presence is not a guarantee, so each guarantee was mutated

Every behaviour their branch contributed was removed in turn to see whether a surviving test
notices:

| their guarantee | mutation | result |
|---|---|---|
| uploads held while verification runs | `blocked = upload.isPending` | 1 test fails |
| Run blocked while documents process | `disabled={running}` | 1 test fails |
| a held DTI draft reads as unsaved | `unsaved = false` | 2 tests fail |
| a held LTV draft reads as unsaved | `unsaved = false` | 2 tests fail |
| **the `beforeunload` reload guard** | **listener removed** | **nothing fails** |

### The reload guard was held by nothing, on either branch

`beforeunload` appears in three components — `calculator-card`, `dti-calculator`,
`ltv-calculator` — and in **no test in the repository**, on their branch or in the merge. So
it is inherited rather than lost, but it is precisely the shape this review was asked to look
for: a partial guarantee that the next hand-merge drops with nothing going red. Each of the
three now has a test that dispatches a cancelable `beforeunload` with an edit held and asserts
it was defended, with a control asserting a quiet page is not interrupted. Five mutations —
the listener removed in each component, and the `hasUnsavedDrafts` guard forced true in two —
all caught.

## The auto-merged surface

Only five of their non-test files import anything from `components/ui/`, and all five are the
hand-resolved ones. So the semantic-conflict surface between their components and the
primitives our branch rewrote (badge, button, card, input, skeleton, tooltip, table…) is
entirely inside the files already reviewed; the rest of their 43 is backend, types and tests.

The design-token guard that caught `rule-finding-row` walks the tree from the repository root
rather than a listed set of directories, so it covered their whole surface rather than the
part someone remembered — that is why it caught a file nobody was looking at. It skips
`*.test.tsx`; a sweep of merged test files for palette classes or `bg-white` found none.

## The two suite results that are not the merge

**The model-selection failures are confirmed, and the test is the defect.** `.env:24` pins
`ANTHROPIC_MODEL_ANALYSIS=claude-sonnet-4-5` where `.env.example:41` uses `claude-haiku-4-5`;
2 fail locally and 4 pass with the example's value. But
`test_four_model_tiers_exist_and_default_correctly` asserts against the live `settings`
singleton, which is populated from whatever `.env` the developer has — so a test whose name
says **default** was reading the environment, and CI passes only because CI has no `.env`.
This has now been diagnosed as an environment quirk three separate times in one session. Both
affected tests read the DECLARED default from `model_fields` instead. They pass on this
machine with its own `.env` unchanged, and still fail if the shipped default is wrong.

**The overlays flake is not the shared database, and the recorded cause is wrong.**
`test_a_low_dti_file_clears_for_both` is a synchronous, pure in-memory test: it builds a
`FileFacts` dict, resolves a registry and evaluates. It opens no session and takes no
database fixture, so cross-session contention cannot reach it. What it does touch is shared
module state — `default_registry()` rebuilds a registry on each call, but from the same
`SAMPLE_RULES` / `CONVENTIONAL_RULES` / `FHA_RULES` / `STARTER_OVERLAYS` objects — and its
helpers use `next(...)`, which raises rather than asserts when a rule is missing, matching the
reported *error* rather than a failure. That is a mechanism, not a diagnosis: it was not
reproduced in three fixed-order runs of `tests/verification/`, four targeted orderings, an
isolated run, or two full-suite runs (6,766 passed). **Cause unknown, and specifically not the
one recorded** — worth leaving open rather than closed against the wrong explanation.

A note on method, because it nearly went the other way: a first attempt to test order
dependence ran `pytest --randomly-seed=N` four times and reported four clean runs. The flag is
unrecognised here — `pytest-randomly` is not installed — so none of those runs executed a
single test, and the pipeline's exit code hid it. Randomised ordering remains untested.

## Verification

Backend: ruff and mypy clean over 465 files; **6,766 passed** with the developer's own `.env`
and no override, where 2 failed before. Frontend: **1,354 tests over 112 files**, biome, tsc
and `next build` clean.
