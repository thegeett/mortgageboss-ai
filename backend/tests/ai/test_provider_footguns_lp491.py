"""LP-491 — two provider footguns found during LP-490a/LP-491, closed and pinned.

Both are the same shape: a failure that costs money or silently produces wrong answers, with NOTHING in
the output to say so. Neither was a logic bug — both were configuration reaching the wrong place.
"""

from __future__ import annotations

import os

import pytest
from app.ai.client import get_anthropic_client
from app.core.config import settings


def test_bedrock_client_is_given_the_configured_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    """⚠️ FOOTGUN 1 — a Bedrock call that fails CLOSED and looks like an abstention.

    The SDK resolves AWS credentials from the default chain, which reads AWS_PROFILE from the
    ENVIRONMENT — it does not know about `settings.aws_profile`. Until LP-491 only the bench engine
    exported it, so every other entry point (a script, a Celery task, a self-consistency harness) got
    "could not resolve credentials from session", the AI call failed, and the producer failed closed to
    `unknown` for every subject.

    That is invisible downstream: a broken pipeline and a confidently-abstaining one produce the same
    tags. It cost LP-490a four derivation runs that scored a PERFECT 1.0000 while calling nothing.

    ⚠️ The profile is passed as an ARGUMENT, never exported to os.environ — the first version of this fix
    did the latter and broke 22 tests, because a process-wide AWS_PROFILE leaks into every other boto3
    client (S3 storage included) and persists across tests.
    """
    monkeypatch.setattr(settings, "ai_provider", "bedrock")
    monkeypatch.setattr(settings, "aws_profile", "test-profile")
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    get_anthropic_client.cache_clear()
    try:
        client = get_anthropic_client()
        assert getattr(client, "aws_profile", None) == "test-profile"
        assert "AWS_PROFILE" not in os.environ, (
            "the profile must be scoped to the client, not exported process-wide"
        )
    finally:
        get_anthropic_client.cache_clear()


def test_the_suite_never_holds_a_real_anthropic_key() -> None:
    """⚠️ FOOTGUN 2 — a test that reaches a real reasoner bills the developer's own key.

    conftest pins `ai_provider="anthropic"` for determinism (a local .env must not change results), so
    a test that slips past its reasoner seam calls the DIRECT API. LP-490 shipped exactly that: a seam
    covering ONE ai group while every other group fell through to the live model — roughly 40-60 real
    calls, noticed only because one test file took 133 seconds.

    The autouse fixture now pins a dummy key alongside the provider, so a leak fails auth loudly instead
    of spending. If someone removes that pin, this fails.
    """
    key = settings.anthropic_api_key or ""
    assert key.startswith("sk-ant-test-"), (
        "the test suite is holding what looks like a REAL Anthropic key — a test that reaches a live "
        "reasoner would bill it. conftest's _pin_ai_provider must pin a dummy."
    )
