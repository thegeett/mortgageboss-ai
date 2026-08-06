#!/usr/bin/env python
"""Run the extraction bench over a folder of real documents — ENTIRELY IN THE TERMINAL.

Same run as the dev UI (`/dev/extraction-bench`): same engine, same output root, same abort rules —
so a CLI run and a UI run are interchangeable and either can `--resume` the other's run id. The
difference is durability: nothing here depends on a browser tab staying open, so a 50-90 minute
Bedrock run cannot be killed by a refresh or a closed window.

    cd backend
    uv run python scripts/extraction-bench.py ~/corpus                 # preview, then confirm
    uv run python scripts/extraction-bench.py ~/corpus --yes           # no prompt
    uv run python scripts/extraction-bench.py ~/corpus --preview-only  # nothing runs, no model call
    uv run python scripts/extraction-bench.py ~/corpus --resume a1b2c3d4e5f6

To survive a closed terminal (and, on macOS, sleep):

    caffeinate -is nohup uv run python scripts/extraction-bench.py ~/corpus --yes \
      > ~/bench-run.log 2>&1 &
    tail -f ~/bench-run.log

The run id and output dir are printed BEFORE the first model call, so an interrupted run is always
resumable. Records are written per document as they complete — a hard kill loses at most the
in-flight document.

⚠️ MEASURES COVERAGE, NOT ACCURACY, and captures REAL values — the output folder contains real
borrower PII and must never be committed, shared, or moved off this machine.

Exit codes: 0 ok · 1 refused (unpaced / preflight / bad path) or the run self-aborted · 130 Ctrl-C.
"""

from __future__ import annotations

import argparse
import asyncio
import shutil
import signal
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # imported lazily in _run so `--help` works without a loadable .env
    from app.dev.bench.engine import RunProgress

_ABORTED = 1
_INTERRUPTED = 130


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="extraction-bench.py",
        description="Run the extraction bench over a document corpus, in the terminal.",
        epilog=(
            "Output goes to BENCH_OUTPUT_DIR (or <storage>/bench_output). It contains REAL PII — "
            "do not commit, share, or move it off this machine."
        ),
    )
    parser.add_argument("root", help="Directory of documents to run (walked recursively)")
    parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Skip the confirmation prompt after the preview (required when not on a TTY)",
    )
    parser.add_argument(
        "--preview-only",
        action="store_true",
        help="Print the preview and exit — nothing runs, no model is called, nothing is spent",
    )
    parser.add_argument(
        "--resume",
        metavar="RUN_ID",
        default=None,
        help="Continue an interrupted run: reuse its output dir and skip documents already done",
    )
    return parser.parse_args(argv)


def _print_preview(pv: Any, *, plan_to_run: int | None = None) -> None:
    print("-" * 72)
    print(f"root              {pv.root}")
    print(f"files found       {pv.total}  ({pv.readable} readable)")
    print(f"by extension      {pv.by_extension}")
    print(f"provider / model  {pv.provider} / {pv.extraction_model}")
    rpm = pv.requests_per_minute
    print(f"pacing            {rpm if rpm else 'UNPACED'} requests/min")
    mins = pv.estimated_minutes
    print(
        f"estimated time    {f'~{mins} min (floor)' if mins is not None else 'unknown (unpaced)'}"
    )
    print(
        f"estimated cost    ~${pv.estimated_cost}  (rough: {pv.readable} x ${pv.per_doc_estimate})"
    )
    if plan_to_run is not None and plan_to_run != pv.readable:
        print(
            f"to run now        {plan_to_run}  ({pv.readable - plan_to_run} already done — resume)"
        )
    if pv.unreadable:
        print(f"unreadable        {len(pv.unreadable)} (skipped, not sent to the model):")
        for u in pv.unreadable[:10]:
            print(f"                    {u['file']} — {u['reason']}")
        if len(pv.unreadable) > 10:
            print(f"                    … and {len(pv.unreadable) - 10} more")
    print("-" * 72)
    print(
        "⚠️  Measures COVERAGE, not accuracy. Captures REAL values — the output contains real PII."
    )


