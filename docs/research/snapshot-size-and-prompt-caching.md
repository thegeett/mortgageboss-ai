# Snapshot growth, context limits, and Bedrock prompt caching

- **Date:** 2026-09-01
- **Scope:** what happens when a loan file has many documents; whether Bedrock prompt
  caching applies to the verification path; what to do about both.
- **Status:** research. Nothing changed. Two of the conclusions **revise LP-635**.
- **Basis:** repo code as of this date, the measured fixture
  `backend/tests/verification/eval/fixtures/lf6t3n_tagged_snapshot.json`, the measurements
  already recorded in `docs/tickets/LP-635.md` and `docs/tickets/LP-210.md`, and current
  AWS/Anthropic documentation. **No staging database was available**, so every projection
  below is arithmetic from measured unit costs, not observed production data. See
  "Measure this first".

---

## TL;DR

1. **No, nothing truncates the snapshot.** There is no size guard anywhere on the path.
   The whole thing is `json.dumps`'d and sent. If it exceeds the model's context window,
   Bedrock rejects the request with a 400, the client classifies it as a non-retryable
   error, and the cross-source pass is recorded as a *degradation* — the run still reports
   `COMPLETED`. The failure is quiet, and it is quiet in the direction that matters: a file
   too big to check looks exactly like a file with nothing to find.

2. **The whole snapshot is NOT sent per rule check.** That premise is wrong, and it is
   good news. Rule-time judgment calls send a filtered tag subset with a **median of 415
   characters** — 0.47 % of the snapshot. The full snapshot goes to the model exactly
   **once per run**, in the cross-source pass, and only when the fingerprint changed.

3. **Prompt caching is available and LP-635's "not viable" is now half wrong.** The Sonnet
   4.5 minimum on Bedrock — recorded in LP-635 as unknown — is **1,024 tokens, not the
   4,096 the code documents for Haiku**. And Bedrock shipped a **1-hour TTL** on
   2026-01-26, which was not available when LP-635 was written. Both change the answer.

4. **But caching is not the lever for the current shape.** Today's repeated calls carry
   ~100–600 token payloads; there is almost nothing to save. Caching's real value here is
   as an **enabler** — it makes "give every rule a shared 4K context block" cost ~$0.71 per
   file instead of ~$7.09. The cost levers that actually matter are the **snapshot's
   unbounded growth** and the **591-call fan-out**.

---

## 1. What actually happens when the snapshot gets big

### The path

```
verification_run.py:1168
  → services/snapshot_findings.py:100   refresh_snapshot_findings()
      → ai/snapshot_cross_source.py:500 snapshot_payload(snapshot)
            json.dumps(snapshot.model_dump(mode="json"), sort_keys=True, default=str)
      → ai/snapshot_cross_source.py:372 reason_over_snapshot()
            complete(model=reasoning, system=PROMPT,
                     messages=[{"role":"user","content": snapshot_json}],
                     max_tokens=8192, temperature=0.0)
```

`complete()` (`ai/client.py:554`) forwards `messages` to the SDK **unchanged**. There is no
length check, no chunking, no elision, no summarisation. I grepped the whole `snapshot/`
package for `.limit(`, `[:N]`, `MAX_`, `truncate` — the only hit is `_MAX_REPORTED = 10` in
`persistence.py:101`, which caps error paths in a PII refusal message.

### So: does it send a partial snapshot?

**No.** It sends all of it, or it fails. There is no silent truncation of *input*.

There is truncation of **output** — `_MAX_TOKENS = 8192`, and
`snapshot_cross_source.py:381` correctly logs `snapshot_cross_source_truncated` and notes
that the parser then drops everything. That is handled and visible.

### What the failure looks like

Bedrock returns **HTTP 400 `ValidationException: Input is too long for requested model`**
when the prompt exceeds the context window. Then:

- `_is_transient()` (`client.py:359`) → **False** for a 400 that is not a throttle code.
  Correct: it is deterministic, retrying is pointless.
