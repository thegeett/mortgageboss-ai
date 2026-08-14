# Provider-agnostic test suite

Make the backend test suite's result independent of the gitignored, per-worktree `backend/.env`.

## The headline: `.env` leaks into the whole suite

**`app/core/config.py` builds the `settings` singleton at import from `.env`** (`env_file=".env"`, then
`settings = get_settings()` at module load). Tests import `app`, so the entire suite reads whatever the
local, gitignored, per-worktree `.env` happens to contain. **A test's result should never depend on a
file that is not part of the test** — yet before this change, flipping one line in `.env` flipped the
suite.

Concretely: this worktree's `.env` carries `AI_PROVIDER=bedrock`, and that alone made **15 tests fail**
that pass under the shipped `anthropic` default. The 15 are only the symptom. **The disease is the
leak** — the same mechanism means any local override of a model tier, an RPM ceiling, a storage path,
etc. could silently change a test outcome on one machine and not another. That is the finding worth
keeping; the 15 tests are just where it surfaced first.

**Scope note.** The fix here neutralises the one variable that currently flips a result — the AI
provider — via a suite-wide baseline fixture. A fuller remediation (constructing `settings`
hermetically for tests, so *no* `.env` value reaches the suite) is larger and out of scope; it is noted
here as the real end state.

## The fix: an autouse baseline fixture

`tests/conftest.py` gains one autouse, function-scoped fixture:

```python
@pytest.fixture(autouse=True)
def _pin_ai_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ai_provider", "anthropic")
```

- **Autouse by design.** A test must *opt out* of the hermetic baseline (by monkeypatching the provider
  itself) to exercise a different provider — it never has to opt in. A future test that accidentally
  reads the ambient provider is the exception that must act deliberately, not the silent default.
- **Provider-specific tests still win.** `test_provider_selection_b1.py`'s `_use_bedrock(monkeypatch)`
  (and any per-test override) runs *after* this fixture and wins within the test body; both unwind
  cleanly at teardown. So the deliberate Bedrock guards are untouched.

This one fixture fixes the 13 bucket-A tests. The 2 bucket-B tests get targeted edits so they assert the
real invariant rather than the fixture's pin.

## The 15, classified

The buckets: **A** — doesn't care about the provider (assert behaviour, not the vendor); **B** —
legitimately tests provider selection (pin the provider explicitly); **C** — genuinely differs per
provider (parametrise). **No test was bucket C** — Bedrock behaviour is already covered explicitly in
`test_provider_selection_b1.py`, so a companion would be redundant. No deliberate provider guard was
removed.

| Test(s) | Bucket | Why it failed under bedrock | What changed |
|---|---|---|---|
| `test_client.py` — 12 wrapper tests: `test_complete_returns_content_and_usage`, `…passes_optional_system_and_temperature`, `…retries_transient_then_succeeds`, `…non_transient_fails_fast_without_retry`, `…exhausted_transient_retries_raises`, `…backoff_delays_increase`, `…success_log_has_metadata_not_content`, `…failure_log_has_metadata_not_content`, `…missing_key_raises_at_call_time`, `…complete_forwards_document_message`, `…retry_works_with_document_input`, `…document_bytes_and_base64_never_logged` | **A** | These mock the SDK and test the wrapper's retry/backoff/logging/forwarding policy. Under bedrock, `complete()`'s `resolve_model("m")` rejects the placeholder model (or `get_anthropic_client()` builds a keyless Bedrock client) *before* the mock is reached. They only ever assumed the anthropic path implicitly. | **No per-test edit** — the baseline fixture restores the known anthropic path they were written against. |
| `test_document_processing.py::test_happy_path_pay_stub` | **A** | Asserted `model_used == settings.anthropic_model_extraction` (the tier literal). The pipeline correctly stores `resolve_model(...)` — the mapped Bedrock profile under bedrock — so the literal mismatched. It was asserting the vendor string, not the behaviour. | Assert `model_used == resolve_model(settings.anthropic_model_extraction)` — "records the model it actually invoked", correct under either provider. |
| `test_provider_selection_b1.py::test_default_provider_is_anthropic` | **B** | Read the ambient singleton (`settings.ai_provider == "anthropic"`), which reflects `.env`. The real invariant is the *declared default*, not the ambient value. | Keep the field-default assertion; add a hermetic fresh-construction check (`delenv("AI_PROVIDER")` + `Settings(_env_file=None, …)` with the other required settings supplied) and drop the ambient read. |
| `test_model_resolution_boundary.py::test_resolve_model_returns_anthropic_ids_in_this_worktree` → renamed `…_under_anthropic` | **B** | Asserted the *ambient* provider (`settings.ai_provider == "anthropic"`) as a "this worktree stays anthropic" guard — a guard this worktree deliberately voids by running `AI_PROVIDER=bedrock`. | Pin `ai_provider="anthropic"` explicitly, keep the identity + `claude-` id assertions, rename to drop "in_this_worktree". |

