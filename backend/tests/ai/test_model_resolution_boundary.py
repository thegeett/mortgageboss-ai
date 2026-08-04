"""The provider-resolution boundary guard (bedrock_integration merge / B1).

`resolve_model()` is the ONLY correct way to turn a caller's tier value into the ACTIVE provider's model id:
under `ai_provider="anthropic"` it is the identity; under `"bedrock"` it maps the tier value to a Bedrock id.
A caller that reaches the Anthropic/Bedrock SDK WITHOUT going through it would send a raw tier string — fine on
the direct API, but rejected at invoke time on Bedrock: the SAME silent-failure class as the LP-457 hard-coded
model (the wrong model, or a crash, only on the provider you don't test locally).

So the SDK is invoked at EXACTLY one boundary — `app/ai/client.py` — which constructs the SDK client and calls
`resolve_model()` before `messages.create`. This guard fails CI if any other `app/` module calls the SDK
directly or constructs an SDK client, and if the boundary ever stops resolving.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.core.config import resolve_model, settings

_APP = Path(__file__).resolve().parents[2] / "app"
_BOUNDARY = "ai/client.py"  # the ONE file allowed to touch the SDK

# The SDK invocation surface: a messages.create/.stream call, or constructing an SDK client.
_SDK_CALL = re.compile(r"\.messages\.(?:create|stream)\b")
_SDK_CTOR = re.compile(r"\bAsyncAnthropic(?:Bedrock)?\s*\(")


def test_sdk_is_invoked_only_at_the_client_boundary() -> None:
    offenders: list[str] = []
    for path in _APP.rglob("*.py"):
        rel = path.relative_to(_APP).as_posix()
        if rel == _BOUNDARY:
            continue
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if _SDK_CALL.search(line) or _SDK_CTOR.search(line):
                offenders.append(f"{rel}:{i}: {line.strip()}")
    assert not offenders, (
        "the Anthropic/Bedrock SDK is invoked outside app/ai/client.py — every model must reach the SDK via "
        "resolve_model() at the one boundary, else a raw tier value is sent verbatim (rejected on Bedrock):\n  "
        + "\n  ".join(offenders)
    )


def test_the_boundary_resolves_the_model_before_the_sdk_call() -> None:
    # client.py must call resolve_model() — the boundary that maps a tier value to the active provider's id.
    src = (_APP / _BOUNDARY).read_text(encoding="utf-8")
    assert "resolve_model(" in src, "client.py must resolve the model before the SDK call"


def test_resolve_model_returns_anthropic_ids_in_this_worktree() -> None:
    # This worktree stays on the direct Anthropic API (ai_provider defaults to "anthropic"). An accidental flip
    # to "bedrock" is the least-visible failure here — the wrong model, working fine, on the wrong provider.
    assert settings.ai_provider == "anthropic"
    for tier in ("classification", "extraction", "reasoning", "analysis"):
        value = getattr(settings, f"anthropic_model_{tier}")
        assert (
            resolve_model(value) == value
        )  # identity under anthropic — an Anthropic id, not a Bedrock one
        assert value.startswith(
            "claude-"
        )  # an Anthropic model id, never a Bedrock ARN/inference-profile id
