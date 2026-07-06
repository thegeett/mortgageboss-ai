# Revert plan — extraction AI tier: Opus 4.8 → Sonnet 4.5

**Status:** NOT executed — this is a standby plan. Execute only when explicitly asked.

**Why this exists:** the extraction/reasoning AI tier was switched from Sonnet 4.5 to Opus 4.8
without an explicit request. It is being kept for now; this document records exactly how to roll it
back later on request.

## What was changed (the target of the revert)

Two commits on `phase3`:

| Commit | What it did |
| --- | --- |
| `d34e8a4` | **The functional switch.** `anthropic_model_extraction` default `claude-sonnet-4-5` → `claude-opus-4-8`; added the `claude-opus-4-8` pricing row in `app/ai/cost.py`; a cost test; and doc/comment prose "Sonnet" → "Opus" across ~17 AI files. |
| `10ea7ea` | **ADR-226** in `decisions.md` recording the decision. |

The only behavioral change is the one config default (`app/core/config.py`). Everything else is the
pricing row, one test, and prose. The classification tier (Haiku) was NOT touched.

Nothing here changes AI *judgment* — the AI is perception-only; the deterministic engine
(LTV/DTI/rules) is unaffected either way.

---

## Option A — Fastest rollback, NO code change (recommended for an urgent flip)

The model is env-overridable, so a single env var flips the tier back without touching git:

```bash
# in the backend environment / .env
ANTHROPIC_MODEL_EXTRACTION=claude-sonnet-4-5
```

Restart the backend (and Celery workers) so the setting is re-read. This overrides the committed
default immediately. Use this if you need Sonnet back RIGHT NOW; do the git revert (Option B) later
to make it the source-of-truth default again.

- Pros: instant, no deploy of code, trivially reversible (unset the var).
- Cons: the committed *default* is still Opus; the pricing row + prose still say Opus (harmless).

---

## Option B — Full git revert (make Sonnet the source-of-truth default again)

Revert both commits, newest first. `git revert` creates new commits (no history rewrite — safe on a
shared branch).

```bash
cd /Users/geetthaker/Geet/project/loan-processing/mortgageboss-ai

# 1) Revert the ADR, then the functional switch (order: newest → oldest)
git revert --no-edit 10ea7ea      # removes ADR-226
git revert --no-edit d34e8a4      # restores Sonnet default + prose + drops the Opus pricing row/test
```

If `git revert d34e8a4` reports a conflict (only if the touched lines changed since), resolve by
keeping the **Sonnet** side, then `git add -A && git revert --continue`.

### Verify after reverting

```bash
cd backend
grep anthropic_model_extraction app/core/config.py         # → "claude-sonnet-4-5"
uv run pytest tests/ai/test_cost.py tests/ai/test_generic_analyzer.py \
              tests/services/test_needs_ai.py -q            # green
uv run ruff check app/ && uv run mypy app/core/config.py app/ai/cost.py
```

Expected end state:
- `anthropic_model_extraction` default is `claude-sonnet-4-5` again.
- `app/ai/cost.py` no longer has the `claude-opus-4-8` row; the Opus cost test is gone (reverted).
- The "Sonnet" prose is restored across the AI files.
- ADR-226 is removed from `decisions.md`.

> Note: reverting `d34e8a4` also removes `test_opus_extraction_tier_is_priced` and the Opus pricing
> row together — that is correct and consistent (no orphaned test).

### ADR handling (choose one)

- **Revert it** (Option B above removes ADR-226 entirely) — cleanest if the switch never happened as
  far as the record is concerned.
- **Keep it as history instead:** if you'd rather preserve the decision trail, do NOT revert
  `10ea7ea`; instead change ADR-226's `Status: Accepted` → `Status: Superseded (reverted to Sonnet
  <date>)` and add a one-line reason. This keeps the "why" discoverable.

---

## Option C — Manual, config-only revert (keep the prose/ADR, flip only behavior)

If you want Sonnet as the committed default but don't care to unwind the prose/pricing/ADR:

1. Edit `app/core/config.py`: `anthropic_model_extraction: str = "claude-sonnet-4-5"`.
2. (Optional) leave the `claude-opus-4-8` pricing row in `app/ai/cost.py` — harmless to keep.
3. Commit: `git commit -am "ai: revert extraction tier to Sonnet 4.5 (config default)"`.

Smallest diff; leaves the Opus pricing row + Opus prose in place (slightly inconsistent, but
functionally correct).

---

## Recommendation

- Need it back immediately → **Option A** (env var), then **Option B** at leisure.
- Clean, source-of-truth rollback → **Option B** (revert both), and mark ADR-226 superseded if you
  want to keep the decision trail (see ADR handling).

## To execute later

Tell me e.g. "run the Opus revert, Option B" (or A/C). I will run the steps, verify, and — per the
usual workflow — commit but not push.
