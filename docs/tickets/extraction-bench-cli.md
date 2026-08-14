# Extraction bench — CLI front door

**Status:** done. **Why:** a full corpus run is 50–90 minutes under Bedrock pacing. Driving it from the
dev UI meant the run's lifetime was tied to a browser tab — a refresh, an accidental close, or a laptop
sleep could end it. The run itself never needed a browser; only the progress display did.

## What changed

The bench's behaviour moved OUT of the HTTP layer and into the engine, and a CLI was added beside the
existing UI. **Both front doors now call the same functions**, so they cannot drift and either can
`--resume` the other's run id (they share `OUTPUT_ROOT`).

| | before | after |
|---|---|---|
| planning (run id, out dir, resume dedup) | `api/dev_bench.py` | `dev/bench/engine.py` → `prepare_run()` |
| the per-document loop + abort streak + finalize | `api/dev_bench.py::_run` | `dev/bench/engine.py` → `run_corpus()` |
| `OUTPUT_ROOT`, `FAILURE_ABORT_STREAK` | `api/dev_bench.py` | `dev/bench/engine.py` |
| unpaced-Bedrock refusal | `_require_paced` (409) | `engine.unpaced_reason()`; API 409s, CLI exits 1 |
| front doors | UI only | UI + `backend/scripts/extraction-bench.py` |

`api/dev_bench.py` is now a shell: routing, dev-gating, and the in-memory `_RUNS` map the UI polls.
Nothing about behaviour changed — same preflight, same abort rules, same report.

## Usage

```bash
cd backend
uv run python scripts/extraction-bench.py ~/corpus                 # preview, then confirm
uv run python scripts/extraction-bench.py ~/corpus --yes           # no prompt
uv run python scripts/extraction-bench.py ~/corpus --preview-only  # nothing runs, no model call
uv run python scripts/extraction-bench.py ~/corpus --resume a1b2c3d4e5f6
```

Detached, surviving a closed terminal and (on macOS) sleep:

```bash
caffeinate -is nohup uv run python scripts/extraction-bench.py ~/corpus --yes > ~/bench-run.log 2>&1 &
tail -f ~/bench-run.log
```

Order of operations, deliberately: preview (no model call) → confirm → unpaced refusal → **preflight**
→ print run id + output dir → run. The run id is printed **before the first model call**, so an
interrupted run is always resumable even if the terminal dies.

## Progress display

The same facts the UI's run panel shows — bar, done/total, cost so far, infrastructure-failure counts,
and the document in flight — plus an ETA the UI has no room for. It reads the same `RunProgress` the UI
polls `/status` for; a ticker redraws every 0.4s so the display stays live *between* completions (at
5 rpm a document takes ~24s, and a frozen screen reads as a hang).

Two modes, picked by `sys.stdout.isatty()`:

**TTY** — one scrolling line per finished document, over a pinned status line that updates in place:

```
✓ bob/bank_statement.pdf → bank_statement · success
⚠ bob/credit_report.pdf → THROTTLED
████████████████░░░░░░░░░░  60% · 3/5 · $0.04 · 1 failed (1 throttled) · ~2s left · alice/2024_w2.pdf
```

**Not a TTY** (`nohup`, a pipe, CI) — no redraws, because carriage returns turn a log file into mush.
One self-contained line per document instead, each carrying the counters and the ETA:

```
[3/5] $0.04 · ~2s left  bob/credit_report.pdf → THROTTLED
```

structlog is pointed at **stderr** for the CLI (the engine's `bench_document_failed` /
`bench_aborted` warnings would otherwise print to stdout and smear the pinned line).

The ETA is measured from the rate observed *this session* — documents carried over by a `--resume` are
excluded, or the rate would read as wildly optimistic. It is truer than the preview's pacing floor,
which assumes no retries and no truncation second calls.

## Stopping gracefully

**`SIGINT` (Ctrl-C) and `SIGTERM` (`kill <pid>`) both** set `progress.cancelled` — the run finishes the
in-flight document and still writes `_SUMMARY.md` / `_FINDINGS.csv` (the same path the UI's Cancel button
takes), then prints the resume command. A second signal hard-kills; records are already on disk per
document, so at most the in-flight document is lost.

`SIGTERM` is handled *because* of the detached mode: a `nohup`'d run has no terminal to Ctrl-C, so `kill`
is the only way to ask it to stop — and SIGTERM's default action is immediate death, which would leave
the per-document JSON on disk but neither report file written. Regression-tested by signalling a real
run mid-document and asserting both reports exist.

Exit codes: `0` ok · `1` refused (unpaced / preflight / bad path) or the run self-aborted after
`FAILURE_ABORT_STREAK` consecutive failures · `130` cancelled by signal.

## Decisions

- **The UI stays.** Its preview screen is better than a terminal table, and it costs nothing now that the
  engine holds the loop. It is the right tool for a short run; the CLI is the right tool for a long one.
- **Sequential only, no `--jobs`.** At 5 requests/min with 2 calls/document the client-side rate limiter
  would serialise concurrent workers anyway — parallelism buys nothing until the AWS Bedrock quota rises.
- **No new safety surface.** The CLI runs as the developer, so it needs no dev-env gate of its own (the
  `is_development` gate exists to keep the *HTTP* route off staging/prod). Same output root, so the same
  gitignore protection applies — and the output still contains **real PII**: never commit, share, or move it.

## Verification

`tests/dev/test_extraction_bench.py` (32 tests): the moved-loop tests now target `engine.run_corpus`
(resume-dedup by relpath, abort-after-throttles, abort-after-auth-failures), plus new coverage for
`prepare_run` (fresh / resume-skips-done-and-reruns-failures / unknown id), `unpaced_reason`, the display
(status line contents, no-ETA at 0% and 100%, ETA excludes resumed documents, no control codes off a
TTY), and the CLI itself — preview-only, unpaced refusal, bad root, and an **end-to-end run with the
model stubbed** asserting the per-document lines and the report on disk. Full backend suite green.

The TTY rendering was also verified for real, by driving the CLI through a `pty.openpty()` pair with a
stubbed model and replaying the captured stream as a terminal would draw it.
