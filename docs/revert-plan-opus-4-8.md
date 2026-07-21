# Extraction AI tier — model choice, history & how to switch

**Current default:** the extraction/reasoning tier runs **Sonnet 4.5**
(`claude-sonnet-4-5`), set as the code default in `app/core/config.py`
(`anthropic_model_extraction`). The classification/summarization tier runs
**Haiku** (`claude-haiku-4-5`). Both are env-overridable — see below.

This file used to be a standby *revert plan* for undoing an Opus switch. That
revert has now been done (the default is Sonnet again), so this is now just the
record of what happened and how to change tiers deliberately.

## Why Sonnet is the default

The default is the **safe/cheap** value on purpose: a clean deploy with no env
override degrades to Sonnet (correct + ~5× cheaper than Opus), never silently to
a high-cost Opus fallback. Opus carries both a higher price ($15/$75 vs $3/$15
per M in/out) and an unassessed retention posture, so it should be an explicit,
deliberate opt-in — not the accidental default when someone forgets an env var.

## How to switch tiers (no code change needed)

The model is env-overridable, so switching is a config change + restart, no
deploy:

```bash
# in the backend environment / .env
ANTHROPIC_MODEL_EXTRACTION=claude-opus-4-8   # opt into Opus 4.8 (higher capability, ~5x cost)
# or drop the line entirely to use the Sonnet default.
```

Restart the backend **and** the Celery workers so the setting is re-read
(extraction runs on the worker). The `claude-opus-4-8` pricing row already exists
in `app/ai/cost.py`, so cost estimates stay accurate under either tier.

## History (for the record)

| Commit | What it did |
| --- | --- |
| `d34e8a4` | Switched `anthropic_model_extraction` default `claude-sonnet-4-5` → `claude-opus-4-8`; added the `claude-opus-4-8` pricing row in `app/ai/cost.py` + a cost test; changed "Sonnet" → "Opus" prose across the AI files. Done **without an explicit request**. |
| `10ea7ea` | ADR-226 in `decisions.md` recording that Opus switch. |
| _(this change)_ | Flipped the default back to `claude-sonnet-4-5` (cost + retention safety on clean deploys) and corrected the stale "Opus" prose on the model-config surface. The `claude-opus-4-8` pricing row + test are **kept** (Opus is still a supported opt-in). |

> Note: ADR-226 (`decisions.md`) still records the original Opus decision and now
> reads as superseded by this flip. It was left untouched by this change; mark it
> `Superseded` in a follow-up if you want the decision trail explicit.