def _fmt_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{int(seconds)}s"
    minutes = int(seconds // 60)
    return f"{minutes}m" if minutes < 60 else f"{minutes // 60}h{minutes % 60:02d}m"


def _outcome(record: dict[str, Any]) -> tuple[str, str]:
    """(glyph, label) for one finished document — the CLI's version of the UI's per-document state."""
    dtype = record.get("classified_type", "?")
    if record.get("rate_limited"):
        return "⚠", "THROTTLED"
    if record.get("ai_failed") or dtype == "error":
        return "✗", f"FAILED ({record.get('failure_error_type') or 'error'})"
    status = (record.get("extraction") or {}).get("status", "?")
    return "✓", f"{dtype} · {status}"


class _Display:
    """Live progress, mirroring the dev UI's run panel — progress bar, done/total, cost so far,
    infrastructure-failure counts, and the document currently in flight — plus an ETA the UI has no
    room for. Same data the UI polls; the engine updates ``RunProgress`` and this reads it.

    Two modes, chosen by whether stdout is a terminal:

    * **TTY** — a PINNED status line at the bottom, redrawn a few times a second, with one scrolling
      line per finished document above it. The in-flight filename updates live, exactly like the UI.
    * **NOT a TTY** (``nohup``, a pipe, CI) — no redraws, because carriage returns turn a log file into
      mush. One self-contained line per document instead, each carrying the counters and the ETA, so
      ``tail -f ~/bench-run.log`` reads as a progress view.
    """

    _BAR_WIDTH = 26

    def __init__(self, progress: RunProgress, *, tty: bool) -> None:
        self._p = progress
        self._tty = tty
        # Documents already on disk from a resumed run are NOT work done this session — excluding them
        # keeps the rate (and so the ETA) honest on a resume.
        self._started_done = progress.done
        self._t0 = time.monotonic()
        self._pinned = False

    def _eta_seconds(self) -> float | None:
        """Remaining time at the rate MEASURED so far — truer than the preview's pacing floor, which
        assumes no retries and no truncation second calls. None until a document has finished, and
        None again once there is nothing left (a "~0s left" on a finished run is just noise)."""
        remaining = self._p.total - self._p.done
        ran = self._p.done - self._started_done
        elapsed = time.monotonic() - self._t0
        if remaining <= 0 or ran <= 0 or elapsed <= 0:
            return None
        return remaining / (ran / elapsed)

    def _status_line(self) -> str:
        p = self._p
        pct = (p.done / p.total * 100) if p.total else 100.0
        filled = round(self._BAR_WIDTH * pct / 100)
        parts = [
            f"{'█' * filled}{'░' * (self._BAR_WIDTH - filled)} {pct:3.0f}%",
            f"{p.done}/{p.total}",
            f"${p.cost_so_far:.2f}",
        ]
        if p.failed:  # infrastructure, NOT coverage gaps — the summary says so too
            throttled = f" ({p.rate_limited} throttled)" if p.rate_limited else ""
            parts.append(f"{p.failed} failed{throttled}")
        eta = self._eta_seconds()
        if eta is not None:
            parts.append(f"~{_fmt_duration(eta)} left")
        parts.append(p.current or "finalizing report…")
        return " · ".join(parts)

    def tick(self) -> None:
        """Redraw the pinned status line (TTY only). Truncated to the terminal width — a wrapped line
        would scroll instead of overwrite, leaving a trail of stale bars."""
        if not self._tty:
            return
        line = self._status_line()
        width = shutil.get_terminal_size(fallback=(100, 24)).columns - 1
        if len(line) > width:
            line = line[: max(width - 1, 0)] + "…"
        print(f"\r\033[K{line}", end="", flush=True)
        self._pinned = True

    def clear(self) -> None:
        if self._tty and self._pinned:
            print("\r\033[K", end="", flush=True)
            self._pinned = False

    def line(self, text: str) -> None:
        """Print a line ABOVE the pinned status (which is cleared, then redrawn under it)."""
        self.clear()
        print(text, flush=True)
        self.tick()

    def on_document(self, record: dict[str, Any], progress: RunProgress) -> None:
        glyph, mark = _outcome(record)
        name = record.get("source_relpath") or record.get("source_filename")
        if self._tty:
            self.line(f"{glyph} {name} → {mark}")  # counters live in the pinned line below
            return
        eta = self._eta_seconds()
        left = f" · ~{_fmt_duration(eta)} left" if eta is not None else ""
        self.line(
            f"[{progress.done}/{progress.total}] ${progress.cost_so_far:.2f}{left}  {name} → {mark}"
        )

    async def run_ticker(self) -> None:
        """Redraw while a document is in flight, so the bar and the current filename stay live between
        completions — at 5 requests/min a document takes ~24s, and a frozen screen reads as a hang."""
        while True:
            self.tick()
            await asyncio.sleep(0.4)


async def _run(args: argparse.Namespace) -> int:
    # Imported here, not at module scope: building the Settings singleton needs backend/.env, and
    # `--help` must work without it.
    import structlog
    from app.ai.client import AIClientError
    from app.dev.bench.engine import (
        ResumeNotFoundError,
        preflight,
        prepare_run,
        preview,
        run_corpus,
        unpaced_reason,
    )

    # Send structlog to STDERR. The engine logs warnings (bench_document_failed / bench_aborted) and
    # structlog's default factory prints to stdout — which is where the pinned progress line lives, so a
    # warning would smear across it. stderr keeps the live display clean and still shows the warning.
    structlog.configure(logger_factory=structlog.PrintLoggerFactory(file=sys.stderr))

    root = Path(args.root).expanduser()
    if not root.is_dir():
        print(f"not a directory: {root}", file=sys.stderr)
        return _ABORTED

    pv = preview(root)  # nothing sent to a model
    try:
        plan = prepare_run(root, args.resume)
    except ResumeNotFoundError:
        print(f"no run to resume: {args.resume}", file=sys.stderr)
        return _ABORTED
    _print_preview(pv, plan_to_run=len(plan.to_run) if plan.resumed else None)

    if args.preview_only:
        return 0
    if not plan.to_run:
        print("nothing to run — every readable document is already done.")
        return 0

    # REFUSE an unpaced Bedrock batch (the API returns 409 on the same condition) — it would be
    # throttled within seconds and its findings corrupted by rate-limit failures.
    reason = unpaced_reason()
    if reason is not None:
        print(f"Refusing to start: {reason}", file=sys.stderr)
        return _ABORTED

    if not args.yes:
        if not sys.stdin.isatty():
            print("Refusing to start: not a TTY and --yes was not passed.", file=sys.stderr)
            return _ABORTED
        if input(f"Run {len(plan.to_run)} documents? [y/N] ").strip().lower() not in {"y", "yes"}:
            print("aborted by user — nothing ran, nothing spent.")
            return _ABORTED

    # PREFLIGHT — one minimal live call proving the model backend is reachable + authenticated BEFORE
    # we process anything. Refuse with the REAL cause rather than march the whole corpus into "AI call
    # failed" records (as the 246-doc run did when the AWS session was not logged in).
    try:
        await preflight()
    except AIClientError as err:
        print(
            f"Preflight failed — the model backend is unreachable or unauthenticated: "
            f"{err.__cause__ or err}\nUnder Bedrock this is almost always AWS credentials: set "
            f"AWS_PROFILE (in .env) and run `aws sso login --profile <name>`, then retry.",
            file=sys.stderr,
        )
        return _ABORTED

    # The run id FIRST — printed before a single call is made, so an interrupted run is resumable even
    # if everything after this scrolls away or the terminal dies.
    print(f"\nrun id            {plan.run_id}")
    print(f"output dir        {plan.out_dir}")
    print(
        f"resume with       uv run python scripts/extraction-bench.py {args.root} "
        f"--resume {plan.run_id} --yes"
    )
    print(f"starting {len(plan.to_run)} documents…\n", flush=True)

    started = time.monotonic()
    display = _Display(plan.progress, tty=sys.stdout.isatty())

    # STOPPING GRACEFULLY. Both signals stop after the IN-FLIGHT document and still write the report —
    # the same path the UI's Cancel button takes:
    #   SIGINT  (Ctrl-C)      — the attached case.
    #   SIGTERM (`kill <pid>`) — the DETACHED case, and the reason this is handled at all: a nohup'd run
    #                            has no terminal to Ctrl-C, so `kill` is the only way to ask it to stop.
    #                            Unhandled, SIGTERM's default action is immediate death — the per-document
    #                            JSON would survive (it is written incrementally) but _SUMMARY.md and
    #                            _FINDINGS.csv would never be written, and that is the point of the run.
    # A SECOND signal is the OS's to handle: hard kill, records already on disk, resume from the run id.
    loop = asyncio.get_running_loop()
    interrupted = False

    def _cancel(signame: str) -> None:
        nonlocal interrupted
        interrupted = True
        plan.progress.cancelled = True
        display.line(f"{signame} — finishing the in-flight document, then writing the report…")
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.remove_signal_handler(sig)  # a second signal hard-kills

    loop.add_signal_handler(signal.SIGINT, _cancel, "interrupted")
    loop.add_signal_handler(signal.SIGTERM, _cancel, "terminated")

    ticker = asyncio.create_task(display.run_ticker())
    try:
        await run_corpus(
            plan.run_id,
            root,
            plan.to_run,
            plan.out_dir,
            plan.progress,
            plan.start_index,
            on_document=display.on_document,
        )
    finally:
        ticker.cancel()
        display.clear()  # the pinned line must not survive into the summary below

    p = plan.progress
    print("-" * 72)
    print(
        f"done              {p.done}/{p.total} documents in {_fmt_duration(time.monotonic() - started)}"
    )
    print(f"failures          {p.failed} ({p.rate_limited} throttled) — NOT coverage gaps")
    print(f"actual cost       ${p.cost_so_far:.4f}  (from real token counts)")
    print(f"report            {plan.out_dir / '_SUMMARY.md'}")
    print(f"                  {plan.out_dir / '_FINDINGS.csv'}")
    if p.aborted_reason:
        fix = (
            "You are being throttled — LOWER AI_REQUESTS_PER_MINUTE_BEDROCK, then resume."
            if p.aborted_reason == "rate_limited"
            else f"Fix the cause ({p.abort_error_type or 'AI failure'}) — e.g. AWS credentials — then resume."
        )
        print(f"\n🛑 RUN ABORTED after {p.done} documents ({p.aborted_reason}). {fix}")
        print(
            f"   resume: uv run python scripts/extraction-bench.py {args.root} "
            f"--resume {plan.run_id} --yes"
        )
        return _ABORTED
    if interrupted:
        print(
            f"\nCancelled. Resume: uv run python scripts/extraction-bench.py {args.root} "
            f"--resume {plan.run_id} --yes"
        )
        return _INTERRUPTED
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        return asyncio.run(_run(args))
    except KeyboardInterrupt:  # before the signal handler is installed (e.g. at the prompt)
        print("\ninterrupted", file=sys.stderr)
        return _INTERRUPTED


if __name__ == "__main__":
    sys.exit(main())