- `complete()` raises `AIClientError` immediately, no retries.
- `infra_failure_kind()` would label it `INFRA_OVERSIZED` — but **nothing on this path
  calls it**. The cross-source call site catches bare `Exception`:

```python
# services/verification_run.py:1179
except Exception as exc:
    logger.warning("snapshot_findings_failed", error=type(exc).__name__, detail=str(exc))
    degradations.append(Degradation("snapshot_findings", f"not refreshed: {exc}"))
```

The `AIClientError` message is `"AI call failed: BadRequestError"` — the underlying
"Input is too long" text is on `__cause__` and never reaches the log line or the
degradation string. So in staging this appears as:

```
snapshot_findings_failed  error=AIClientError  detail=AI call failed: BadRequestError
```

Indistinguishable from an auth failure, a bad inference-profile id, or a malformed
request. **This is the same class of bug LP-637 already shipped once** (a 400 from an
unreadable scan reported as "your file is too big"), just pointing the other way.

### When does it happen? — the size model

Measured, on the repo's own fixture (5 bank statements, 50 transactions, **zero** typed
fields, **zero** MISMO facts, **zero** generic lists, reasoning strings stubbed to 59
chars):

| section | compact bytes | share |
|---|---:|---:|
| `tags` | 58,897 | **72.1 %** |
| `documents` | 20,094 | 24.6 % |
| `calculations` | 2,403 | 2.9 % |
| `mismo` | 40 | 0.0 % |
| **total** | **81,647** | **≈ 23,300 tokens** |

All 50 subjects in that fixture are transactions, at **~1,178 B each in `tags` alone**,
plus ~400 B in `documents.entries[].transactions`. **Transactions are the snapshot.**

The fixture is a floor, not a typical file. It carries `lists: {}`, `fields: {}` and 59-char
stub `reasoning` on every entry — three multipliers a production snapshot exercises and this
one does not. Read every number below as a lower bound.

Nothing caps them:

- document query has no `LIMIT` (`documents_section.py:1801`)
- `build_transactions` emits every extracted row (`documents_section.py:597`)
- `build_list_rows` emits every row of every declared list, for 67 document types
  (`documents_section.py:1669`, `_LIST_SPECS:1499`) — and bank-statement rows are
  **stored twice**, in `entry.transactions` *and* `entry.lists["transactions"]`, which
  `documents_section.py:774` documents as deliberate belt-and-braces
- `tags.by_subject` gets an entry for every enumerated subject including ones that
  resolved to `unknown` (`tag_materialization/ai.py:378`)
- tag `reasoning` (`snapshot/tag.py:68`) has no length validator
- `untyped_extraction` is bounded only by the analyzer's 8,192 output tokens
  (~30 KB of JSON per untyped document)

**Per-transaction all-in ≈ 1.6 KB** on the fixture's shape, and higher in production
(real reasoning sentences ≈ 120 chars vs the fixture's 59; generic list rows add ~680 B
where a spec exists).

At **1.6 KB/txn** and **3.5 B/token**, Sonnet 4.5's 200K-token window is reached at
roughly **430 transactions ≈ 700 KB**.

430 transactions is **not** an unusual file. Two borrowers × two accounts × two months at
50 lines a statement is 400. LF-ZE9N had 44 documents. **This ceiling is reachable today**,
and it will be hit before anyone notices, because it degrades silently.

The second-order problem: `snapshot_records.snapshot_json` is JSONB, insert-only, one row
per run, never deleted (`models/snapshot_record.py:57`), and
`load_snapshots_for_loan_file` (`persistence.py:194`) materialises **every** run's blob for
a file at once. And `persistence.py:157-183` serialises the whole snapshot **twice** per
persist (`model_dump_json()` for the PII assertion, then `model_dump(mode="json")` to
store), plus a `json.loads` and a full recursive scalar walk in between.

---

## 2. Where the snapshot actually goes — the per-call payload table

This corrects the premise in the question. Traced through `verification_run.py`:

