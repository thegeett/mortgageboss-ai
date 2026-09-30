# The condition reading's real-model trial (LP-939)

`condition-reading-trial.py` runs Stage 3's condition reading with the **configured model** on real
lender condition sheets, and writes a summary that holds **numbers and codes only**. It is local only:
the owner runs it, and nothing it reads or writes is committed.

## Before you run it

- **Put the sheets OUTSIDE the repository**, for example `~/trial/sheets/`, as PDFs. The script refuses
  a sheets folder or an output path inside the repo.
- The model is the one the app is configured for: the same setting `read_round` passes
  (`ANTHROPIC_MODEL_EXTRACTION`, which the provider maps to its Bedrock counterpart under Bedrock), from
  `backend/.env`. Each sheet is **one model call**, the same call `read_round` makes. The summary's
  `model_setting` is that setting, and each sheet's `model` is the id that actually answered.
- Nothing is written to any database. The conditions are built in memory from each sheet and typed from
  the repo's lender code maps (`app/conditions/lender_codes/uwm.yaml`, `champions.yaml`). A sheet from
  any other lender is read by the generic reader and its conditions have no library type.

## Running it

```bash
cd backend
# 1. Check the pipeline first: no model call, costs nothing, every condition "falls back".
uv run python scripts/condition-reading-trial.py ~/trial/sheets --out ~/trial/summary-dry.json --no-model

# 2. The trial: asks before calling the model (or add --yes).
uv run python scripts/condition-reading-trial.py ~/trial/sheets --out ~/trial/summary.json
```

The summary is rewritten after each sheet, so stopping early loses at most the sheet in flight.

## What the summary holds

Per sheet (a "round"; sheets are named `sheet 1`, `sheet 2` in file-name order, never by file name):

| field | meaning |
|---|---|
| `reader` | which sheet reader read it (`uwm`, `champions`, `generic`) |
| `conditions` | how many conditions it has |
| `input_tokens`, `output_tokens` | the model call's tokens |
| `cost_estimate` | the app's own estimate for that call, in dollars |
| `seconds` | the model call's wall time |
| `model` | the model id that answered |
| `fell_back` | the whole call failed or was unreadable (every condition fell back) |
| `error` | the failure's class name only, when there was one |

Per condition (`rows`):

| field | meaning |
|---|---|
| `code` | the lender's condition code |
| `type` | the library type id, from the code map (none when unmapped) |
| `items` | how many items the reading made |
| `performers` | who acts on those items |
| `confidence` | the model's confidence, 0 to 1 (none when it gave none) |
| `fallback` | the model gave nothing for this condition, so the library or the owner hint read it |
| `source`, `status` | the reading's source (`ai`, `library`) and whether it needs her confirmation |

`totals` adds up the sheets: conditions, tokens, cost, seconds, and conditions that fell back.

**Never in the summary:** condition text, borrower or other names, amounts, account digits, or file
names. A sheet that cannot be read shows only its error's class name.

## Keep out of the repo

Never commit the sheets or any summary. They stay in the folder you chose, outside the repository.
