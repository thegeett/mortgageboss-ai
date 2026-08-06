"""B1 — provider selection, model resolution, startup validation, pacing, pricing.

Fully offline. The Bedrock client is constructed but never used to make a request, so
no AWS credentials are needed: ``AsyncAnthropicBedrock.__init__`` does not resolve
credentials (signing happens per request, in ``_prepare_request``).

What these DO prove: the provider switch selects the right class, the tier map
translates correctly, misconfiguration fails at boot, throttles classify as transient,
the limiter paces without sleeping in real time, and every configured model has a price.

What they do NOT prove: that Bedrock accepts the request shape, that the inference
profiles exist in the account, or that a real throttle looks the way ``_is_transient``
expects. Those are ``scripts/verify-bedrock.py``'s job (tasks 4/5 findings are marked
PENDING in the result doc until it runs).
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest
from anthropic import APIStatusError, AsyncAnthropic, AsyncAnthropicBedrock
from app.ai import client as client_module
from app.ai.client import (
    TRUNCATED_STOP_REASON,
    AIClientError,
    _is_transient,
    _normalize_stop_reason,
    get_anthropic_client,
)
from app.ai.cost import PRICING, estimate_cost
from app.ai.rate_limit import RateLimiter, get_rate_limiter, reset_rate_limiter
from app.core.config import (
    ModelResolutionError,
    Settings,
    resolve_model,
    resolve_requests_per_minute,
    settings,
)
from pydantic import ValidationError

HAIKU_PROFILE = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
SONNET_PROFILE = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"

_REQUEST = httpx.Request("POST", "https://api.anthropic.com/v1/messages")


@pytest.fixture(autouse=True)
def _reset_caches() -> Any:
    """The client factory and the limiter are process-wide caches; reset around each test."""
    get_anthropic_client.cache_clear()
    reset_rate_limiter()
    yield
    get_anthropic_client.cache_clear()
    reset_rate_limiter()


def _use_bedrock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ai_provider", "bedrock")
    monkeypatch.setattr(settings, "bedrock_model_classification", HAIKU_PROFILE)
    monkeypatch.setattr(settings, "bedrock_model_extraction", HAIKU_PROFILE)
    monkeypatch.setattr(settings, "bedrock_model_reasoning", SONNET_PROFILE)


# --------------------------------------------------------------------------- #
# Provider selection (task 9)
# --------------------------------------------------------------------------- #


def test_default_provider_is_anthropic() -> None:
    """The default must not change — acceptance criterion 1."""
    assert Settings.model_fields["ai_provider"].default == "anthropic"
    assert settings.ai_provider == "anthropic"


def test_anthropic_provider_constructs_the_direct_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ai_provider", "anthropic")
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-ant-test")
    assert isinstance(get_anthropic_client(), AsyncAnthropic)


def test_bedrock_provider_constructs_the_bedrock_client(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_bedrock(monkeypatch)
    assert isinstance(get_anthropic_client(), AsyncAnthropicBedrock)


def test_bedrock_client_needs_no_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bedrock authenticates through the AWS chain — a key must not be required."""
    _use_bedrock(monkeypatch)
    monkeypatch.setattr(settings, "anthropic_api_key", None)
    assert isinstance(get_anthropic_client(), AsyncAnthropicBedrock)


def test_anthropic_client_without_a_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ai_provider", "anthropic")
    monkeypatch.setattr(settings, "anthropic_api_key", None)
    with pytest.raises(AIClientError, match="ANTHROPIC_API_KEY"):
        get_anthropic_client()


def test_both_clients_share_the_same_transport() -> None:
    """Why the lru_cache is safe for both: identical httpx lifecycle (B1 finding)."""
    direct = AsyncAnthropic(api_key="sk-fake", max_retries=0)
    bedrock = AsyncAnthropicBedrock(aws_region="us-east-1", aws_access_key="x", aws_secret_key="y")
    assert type(direct._client) is type(bedrock._client)


# --------------------------------------------------------------------------- #
# Model resolution
# --------------------------------------------------------------------------- #


def test_resolve_model_is_identity_under_anthropic(monkeypatch: pytest.MonkeyPatch) -> None:
    """The default path must be byte-identical — acceptance criterion 1."""
    monkeypatch.setattr(settings, "ai_provider", "anthropic")
    for value in ("claude-haiku-4-5", "claude-sonnet-4-5", "anything-at-all"):
        assert resolve_model(value) == value