## Test 15: the worktree-policy guard is now a behaviour test

The old `test_resolve_model_returns_anthropic_ids_in_this_worktree` did double duty: it verified
`resolve_model()` is the identity under anthropic **and** asserted, as a guard, that *this worktree's
ambient provider is anthropic* ("an accidental flip to bedrock is the least-visible failure here").

That guard is intentionally void now — the worktree runs `AI_PROVIDER=bedrock` on purpose. The rewrite
keeps the valuable half (identity + `claude-` ids, under a **pinned** anthropic provider) and drops the
ambient assertion. **The consequence, stated plainly:** the test suite no longer warns you if a worktree
is unexpectedly on a given provider. A "this deployment/worktree must be on provider X" check is a
runtime/deployment concern, not a unit-test one — **if you want that warning, it must live outside the
suite** (e.g. a pre-run environment check or a startup log assertion), because a hermetic suite must not
assert on ambient state by construction.

## Does anything else depend on ambient environment?

Only two test files read `settings.ai_provider` directly — both handled above. The other 13 failures
were *transitive* (through `resolve_model()` / `get_anthropic_client()`), not direct reads. Beyond the
provider, no other test asserts on an ambient setting today — but that is not a guarantee, because the
root leak (`.env` → `settings` singleton → every test) remains. The autouse fixture closes the provider
vector and makes "read ambient settings" an opt-out; the broader hermetic-settings remediation is the
real fix for the class.

## Proof — same result regardless of `AI_PROVIDER`

Full suite, three ambient conditions (no model calls in any):

| `AI_PROVIDER` | Result |
|---|---|
| `anthropic` (overrides `.env`) | **4010 passed**, 5 skipped, 1 xfailed, 0 failed |
| `bedrock` (matches `.env`) | **4010 passed**, 5 skipped, 1 xfailed, 0 failed |
| unset (OS var removed; `.env` still says bedrock) | **4010 passed**, 5 skipped, 1 xfailed, 0 failed |

Identical across all three — the suite's result no longer depends on the ambient provider. (Before this
change, the `bedrock` column was 15 failed / 4012 passed on `extraction_bench`; the 4010 baseline here
excludes the 17 bench tests that live only on that branch.)

> "Unset" removes the OS env var; `.env` still pins `bedrock`, so it resolves via `.env` — yet the
> result is identical to the other two because the autouse fixture governs every test. That identity is
> the whole point.

- `ACTIVE_RULE_IDS` = **37**, the 37 live rule ids unchanged (read from the registry, no live run).
- `ruff` clean; `mypy app/` (CI scope) clean. (Test files are outside CI's mypy scope; the edits add no
  new error beyond the file's own pre-existing, idiomatic `pipeline.`-attribute pattern.)

## Branch

Committed on **`phase3_bucket_2`**, not `extraction_bench`. The failing files and the root cause
(`.env`-reading config, merged at `cbf2a52`) live on `phase3_bucket_2`; `extraction_bench` is that
commit plus the unrelated bench feature. This is cross-cutting test-infra hygiene, so it belongs at the
base where every branch off it inherits the fix. `extraction_bench` picks it up on its next merge/rebase.

## Files changed

- `backend/tests/conftest.py` — the `_pin_ai_provider` autouse fixture.
- `backend/tests/ai/test_provider_selection_b1.py` — `test_default_provider_is_anthropic` hermetic.
- `backend/tests/ai/test_model_resolution_boundary.py` — test 15 pinned + renamed (+`import pytest`).
- `backend/tests/tasks/test_document_processing.py` — `test_happy_path_pay_stub` provider-agnostic.