| # | Call site | Fires per run | User payload |
|---|---|---|---|
| 1 | Stage A `ai/tag_production.py:180` | `ceil(txn fingerprints / 15)`, serial | ≤15 transactions |
| 2 | Stage B `ai/tag_correlation.py:124` | **one per money-in deposit**, concurrent(8) | 1 deposit + candidates |
| 3 | AI groups `tag_materialization/ai.py:109` | `ceil(subjects / 15)` × 15 groups | ≤15 subject contexts |
| 4 | Judgment `ai/rule_judgment.py:65` | **16 rules × surviving subjects**, concurrent(8) | **median 415 chars** |
| 5 | Consistency `rule_engine/consistency.py:432` | 1 rule × borrower, only on disagreement | distinct values only |
| 6 | Finding prose `ai/finding_prose.py:598` | 1 per finding + ≤1 retry | fact summary |
| 7 | Needs prose `ai/needs_prose.py:234` | 1 per need + ≤1 retry | fact summary |
| 8 | **Cross-source `ai/snapshot_cross_source.py:372`** | **exactly 1, fingerprint-gated** | **entire snapshot** |

Judgment context is built by `rule_engine/judgment.py:97`:

```python
def _build_context(reasoned_over, subject_tags):
    return {"tags": {tag_id: {value, confidence, reasoning}
                     for tag_id in reasoned_over}}
```

Only the 1–6 tags the rule's YAML spec declares. Measured across `AS-12` on the fixture:
**min 403 / median 415 / max 734 characters.** The snapshot is 87,862. So the per-rule
call carries **0.47 %** of it.

**Nothing sends the whole snapshot per rule.** Grep for `json.dumps` on the verification
path: `judgment.py:662`, `consistency.py:432`, `tag_correlation.py:519`,
`tag_production.py:192`, `ai.py:348` — all over small assembled dicts. Only
`snapshot_cross_source.py:500` dumps the snapshot, once.

Measured reality from LP-635: **591 AI calls, 2,542 s cumulative latency, mean 4.3 s** on a
44-document file. Stage B and the judgment rules are the count; the snapshot is one call.

---

## 3. Bedrock prompt caching — what is true as of today

### The numbers (from AWS's own table, current)

| | Claude Sonnet 4.5 | Claude Haiku 4.5 |
|---|---|---|
| minimum cacheable prefix | **1,024 tokens** | **4,096 tokens** |
| max cache checkpoints | 4 | 4 |
| TTL options | **5 m and 1 h** | 5 m and 1 h |
| cacheable fields | `tools`, `system`, `messages` | same |

Pricing (Sonnet 4.5, $3.00/MTok base input):

| | rate | multiplier |
|---|---:|---:|
| uncached input | $3.00/MTok | 1.0× |
| 5-minute cache **write** | $3.75/MTok | 1.25× |
| 1-hour cache **write** | $6.00/MTok | 2.0× |
| cache **read** | **$0.30/MTok** | **0.1×** |

Mechanics that matter here:

- The minimum is evaluated against the **cumulative `tools` → `system` → `messages`
  prefix**, not per section. `client.py:143` already documents this correctly.
- Under the minimum, caching **silently does nothing** — no error,
  `cache_creation_input_tokens: 0`.
- Any change to an earlier section invalidates every later cache.
- Longer-TTL breakpoints must appear **before** shorter-TTL ones.
- Prompt caching is **not supported on batch inference**.
- Cross-region inference profiles (which we use — the `us.` ids) may **increase cache
  writes** under high demand, because a cache lives on a specific endpoint.

### Two corrections to LP-635

LP-635 §"Item 1 answered: prompt caching cannot help here" reasoned from Haiku's 4,096-token
minimum and explicitly flagged Sonnet's as unconfirmed. Both of its open questions now have
answers, and they change the conclusion at the margins:

**Correction 1 — the Sonnet minimum is 1,024, not 4,096.** Re-run LP-635's own table
against the right threshold:

| prompt | tokens | vs 4,096 (assumed) | vs 1,024 (actual) |
|---|---:|---|---|
| Stage A system prompt | ~1,127 | ✗ | **✓ clears** |
| Stage B system prompt | ~787 | ✗ | ✗ still under |
| 23 AI-group prompts | 131–1,127 | ✗ | ✓ for the largest few |
| needs reasoner (post bug-009) | ~2,936 | ✗ | **✓ clears** |
| judgment rule prompts | ~200–600 | ✗ | ✗ |