def test_resolve_model_maps_each_tier_under_bedrock(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_bedrock(monkeypatch)
    assert resolve_model(settings.anthropic_model_classification) == HAIKU_PROFILE
    assert resolve_model(settings.anthropic_model_extraction) == HAIKU_PROFILE
    assert resolve_model(settings.anthropic_model_reasoning) == SONNET_PROFILE


def test_reasoning_resolves_to_sonnet_not_haiku(monkeypatch: pytest.MonkeyPatch) -> None:
    """The 37 live rules are calibrated on Sonnet reasoning — this must never drift."""
    _use_bedrock(monkeypatch)
    resolved = resolve_model(settings.anthropic_model_reasoning)
    assert "sonnet" in resolved
    assert resolved != resolve_model(settings.anthropic_model_extraction)


def test_resolve_model_rejects_an_unknown_value_under_bedrock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A hard-coded model would otherwise be sent verbatim and rejected at invoke time."""
    _use_bedrock(monkeypatch)
    with pytest.raises(ModelResolutionError, match="no BEDROCK_MODEL_"):
        resolve_model("claude-opus-4-8")


# --------------------------------------------------------------------------- #
# Startup validation
# --------------------------------------------------------------------------- #


def _settings_kwargs(**overrides: Any) -> dict[str, Any]:
    base = settings.model_dump()
    base.update(overrides)
    return base


def test_bedrock_without_a_model_id_refuses_to_start() -> None:
    with pytest.raises(ValidationError, match="BEDROCK_MODEL_REASONING"):
        Settings(
            **_settings_kwargs(
                ai_provider="bedrock",
                bedrock_model_classification=HAIKU_PROFILE,
                bedrock_model_extraction=HAIKU_PROFILE,
                bedrock_model_reasoning=None,
            )
        )


def test_bedrock_reports_every_missing_model_id() -> None:
    with pytest.raises(ValidationError) as exc:
        Settings(
            **_settings_kwargs(
                ai_provider="bedrock",
                bedrock_model_classification=None,
                bedrock_model_extraction=None,
                bedrock_model_reasoning=None,
            )
        )
    message = str(exc.value)
    for name in (
        "BEDROCK_MODEL_CLASSIFICATION",
        "BEDROCK_MODEL_EXTRACTION",
        "BEDROCK_MODEL_REASONING",
    ):
        assert name in message


def test_bedrock_starts_with_no_anthropic_api_key() -> None:
    """The whole point of the conditional key — no dummy-value workaround."""
    cfg = Settings(
        **_settings_kwargs(
            ai_provider="bedrock",
            anthropic_api_key=None,
            bedrock_model_classification=HAIKU_PROFILE,
            bedrock_model_extraction=HAIKU_PROFILE,
            bedrock_model_reasoning=SONNET_PROFILE,
        )
    )
    assert cfg.anthropic_api_key is None


def test_anthropic_without_a_key_refuses_to_start() -> None:
    with pytest.raises(ValidationError, match="ANTHROPIC_API_KEY is required"):
        Settings(**_settings_kwargs(ai_provider="anthropic", anthropic_api_key=None))


def test_blank_api_key_counts_as_unset() -> None:
    with pytest.raises(ValidationError, match="ANTHROPIC_API_KEY is required"):
        Settings(**_settings_kwargs(ai_provider="anthropic", anthropic_api_key="   "))


def test_ambiguous_tier_mapping_is_refused() -> None:
    """Two tiers sharing one Anthropic value but different Bedrock ids cannot resolve."""
    with pytest.raises(ValidationError, match="ambiguous Bedrock model mapping"):
        Settings(
            **_settings_kwargs(
                ai_provider="bedrock",
                anthropic_model_classification="claude-haiku-4-5",
                anthropic_model_extraction="claude-haiku-4-5",  # same value...
                bedrock_model_classification=HAIKU_PROFILE,
                bedrock_model_extraction=SONNET_PROFILE,  # ...different ids
                bedrock_model_reasoning=SONNET_PROFILE,
            )
        )


def test_no_aws_credential_settings_exist() -> None:
    fields = set(Settings.model_fields)
    for forbidden in (
        "aws_access_key_id",
        "aws_secret_access_key",
        "bedrock_access_key",
        "bedrock_secret_key",
        "aws_session_token",
    ):
        assert forbidden not in fields


# --------------------------------------------------------------------------- #
# Retry classification (task 4 — the throttle hazard)
# --------------------------------------------------------------------------- #


def _status_error(cls: type, status: int, body: object = None) -> Exception:
    return cls("boom", response=httpx.Response(status, request=_REQUEST), body=body)


def test_bedrock_throttling_exception_is_transient() -> None:
    """At 10 RPM a misclassified throttle fails the common path, not an edge case."""

    class ThrottlingException(Exception):
        pass

    assert _is_transient(ThrottlingException("Rate exceeded")) is True


def test_bedrock_throttle_as_a_non_429_status_error_is_still_transient() -> None:
    """Belt-and-braces: correct even if the SDK surfaces a throttle as a 400."""
    exc = _status_error(APIStatusError, 400, {"message": "ThrottlingException: rate exceeded"})
    assert _is_transient(exc) is True


def test_model_not_ready_and_service_unavailable_are_transient() -> None:
    for name in ("ModelNotReadyException", "ServiceUnavailableException"):
        assert _is_transient(type(name, (Exception,), {})("capacity")) is True


def test_timeout_is_transient() -> None:
    """complete() bounds each attempt; a timeout is network-class and must retry."""
    assert _is_transient(TimeoutError("timed out")) is True


def test_genuine_client_errors_still_fail_fast() -> None:
    """The 4xx-fails-fast rule must not be weakened by the throttle addition."""
    for status in (400, 401, 403, 404, 422):
        assert _is_transient(_status_error(APIStatusError, status)) is False
    assert _is_transient(ValueError("bad input")) is False


def test_429_and_5xx_remain_transient() -> None:
    assert _is_transient(_status_error(APIStatusError, 429)) is True
    assert _is_transient(_status_error(APIStatusError, 503)) is True


# --------------------------------------------------------------------------- #
# stop_reason normalisation (task 5)
# --------------------------------------------------------------------------- #


def test_canonical_stop_reason_passes_through() -> None:
    assert _normalize_stop_reason(TRUNCATED_STOP_REASON) == "max_tokens"
    assert _normalize_stop_reason("end_turn") == "end_turn"
    assert _normalize_stop_reason(None) is None


def test_model_call_compares_against_the_shared_constant() -> None:
    """The truncation guard must not carry its own literal (it would drift silently)."""
    from app.ai.extraction import model_call

    source = (model_call.__file__ or "").replace(".pyc", ".py")
    with open(source, encoding="utf-8") as fh:
        lines = fh.readlines()

    # CODE lines only — the module docstring legitimately quotes the literal while
    # explaining the LP-102 bug, and matching prose would make this test unfixable.
    comparisons = [
        line.strip()
        for line in lines
        if "stop_reason" in line and ("==" in line or "!=" in line) and "if " in line
    ]
    assert comparisons, "no stop_reason comparison found — did the guard move?"
    for line in comparisons:
        assert "TRUNCATED_STOP_REASON" in line, f"literal comparison would drift: {line}"


# --------------------------------------------------------------------------- #
# Rate limiting (task 4b) — injected clock, never a real sleep
# --------------------------------------------------------------------------- #


class FakeClock:
    """A monotonic clock that only advances when the limiter 'sleeps'."""

    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


async def test_unlimited_limiter_never_waits() -> None:
    clock = FakeClock()
    limiter = RateLimiter(None, clock=clock, sleep=clock.sleep)
    for _ in range(50):
        assert await limiter.acquire() == 0.0
    assert clock.slept == []


async def test_zero_or_negative_rpm_is_unlimited() -> None:
    for rpm in (0, -1):
        clock = FakeClock()
        limiter = RateLimiter(rpm, clock=clock, sleep=clock.sleep)
        assert await limiter.acquire() == 0.0


async def test_limiter_paces_at_the_configured_rate() -> None:
    """8 RPM => 7.5s spacing. First call free, each subsequent one waits."""
    clock = FakeClock()
    limiter = RateLimiter(8, clock=clock, sleep=clock.sleep)
    assert limiter.interval_seconds == pytest.approx(7.5)

    assert await limiter.acquire() == 0.0  # first is immediate
    assert await limiter.acquire() == pytest.approx(7.5)
    assert await limiter.acquire() == pytest.approx(7.5)
    assert clock.slept == [pytest.approx(7.5), pytest.approx(7.5)]


async def test_limiter_does_not_wait_when_enough_time_has_passed() -> None:
    clock = FakeClock()
    limiter = RateLimiter(60, clock=clock, sleep=clock.sleep)  # 1s spacing
    await limiter.acquire()
    clock.now += 10.0  # a long gap
    assert await limiter.acquire() == 0.0


async def test_limiter_is_safe_under_concurrency() -> None:
    """Concurrent callers each claim their own slot, one interval apart.

    There is no lock (see ``RateLimiter.acquire``): each caller claims its slot in a
    critical section with no await in it, then sleeps. What matters is the resulting
    SCHEDULE — four calls at 10s spacing start at t=0/10/20/30 — which is exactly what a
    per-minute server-side quota measures.
    """
    clock = FakeClock()
    limiter = RateLimiter(6, clock=clock, sleep=clock.sleep)  # 10s spacing
    waits = await asyncio.gather(*(limiter.acquire() for _ in range(4)))

    assert waits[0] == 0.0  # the first call is never delayed
    assert all(w == pytest.approx(10.0) for w in waits[1:])
    assert clock.now == pytest.approx(30.0)  # 4th call starts at t=30, i.e. 6 RPM


def test_limiter_survives_a_fresh_event_loop_per_task() -> None:
    """The Celery shape: ONE process-wide limiter used from many short-lived loops.

    ``run_async`` is ``asyncio.run`` (``app/tasks/base.py:41-43``), so every Celery task
    gets a brand-new event loop while the limiter singleton persists. An ``asyncio.Lock``
    on the limiter bound itself to the FIRST loop that contended for it and then raised
    ``RuntimeError: ... is bound to a different event loop`` on every later task — and
    contention is guaranteed, since the rule engine gathers up to 8 concurrent judgments.

    Deliberately NOT using the fake clock: this must exercise real ``asyncio`` primitives
    across real loops, which is precisely what the fake sleep would hide.
    """
    limiter = RateLimiter(60_000)  # 1ms spacing — real, but too small to slow the suite

    async def burst() -> None:
        await asyncio.gather(*(limiter.acquire() for _ in range(4)))

    for _ in range(3):
        asyncio.run(burst())  # a fresh loop each time, exactly like a new Celery task


async def test_limiter_failure_surfaces_as_ai_client_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A limiter error must not escape ``complete()`` raw.

    ``rule_engine/judgment.py`` catches only ``AIClientError`` in order to fail ONE subject
    closed. Anything else slips past that handler and aborts the entire verification run,
    so pacing must obey the same contract as every other failure inside ``complete()``.
    """

    class _Exploding:
        async def acquire(self, *, label: str = "ai_call") -> float:
            raise RuntimeError("is bound to a different event loop")

    monkeypatch.setattr(client_module, "get_rate_limiter", lambda: _Exploding())
    monkeypatch.setattr(client_module.settings, "ai_max_retries", 1)

    with pytest.raises(AIClientError):
        await client_module.complete(
            model=settings.anthropic_model_reasoning,
            messages=[{"role": "user", "content": "x"}],
            max_tokens=16,
        )


def test_rpm_resolver_picks_the_active_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ai_requests_per_minute_anthropic", 100)
    monkeypatch.setattr(settings, "ai_requests_per_minute_bedrock", 8)

    monkeypatch.setattr(settings, "ai_provider", "anthropic")
    assert resolve_requests_per_minute() == 100

    monkeypatch.setattr(settings, "ai_provider", "bedrock")
    assert resolve_requests_per_minute() == 8


def test_rpm_defaults_to_unlimited() -> None:
    assert Settings.model_fields["ai_requests_per_minute_anthropic"].default is None
    assert Settings.model_fields["ai_requests_per_minute_bedrock"].default is None


def test_limiter_is_rebuilt_when_the_resolved_rpm_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A provider flip must not keep pacing at the other provider's ceiling."""
    monkeypatch.setattr(settings, "ai_provider", "anthropic")
    monkeypatch.setattr(settings, "ai_requests_per_minute_anthropic", None)
    assert get_rate_limiter().interval_seconds == 0.0

    monkeypatch.setattr(settings, "ai_provider", "bedrock")
    monkeypatch.setattr(settings, "ai_requests_per_minute_bedrock", 8)
    assert get_rate_limiter().interval_seconds == pytest.approx(7.5)


# --------------------------------------------------------------------------- #
# Pricing coverage (task 6.3) — a silent $0 destroys the telemetry that finds it
# --------------------------------------------------------------------------- #


def test_every_configured_model_has_a_price() -> None:
    """Both triplets. A missing key prices the call at $0.00 with only a warning."""
    configured = [
        settings.anthropic_model_classification,
        settings.anthropic_model_extraction,
        settings.anthropic_model_reasoning,
        HAIKU_PROFILE,
        SONNET_PROFILE,
    ]
    missing = [m for m in configured if m not in PRICING]
    assert not missing, f"models with no PRICING entry (would cost $0.00): {missing}"


def test_configured_models_produce_a_non_zero_estimate() -> None:
    """Acceptance criterion 3: a real call must record a non-zero cost_estimate."""
    for model in (HAIKU_PROFILE, SONNET_PROFILE, settings.anthropic_model_extraction):
        cost = estimate_cost(model=model, input_tokens=1000, output_tokens=1000)
        assert cost > 0.0, f"{model} estimated at $0.00"


def test_bedrock_and_direct_rates_match_per_tier() -> None:
    """The ticket's premise: same per-token rates on both providers."""
    assert PRICING[HAIKU_PROFILE] == PRICING["claude-haiku-4-5"]
    assert PRICING[SONNET_PROFILE] == PRICING["claude-sonnet-4-5"]


def test_unknown_model_still_returns_zero_and_warns() -> None:
    assert estimate_cost(model="nonexistent", input_tokens=1000, output_tokens=1000) == 0.0


# --------------------------------------------------------------------------- #
# complete() wiring — the pieces above, joined up
# --------------------------------------------------------------------------- #


class _FakeMessages:
    """Streaming seam for ``complete`` — records the kwargs of each ``stream(...)`` call (so tests can
    assert the model sent on the wire) and returns a fixed final Message via ``get_final_message()``."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def stream(self, **kwargs: Any) -> Any:
        from types import SimpleNamespace

        self.calls.append(kwargs)

        class _Stream:
            async def __aenter__(self) -> Any:
                return self

            async def __aexit__(self, *exc: object) -> bool:
                return False

            async def get_final_message(self) -> Any:
                return SimpleNamespace(
                    content=[SimpleNamespace(type="text", text="ok")],
                    usage=SimpleNamespace(input_tokens=10, output_tokens=5),
                    stop_reason="end_turn",
                )

        return _Stream()


async def test_complete_sends_the_resolved_bedrock_id(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    _use_bedrock(monkeypatch)
    fake = _FakeMessages()
    monkeypatch.setattr(
        client_module, "get_anthropic_client", lambda: SimpleNamespace(messages=fake)
    )

    result = await client_module.complete(
        model=settings.anthropic_model_extraction,
        messages=[{"role": "user", "content": "x"}],
        max_tokens=16,
    )
    assert fake.calls[0]["model"] == HAIKU_PROFILE  # translated on the wire
    assert result.model == HAIKU_PROFILE  # and reported as what ran


async def test_complete_passes_the_model_through_under_anthropic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    monkeypatch.setattr(settings, "ai_provider", "anthropic")
    fake = _FakeMessages()
    monkeypatch.setattr(
        client_module, "get_anthropic_client", lambda: SimpleNamespace(messages=fake)
    )

    result = await client_module.complete(
        model="claude-haiku-4-5", messages=[{"role": "user", "content": "x"}], max_tokens=16
    )
    assert fake.calls[0]["model"] == "claude-haiku-4-5"
    assert result.model == "claude-haiku-4-5"


async def test_complete_wraps_an_unmappable_model(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_bedrock(monkeypatch)
    with pytest.raises(AIClientError, match="no BEDROCK_MODEL_"):
        await client_module.complete(
            model="claude-opus-4-8", messages=[{"role": "user", "content": "x"}], max_tokens=16
        )
