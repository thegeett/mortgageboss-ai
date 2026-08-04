#!/usr/bin/env python
"""Verify the Bedrock provider against the REAL Bedrock runtime (B1, task 10).

The unit tests in ``tests/ai/test_provider_selection_b1.py`` are fully stubbed: they
prove the provider switch, the tier map, the startup validation, and the pacing maths,
but nothing about the world this runs in. They cannot tell you whether the inference
profiles exist in your account, whether the IAM role can invoke them, what a real
throttle looks like, or what ``stop_reason`` Bedrock actually returns. This script
answers all four — and **two of its findings are load-bearing for code that is already
merged**:

* **Step 3 (throttle shape)** decides whether ``_is_transient`` retries a throttle. At a
  10 RPM account a misclassified throttle fails the COMMON path, not an edge case.
* **Step 2 (stop_reason)** decides whether the LP-102 truncation guard still fires. If
  Bedrock spells truncation differently, a cut-off extraction is misreported as
  "could not parse extraction" — silently, and exactly the bug LP-102 exists to prevent.

Both are currently implemented against the EXPECTED values and marked PENDING in
``docs/tickets/B1-bedrock-provider-result.md``. Run this, then reconcile.

    cd backend
    AWS_PROFILE=mbai-dev uv run python scripts/verify-bedrock.py --region us-east-1
    AWS_PROFILE=mbai-dev uv run python scripts/verify-bedrock.py --skip-throttle

Credentials come from the AWS default provider chain — SSO or a profile locally, the
task role on ECS. There is no credential flag here on purpose (ADR-360).

Steps:

  1. tiers      — one real call per tier; print model, tokens, latency, stop_reason
  2. truncate   — force a tiny max_tokens and print the EXACT stop_reason string
  3. throttle   — burst until throttled; print the exception type, class and status
  4. cost       — estimate_cost for every call above; FAIL LOUDLY on any $0.00

Exits non-zero on any failure. Step 3 deliberately consumes quota; ``--skip-throttle``
omits it when you would rather not.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time

_OK = "  ok  "
_FAIL = " FAIL "
_INFO = " info "


def _step(label: str, detail: str = "") -> None:
    print(f"[{_OK}] {label}" + (f" — {detail}" if detail else ""), flush=True)


def _info(label: str, detail: str = "") -> None:
    print(f"[{_INFO}] {label}" + (f" — {detail}" if detail else ""), flush=True)


def _fail(label: str, detail: str) -> None:
    print(f"[{_FAIL}] {label} — {detail}", file=sys.stderr, flush=True)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="verify-bedrock.py",
        description="Verify the Bedrock provider end to end against real Bedrock (B1).",
        epilog=(
            "Credentials come from the AWS default provider chain (AWS_PROFILE / SSO "
            "locally, task role on ECS). Exits non-zero on the first failure."
        ),
    )
    parser.add_argument("--region", default=None, help="Override BEDROCK_REGION")
    parser.add_argument(
        "--burst",
        type=int,
        default=15,
        help="Requests to fire when probing for a throttle (default: 15)",
    )
    parser.add_argument(
        "--skip-throttle",
        action="store_true",
        help="Skip step 3 — it deliberately burns quota to provoke a throttle",
    )
    return parser.parse_args(argv)


async def _run(args: argparse.Namespace) -> int:
    # Imported here, not at module scope, so `--help` works without app settings
    # (importing app.core.config builds the Settings singleton, which needs backend/.env).
    from app.ai.client import AIClientError, complete, get_anthropic_client
    from app.ai.cost import estimate_cost
    from app.core.config import resolve_model, settings

    if settings.ai_provider != "bedrock":
        _fail(
            "provider",
            f'AI_PROVIDER is "{settings.ai_provider}", not "bedrock" — set it in the '
            "environment before running this script (it verifies the Bedrock path).",
        )
        return 1
    if args.region:
        settings.bedrock_region = args.region  # type: ignore[misc]

    print(f"provider={settings.ai_provider} region={settings.bedrock_region}")
    print(f"client={type(get_anthropic_client()).__name__}")
    print("-" * 72)

    zero_cost: list[str] = []
    findings: dict[str, str] = {}

    # --- 1. one call per tier ---------------------------------------------------
    tiers = (
        ("classification", settings.anthropic_model_classification),
        ("extraction", settings.anthropic_model_extraction),
        ("reasoning", settings.anthropic_model_reasoning),
    )
    for tier, tier_value in tiers:
        resolved = resolve_model(tier_value)
        started = time.perf_counter()
        try:
            result = await complete(
                model=tier_value,
                messages=[{"role": "user", "content": "Reply with exactly: OK"}],
                max_tokens=32,
            )
        except AIClientError as exc:
            _fail(f"tier:{tier}", f"{type(exc.__cause__).__name__}: {exc.__cause__ or exc}")
            return 1
        latency_ms = int((time.perf_counter() - started) * 1000)
        cost = estimate_cost(
            model=result.model,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
        )
        if cost <= 0.0:
            zero_cost.append(f"{tier} ({result.model})")
        _step(
            f"tier:{tier}",
            f"model={result.model} in={result.input_tokens} out={result.output_tokens} "
            f"{latency_ms}ms stop_reason={result.stop_reason!r} est=${cost:.6f}",
        )
        if resolved != result.model:
            _fail(f"tier:{tier}", f"resolved {resolved!r} but response reported {result.model!r}")
            return 1

    # --- 2. truncation: the EXACT stop_reason string ---------------------------
    from app.ai.client import TRUNCATED_STOP_REASON

    try:
        truncated = await complete(
            model=settings.anthropic_model_extraction,
            messages=[
                {
                    "role": "user",
                    "content": "Count slowly from 1 to 500, one number per line.",
                }
            ],
            max_tokens=16,  # deliberately tiny — must truncate
        )
    except AIClientError as exc:
        _fail("truncate", f"{type(exc.__cause__).__name__}: {exc.__cause__ or exc}")
        return 1

    findings["stop_reason"] = repr(truncated.stop_reason)
    if truncated.stop_reason == TRUNCATED_STOP_REASON:
        _step(
            "truncate",
            f"stop_reason={truncated.stop_reason!r} — MATCHES the canonical value; the "
            "LP-102 truncation guard fires correctly on Bedrock",
        )
    else:
        _fail(
            "truncate",
            f"stop_reason={truncated.stop_reason!r}, expected {TRUNCATED_STOP_REASON!r}. "
            "The truncation guard is NOT firing on Bedrock: a cut-off extraction will be "
            'misreported as "could not parse extraction". Add the alias to '
            "_STOP_REASON_ALIASES in app/ai/client.py — that is the only place needed.",
        )
        return 1

    # --- 3. throttle: what does the SDK actually raise? -------------------------
    if args.skip_throttle:
        _info("throttle", "skipped (--skip-throttle); the task-4 finding stays PENDING")
    else:
        _info("throttle", f"firing {args.burst} concurrent requests to provoke a throttle…")

        # Bypass the wrapper's own retry/pacing for this probe: we want the RAW
        # exception, not a retried-then-wrapped one.
        raw: list[BaseException] = []
        client = get_anthropic_client()
        model_id = resolve_model(settings.anthropic_model_classification)

        async def _raw(i: int) -> None:
            try:
                await client.messages.create(
                    model=model_id,
                    messages=[{"role": "user", "content": f"Reply with the number {i}."}],
                    max_tokens=8,
                )
            except BaseException as exc:
                raw.append(exc)

        await asyncio.gather(*(_raw(i) for i in range(args.burst)), return_exceptions=True)

        if not raw:
            _info(
                "throttle",
                f"no throttle observed in {args.burst} concurrent requests — the account "
                "may have been granted a higher RPM. The task-4 finding stays PENDING; "
                "re-run with a larger --burst to confirm.",
            )
            findings["throttle"] = "not observed"
        else:
            from app.ai.client import _is_transient

            exc = raw[0]
            status = getattr(exc, "status_code", None)
            body = getattr(exc, "body", None)
            transient = _is_transient(exc) if isinstance(exc, Exception) else False
            findings["throttle"] = (
                f"{type(exc).__module__}.{type(exc).__name__} status={status} transient={transient}"
            )
            detail = (
                f"{len(raw)}/{args.burst} failed; first: "
                f"{type(exc).__module__}.{type(exc).__name__} status_code={status} "
                f"body={str(body)[:200]!r}"
            )
            if transient:
                _step("throttle", f"{detail} → classified TRANSIENT (will retry) ✓")
            else:
                _fail(
                    "throttle",
                    f"{detail} → classified NON-TRANSIENT. It will FAIL FAST instead of "
                    "retrying, which at this account's RPM is the common path. Extend "
                    "_BEDROCK_TRANSIENT_CODES / _is_transient in app/ai/client.py.",
                )
                return 1

    # --- 4. cost: any zero is a failure ----------------------------------------
    if zero_cost:
        _fail(
            "cost",
            "estimate_cost returned $0.00 for: "
            + ", ".join(zero_cost)
            + " — add the exact model id to PRICING in app/ai/cost.py. A silent zero "
            "destroys the telemetry you would use to notice it.",
        )
        return 1
    _step("cost", "every call produced a non-zero estimate")

    print("-" * 72)
    print("ALL CHECKS PASSED — the Bedrock provider works against this account.")
    print()
    print("Record these in docs/tickets/B1-bedrock-provider-result.md (they are the")
    print("EMPIRICAL findings for tasks 4 and 5, currently marked PENDING):")
    for key, value in findings.items():
        print(f"  {key}: {value}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        return asyncio.run(_run(args))
    except KeyboardInterrupt:
        _fail("aborted", "interrupted")
        return 130


if __name__ == "__main__":
    sys.exit(main())