**Correction 2 — 1-hour TTL exists now.** AWS shipped it on **2026-01-26** for Sonnet 4.5,
Haiku 4.5 and Opus 4.5, in all commercial and GovCloud regions where those models run. This
matters specifically for the needs reasoner, which LP-635 identified as re-reasoning on
*every document arrival* (`app/tasks/needs.py:78`) — ~44 calls on a 44-document file, spread
across ingestion, quite possibly more than 5 minutes apart. A 5-minute TTL would have missed
most of them; a 1-hour TTL will not.

### But LP-635's *bottom line* still stands

Caching a 1,127-token prefix across 12 Stage A calls, or a 2,936-token prefix across 44
needs calls, is worth roughly:

```
needs:   44 × 2,936 tok × ($3.00 − $0.30)/1M  ≈  $0.35 per file
Stage A: 12 × 1,127 tok × $2.70/1M            ≈  $0.04 per file
```

Real, free, and small. **It does not touch the 591-call problem**, because the call that
repeats hundreds of times — Stage B — has a 787-token prefix and is the one furthest under
the minimum.

### Where caching is actually worth something: as an enabler

The break-even is startlingly low. For a prefix of `P` tokens reused `N` times on Sonnet:

```
uncached:  N × P × 3.00
5m cache:  P × 3.75 + (N−1) × P × 0.30    → pays from the 2nd call  (N > 1.28)
1h cache:  P × 6.00 + (N−1) × P × 0.30    → pays from the 3rd call  (N > 2.11)
```

So the question is not "can we save on what we send today" — we send almost nothing today.
It is **"what would we send if it were nearly free?"**

Concretely: a shared **loan-core context block** — borrowers, loan terms, subject property,
the four calculator outputs, the document inventory — call it 4K tokens, byte-identical
across every reasoning call in a run.

```
591 calls × 4,000 tok, uncached:  591 × 4,000 × $3.00/1M  =  $7.09 / file
591 calls × 4,000 tok, 1h cache:  4,000 × $6.00/1M
                                + 590 × 4,000 × $0.30/1M  =  $0.73 / file
```

**Ten times cheaper**, and it is the difference between "each rule judges on 415 characters
of tags with no idea what loan it is looking at" and "each rule judges with the file's
shape in front of it". That is a quality argument, not a cost one, and caching is what
makes it affordable.

The required shape (Messages API, which is what `AsyncAnthropicBedrock` uses):

```python
system = [
    {"type": "text",
     "text": LOAN_CORE_CONTEXT,                      # identical for every call in the run
     "cache_control": {"type": "ephemeral", "ttl": "1h"}},
    {"type": "text", "text": spec.judgment.system_prompt},   # varies per rule, AFTER the breakpoint
]
messages = [{"role": "user", "content": context_json}]        # varies per subject
```

Note `complete()` currently takes `system: str | None` and passes it through
(`client.py:600`). Accepting a **list of blocks** is a one-line signature change; the SDK
already supports it. This is the smallest enabling change in the whole document.

Three traps, all of which this codebase has hit before in other forms:

1. **Verify by reading `cache_read_input_tokens` back.** `AICompletion` already carries
   `cache_read_tokens` / `cache_write_tokens` (`client.py:100`) and `complete()` already
   logs both. Zero on both means the prefix fell under the minimum — the silent no-op.
   Do not ship on the assumption that a flag worked; LP-635's own note says this.
2. **The prefix must be byte-identical.** A timestamp, a run id, a dict whose key order
   is not pinned, or a float that formats differently will produce a fresh hash every
   call. `snapshot_payload` already uses `sort_keys=True` — the core block needs the same
   discipline.
3. **`billed_input_tokens` already exists for this** (`client.py:110`) precisely because
   `input_tokens` is the *uncached remainder*. Any cost estimate written against a cached
   call must use it, or it will under-report by an order of magnitude — the bug LP-628's
   review caught one layer down.

