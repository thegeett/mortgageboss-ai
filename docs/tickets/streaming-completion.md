# Streaming completions — fix the truncation-retry `ValueError` (core AI path)

The extraction bench, run over 889 real documents, surfaced a **core/production** bug: dense documents
failed extraction with a `ValueError`, not a coverage gap. This changes the shared model-call path to
**streaming** to fix it.

## The bug

`app/ai/client.py::complete()` made a **non-streaming** request:

```python
resp = await asyncio.wait_for(client.messages.create(**kwargs), timeout=timeout_s)
```

The anthropic SDK (which `AsyncAnthropicBedrock` is built on) refuses any **non-streaming** request whose
worst-case duration could exceed 10 minutes — raising, **client-side, before sending**:

```
ValueError: Streaming is required for operations that may take longer than 10 minutes.
  anthropic/_base_client.py  _calculate_nonstreaming_timeout
```

The threshold is `max_tokens > 21,333` (`3600 * max_tokens / 128000 > 600s`). The LP-102 truncation guard
retries a truncated extraction at **`RETRY_MAX_TOKENS = 32768`** (> 21,333), so **every document that
truncates on the first attempt and hits the retry** got an instant `ValueError` instead of a second
attempt — and was recorded as `"AI call failed"`.

**Not bench-only.** The bench uses the identical `complete()` path as normal document processing, so any
large-output document in production failed its truncation retry the same way. Introduced when
`RETRY_MAX_TOKENS` went `16384 → 32768` (16384 was under the ceiling). Confirmed the only value in the
codebase above 21,333 is that retry ceiling — first-attempt tiers top out at 16384.

## The fix — stream every completion

`complete()` now assembles the response from a **streamed** connection:

```python
async def _stream_final_message(client, kwargs):
    async with client.messages.stream(**kwargs) as stream:
        return await stream.get_final_message()
```

Streaming has **no 10-minute/`max_tokens` ceiling** (a streamed connection never idles, so gateways don't
drop it). `get_final_message()` returns the **same** final `Message` (`.content` / `.usage` /
`.stop_reason`), so every caller sees an identical result — only the transport changed.

Two supporting details:

- **Per-attempt timeout is now `max_tokens`-scaled** (`_stream_timeout`): floored at
  `ai_request_timeout_seconds` (60 s) and raised toward the SDK's own worst-case estimate for large
  `max_tokens`, so a dense retry isn't killed by the 60 s bound (which would just trade the `ValueError`
  for a timeout) while small calls keep a tight bound.
- `RETRY_MAX_TOKENS` stays **32768** — streaming makes it viable (it's half the model's 64K output
  ceiling, the LP-102/LP-445 sizing rationale).

Everything else — the transient-retry loop, rate limiter, metadata-only logging, model resolution — is
unchanged.

## Verified live (Bedrock, real documents)

The three docs that previously failed with the streaming `ValueError` now **succeed**:

| document | before | after |
|---|---|---|
| Wells Fargo bank statement | `ValueError` | ✅ succeeded — 7,953 output tokens |
| Lease agreement 1401 | `ValueError` | ✅ succeeded — truncated → retried at 32768 (streamed) |
| 4506-C form (9 MB, densest) | `ValueError` | ✅ succeeded — retry at 32768 **streamed for 61 s**, 9,244 tokens |

Zero `"Streaming is required"` errors across the run. That 61-second streamed 4506-C retry is exactly the
request that was an *instant* client-side `ValueError` before.

- 67 client + provider tests pass with the streaming test seam (the mock now drives
  `messages.stream(...).get_final_message()` instead of `messages.create()`).
- ruff + `mypy app/` clean; full suite green.

## Out of scope / follow-up

- **AWS Bedrock content-filter block (separate issue).** One lease still fails with
  `ValueError: Bad response code … {"message":"Output blocked by content filtering policy"}` — a Bedrock
  **guardrail** rejecting the output (a 400 `validationException`), surfaced by the Bedrock stream
  decoder. This is an **AWS account/guardrail configuration** matter, not a code bug; the fix here does
  not (and can't) address it. The bench correctly tags it `ai_failed` (infrastructure, not coverage).
- **Full B, not B-lite:** streaming is now the default for *all* completions (classification, every
  extractor, rule-engine reasoning), not just the retry — the simpler, uniform path.

## Files

- `backend/app/ai/client.py` — `_stream_final_message`, `_stream_timeout`, and `complete()` streaming.
- `backend/tests/ai/test_client.py`, `test_provider_selection_b1.py` — test seams driven through
  `messages.stream(...)`.