---

## 4. What I would actually do, in order

### A. Stop the silent oversize failure (small, urgent)

Two changes, neither of which needs a design decision:

1. **Measure the payload before sending it.** In `snapshot_payload`, log
   `len(payload)` and a token estimate; carry it onto the run. Right now nobody can answer
   "how big are our snapshots" without a database query, which is why this document has
   projections instead of facts.
2. **Distinguish an oversize 400 from every other 400.** `infra_failure_kind()` already
   exists and returns `INFRA_OVERSIZED`; the cross-source call site never calls it. Catch
   `AIClientError` specifically, classify it, and put the real reason in the degradation
   string — the underlying "Input is too long" text lives on `__cause__` and is being
   thrown away today. A processor being told "cross-source review not refreshed" when the
   truth is "this file is too large to review" is the LP-637 failure mode again.

### B. Bound the snapshot (the actual fix)

The snapshot is a **model input** and a **persisted artifact** and it is currently the same
object for both. It should not be. The cross-source pass does not need 400 individual
transaction rows to notice that a tax bill's assessed value disagrees with a stated
valuation. Options, cheapest first:

1. **Drop the duplicate transaction channel from the model payload.** Bank-statement rows
   are emitted to `entry.transactions` *and* `entry.lists["transactions"]`
   (`documents_section.py:774`, wired under LP-443), and the generic one is "read by no rule
   yet" by its own comment. Keep both in the persisted blob if the belt-and-braces argument
   still holds; send one to the model. **Confirm on a production snapshot first** — the eval
   fixture predates this wiring (`lists: {}` on all five of its bank statements), so the
   duplication is not visible in the numbers above and every documents-section figure in this
   document is *understated* by roughly the size of the generic channel (~680 B/row vs the
   legacy ~400 B).
2. **Project a `model_payload` view.** A `Snapshot.for_reasoning()` that drops
   `tags.by_subject` entries for transaction subjects (they are Stage-A/B outputs the
   cross-source pass does not reason over), collapses transaction rows into per-statement
   aggregates plus outliers, and truncates `reasoning` strings. Given `tags` is **72 %** of
   the fixture and transaction subjects are all of it, this alone is likely a 5–10×
   reduction. **The fingerprint must hash the projection, not the full snapshot**, or the
   cache-hit logic in `refresh_snapshot_findings` starts re-asking on changes the model
   cannot see.
3. **Only then** consider the 1M-token context window (Sonnet 4.x supports it on Bedrock
   behind a beta header, with >200K input priced at 2×). Buying headroom before capping
   growth just moves the cliff and doubles the price of walking off it.

### C. Prompt caching (do it, but for the right reason)

1. **Enable it where it already clears the minimum**, today: the needs reasoner (~2,936
   tokens × ~44 calls) with `ttl: "1h"`, and Stage A (~1,127 × ~12) with `5m`. Confirm
   with `cache_read_tokens > 0`. Expected ≈ $0.40/file. Do it because it is free, not
   because it is the fix.
2. **Change `complete()` to accept a system block list.** One-line signature change,
   unblocks everything else.
3. **Then** decide whether a shared loan-core context block is worth adding to the
   judgment path. That is a **quality** proposal with a cost of ~$0.73/file, not a saving.
   It needs the calibration harness, because it changes every judgment prompt and can move
   verdicts — the same reason LP-635 deferred batching Stage B.

### D. The call count is still the real cost

Unchanged from LP-635's open items, and still the biggest number on the page: **591 calls**.
Caching does not reduce it. Batching Stage B fifteen deposits per call, the way Stage A and
the tag groups already work, would — and LP-635 correctly notes it changes the prompt and
must be validated against the calibration harness rather than shipped on reasoning.

---

## 5. "If we don't send the snapshot, how does a rule get full context?"

It doesn't — **and that is the design, not an oversight.** The file is read once, upstream,
and compressed into structured tags. By the time a rule runs, the loan file *is* its tags.

### The funnel

```
documents → extraction → snapshot          (the file, in full)
          → tag materialization             ← THIS is where the file is read
              tag_materialization/ai.py:109, ≤15 subjects per call,
              each group's own context builder (subjects.py)
          → tags.by_subject                  (143-tag vocabulary, fact_tags.csv)
          → rule engine                      ← reads ONLY declared tags
              load_bearing_tags  → the fail-closed gate
              reasoned_over      → the AI context (judgment.py:97)
```

`CLAUDE.md` states the principle: *"Deterministic rules; AI only for perception
(classify/extract)."* Perception happens at materialization. Rules adjudicate over the
output of perception. The 415-character judgment context is not a truncation of the
snapshot — it is the whole point.

### Why the narrow context buys something real

Three properties depend on the context being a **declared, finite list** rather than "the
file":

1. **The fail-closed gate works before any AI call.** `evaluate_gate` (`judgment.py:628`)
   checks that every `load_bearing_tags` entry is present and above the confidence floor.
   Missing or shaky → `COULDNT_CHECK` / `NEEDS_REVIEW` with **no model call and no tag
   written**. You cannot write that gate against "the whole file", because there is no
   answer to "is the whole file confident enough".
2. **Verdicts are auditable and calibrated.** A finding cites named tags with values and
   confidences. "The model read the file and decided" cites nothing, cannot be replayed,
   and cannot be calibrated — and the live bars are calibrated on this shape
   (`config.py:104`).
3. **Cost and determinism.** 591 calls at 415 characters is affordable; at 23K tokens it
   is not, and temperature-0 over a 23K-token payload is far less stable than over six
   named tags.

### Where the design actually leaks — three gaps, and one is load-bearing

**Gap 1 — `per_deposit` does not merge loan-level tags, while the other enumerators do.**

```python
# enumerators.py:126  _per_borrower   →  {**loan_tags, **borrower_tags}   ✓
# enumerators.py:161  _per_document   →  {**loan_tags, **entry_tags}      ✓
# enumerators.py:72   _per_deposit    →  by_subject.get(txn.content_id, {})   ✗ no loan tags
```

`per_deposit` is the **highest-volume** judgment path — `AS-12` and `FR-5` fire once per
transaction and are the bulk of the 591 calls. Those are exactly the rules judging without
loan-level facts.

**Gap 2 — `loan_tags` reaches the evaluator but never the prompt.** `_evaluate_subject`
receives `loan_tags` (`judgment.py:580`) and uses it for **applicability** and
**materiality** — deterministic gating — but `_build_context(jud.reasoned_over,
subject_tags)` never reads it. Loan-level facts decide *whether* the model is asked; they
are not part of *what it knows*.

**This has already cost a real defect, and the spec documents it.** `AS-12.yaml:57-66`,
after LP-516 added `txn.amount` and `txn.date` because the prompt was asking about signals
the model could not observe:

> ⚠️ Two of the prompt's three signals, not all three: "proximity to closing" also needs
> the loan's closing date (`contract.loan_closing_date`), which is loan-level and absent on
> the file this ticket came from — the same gap that makes IH-3 abstain there.

The prompt asks a senior underwriter to spot "funds appearing just before closing". The
model is not told when closing is. It cannot be, through `per_deposit`, today.

**Gap 3 — no cross-subject context.** `AS-12` judging deposit #7 knows nothing about
deposits #1–6. Five identical $9,500 deposits are five independent judgments, and the
pattern that makes them interesting is invisible to every one of them. (`AS-2.yaml:48`
records the sibling symptom: "nine distinct deposits as nine identical rows".)

### The escape hatch is the cross-source pass — and that is why *it* gets the snapshot

`ai/snapshot_cross_source.py` is the one pass that sees the whole file, and its docstring
says exactly why: *"this pass exists for the pairings NOBODY WROTE A RULE FOR."* It is also
deliberately declawed — *"IT NOTICES; IT DOES NOT JUDGE... a finding may never write to the
loan."*

So the architecture's answer to "who sees the whole file" is: **one pass, once per run, and
it is not allowed to change anything.** Everything that *can* change the loan reasons over
named, gated, calibrated tags.

### What to do about a context gap

Not "send the snapshot". The correct moves, cheapest first:

1. **Add the tag to `reasoned_over`.** This is the intended lever and LP-516/LP-522 are
   both examples of pulling it. Costs a few hundred tokens per call.
2. **Merge loan tags into `_per_deposit`**, matching `_per_borrower` and `_per_document`.
   One line. It closes the `AS-12` closing-date gap for every per-deposit rule at once.
   It changes prompts, so it goes through the calibration harness.
3. **The shared loan-core context block from §3.** This is where caching stops being a
   rounding error and becomes the enabling mechanism: giving all 591 calls a 4K block of
   loan-level facts costs **$7.09/file uncached and $0.73 with a 1-hour breakpoint**. Gaps
   1 and 2 are precisely the problem it solves, and the cache is what makes solving it
   affordable.

A useful test for any future "the model needs more context" instinct: **if the missing fact
has a tag, it is a `reasoned_over` change. If it does not have a tag, it is a
`fact_tags.csv` change. It is never a reason to send the snapshot.**

---

## Measure this first

Everything above marked "projection" is arithmetic from a 5-document fixture.

**Correction to an earlier claim in this document:** staging *is* queryable —
`./scripts/deploy staging query`, documented in `docs/querying-staging.md`, and
`snapshot_json` comes back through the `readonly.*` views as scrubbed-but-queryable JSON,
which is exactly the shape these queries need. What blocked me is narrower: the shell this
session reaches has no `aws` binary, so the script stops at
`STOPPED Required command not found: aws`. **Someone with the CLI should run these three;
they turn every projection above into a fact.**

```sql
-- 1. Snapshot size distribution. Is 700 KB reachable, or already reached?
SELECT run_id,
       pg_column_size(snapshot_json)        AS jsonb_bytes,
       length(snapshot_json::text)          AS json_chars,
       length(snapshot_json::text) / 3.5    AS est_tokens
FROM   snapshot_records
ORDER  BY 3 DESC
LIMIT  20;

-- 2. Section split on the largest ones. Is `tags` really 72 % in production?
SELECT run_id,
       length(snapshot_json->>'tags')         AS tags_chars,
       length(snapshot_json->>'documents')    AS docs_chars,
       length(snapshot_json->>'calculations') AS calc_chars
FROM   snapshot_records
ORDER  BY length(snapshot_json::text) DESC
LIMIT  10;

-- 3. Has the oversize failure already happened and been logged as a generic degradation?
--    (grep staging logs)
--    snapshot_findings_failed  error=AIClientError
```

And one log check: `ai_call_succeeded` where `cache_read_tokens > 0` — should be zero
outside the chunked-extraction path today. That is the baseline any caching change is
measured against.

## Sources

- [Prompt caching for faster model inference — Amazon Bedrock](https://docs.aws.amazon.com/bedrock/latest/userguide/prompt-caching.html)
- [Amazon Bedrock now supports 1-hour duration for prompt caching](https://aws.amazon.com/about-aws/whats-new/2026/01/amazon-bedrock-one-hour-duration-prompt-caching)
- [Prompt caching — Claude Platform Docs](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)
- [Context windows — Claude Platform Docs](https://platform.claude.com/docs/en/build-with-claude/context-windows)
- [GENCOST03-BP03 Implement prompt caching to reduce token costs — AWS Generative AI Lens](https://docs.aws.amazon.com/wellarchitected/latest/generative-ai-lens/gencost03-bp03.html)
- [Claude on Bedrock "Input is too long for requested model" — AWS re:Post](https://repost.aws/questions/QUshd0uzCZRAy1TbudkUKhww/claude-on-bedrock-giving-input-is-too-long-for-requested-model-for-10k-token-inputs-edit-broken-in-eu-central-1-working-in-other-regions)
- Internal: `docs/tickets/LP-635.md`, `docs/tickets/LP-210.md`, `docs/tickets/LP-628.md`
