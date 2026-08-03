"""Tests for the S3 storage backend (C0) — fully STUBBED, no network.

**Why a stub and not moto.** The repo's established pattern for an external SDK is to
replace the client with a fake and assert on the wrapper's own policy — see
``tests/ai/test_client.py:70-73``, which swaps the Anthropic singleton for a
``SimpleNamespace`` whose ``messages.create`` is an ``AsyncMock``. There is no moto,
LocalStack, or testcontainers anywhere in this suite, and moto's aiobotocore support
is a separate, historically fragile integration. A stub keeps the suite dependency-free
and offline, which is the property CI actually relies on.

**What that costs, stated plainly:** these tests prove the backend's *contract* — key
shape, encryption arguments, the StorageError mapping, delete idempotency — but they do
NOT prove the calls are shaped the way real S3 accepts, nor that IAM, SSE, or presigning
work. That is exactly what ``scripts/verify-s3.py`` exists to prove, against a real
bucket, before Fargate depends on this.

The parity test against ``LocalStorageBackend`` is the one that matters most: existing
DB rows hold local-format keys, so an S3 backend that derived keys differently would
orphan every stored document.
"""

from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from app.core.config import Settings, settings
from app.storage import get_storage_backend
from app.storage.base import StorageError
from app.storage.local import LocalStorageBackend
from app.storage.s3 import S3StorageBackend
from botocore.exceptions import ClientError
from pydantic import ValidationError

# The same stable UUIDs test_local_storage.py uses, so the parity assertion below
# compares like with like.
COMPANY_ID = UUID("11111111-1111-1111-1111-111111111111")
FILE_ID = UUID("22222222-2222-2222-2222-222222222222")
DOCUMENT_ID = UUID("33333333-3333-3333-3333-333333333333")

BUCKET = "mbai-documents-test"


# --------------------------------------------------------------------------- #
# The stub: an in-memory S3 that mimics the aioboto3 client surface we use
# --------------------------------------------------------------------------- #


def _client_error(code: str, operation: str) -> ClientError:
    """A real botocore ClientError, so the mapping is tested against the true type."""
    return ClientError({"Error": {"Code": code, "Message": "stub"}}, operation)


class _Body:
    """Stands in for the streaming body on a GetObject response."""

    def __init__(self, data: bytes) -> None:
        self._data = data

    async def read(self) -> bytes:
        return self._data


class FakeS3Client:
    """In-memory S3. Records every put so encryption args can be asserted."""

    def __init__(self, store: dict[str, dict[str, Any]]) -> None:
        self.store = store
        self.deleted: list[str] = []
        self.presign_calls: list[dict[str, Any]] = []

    async def __aenter__(self) -> "FakeS3Client":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        return None

    async def put_object(self, **kwargs: Any) -> dict[str, Any]:
        self.store[kwargs["Key"]] = dict(kwargs)
        return {}

    async def get_object(self, **kwargs: Any) -> dict[str, Any]:
        obj = self.store.get(kwargs["Key"])
        if obj is None:
            raise _client_error("NoSuchKey", "GetObject")
        return {"Body": _Body(obj["Body"])}

    async def delete_object(self, **kwargs: Any) -> dict[str, Any]:
        # Real S3 succeeds on an absent key; the stub must too, or the idempotency
        # test would pass for the wrong reason.
        self.deleted.append(kwargs["Key"])
        self.store.pop(kwargs["Key"], None)
        return {}

    async def generate_presigned_url(
        self, operation: str, *, Params: dict[str, Any], ExpiresIn: int
    ) -> str:
        self.presign_calls.append({"op": operation, "params": Params, "expires": ExpiresIn})
        return (
            f"https://{Params['Bucket']}.s3.amazonaws.com/{Params['Key']}"
            f"?X-Amz-Expires={ExpiresIn}&X-Amz-Signature=stub"
        )


class FakeSession:
    """Stands in for ``aioboto3.Session`` — hands out one shared FakeS3Client."""

    def __init__(self, client: FakeS3Client) -> None:
        self._client = client
        self.client_kwargs: list[dict[str, Any]] = []

    def client(self, service: str, **kwargs: Any) -> FakeS3Client:
        assert service == "s3"
        self.client_kwargs.append(kwargs)
        return self._client


def make_backend(**overrides: Any) -> tuple[S3StorageBackend, FakeS3Client, FakeSession]:
    """An S3StorageBackend wired to the in-memory stub."""
    kwargs: dict[str, Any] = {"bucket": BUCKET, "region": "us-east-1"}
    kwargs.update(overrides)
    backend = S3StorageBackend(**kwargs)
    fake_client = FakeS3Client({})
    fake_session = FakeSession(fake_client)
    backend._session = fake_session  # type: ignore[assignment]
    return backend, fake_client, fake_session


@pytest.fixture
def backend() -> S3StorageBackend:
    return make_backend()[0]


# --------------------------------------------------------------------------- #
# Key parity with the local backend — the property existing DB rows depend on
# --------------------------------------------------------------------------- #


async def test_save_returns_same_key_as_local_backend_for_identical_inputs(
    tmp_path: Path,
) -> None:
    """S3 and local MUST derive byte-identical keys — stored rows hold local-format keys."""
    s3_backend, _client, _session = make_backend()
    local_backend = LocalStorageBackend(tmp_path / "storage")

    args: dict[str, Any] = {
        "company_id": COMPANY_ID,
        "file_id": FILE_ID,
        "document_id": DOCUMENT_ID,
        "filename": "paystub.pdf",
        "content": b"%PDF-1.7 fake",
    }
    s3_key = await s3_backend.save(**args)
    local_key = await local_backend.save(**args)

    assert s3_key == local_key
    assert s3_key == f"{COMPANY_ID}/{FILE_ID}/{DOCUMENT_ID}.pdf"


async def test_save_applies_the_shared_extension_sanitization(backend: S3StorageBackend) -> None:
    """A junk extension falls back to the allowlist default, exactly as in base.py."""
    key = await backend.save(
        company_id=COMPANY_ID,
        file_id=FILE_ID,
        document_id=DOCUMENT_ID,
        filename="payload.exe",
        content=b"x",
    )
    assert key == f"{COMPANY_ID}/{FILE_ID}/{DOCUMENT_ID}.bin"


# --------------------------------------------------------------------------- #
# Encryption
# --------------------------------------------------------------------------- #


async def test_save_uses_sse_s3_when_no_kms_key_configured() -> None:
    backend, client, _ = make_backend()
    key = await backend.save(
        company_id=COMPANY_ID,
        file_id=FILE_ID,
        document_id=DOCUMENT_ID,
        filename="a.pdf",
        content=b"x",
    )
    put = client.store[key]
    assert put["ServerSideEncryption"] == "AES256"
    assert "SSEKMSKeyId" not in put


async def test_save_uses_sse_kms_when_a_key_is_configured() -> None:
    key_arn = "arn:aws:kms:us-east-1:123456789012:key/abcd-1234"
    backend, client, _ = make_backend(kms_key_id=key_arn)
    key = await backend.save(
        company_id=COMPANY_ID,
        file_id=FILE_ID,
        document_id=DOCUMENT_ID,
        filename="a.pdf",
        content=b"x",
    )
    put = client.store[key]
    assert put["ServerSideEncryption"] == "aws:kms"
    assert put["SSEKMSKeyId"] == key_arn


async def test_save_never_writes_an_unencrypted_object() -> None:
    """There is no code path that omits ServerSideEncryption."""
    for overrides in ({}, {"kms_key_id": "arn:aws:kms:eu-west-1:1:key/x"}):
        backend, client, _ = make_backend(**overrides)
        key = await backend.save(
            company_id=COMPANY_ID,
            file_id=FILE_ID,
            document_id=DOCUMENT_ID,
            filename="a.pdf",
            content=b"x",
        )
        assert "ServerSideEncryption" in client.store[key]


async def test_save_sets_content_type_from_the_extension() -> None:
    backend, client, _ = make_backend()
    for filename, expected in (
        ("scan.pdf", "application/pdf"),
        ("scan.png", "image/png"),
        ("scan.jpeg", "image/jpeg"),
        ("weird.exe", "application/octet-stream"),  # → .bin fallback
    ):
        key = await backend.save(
            company_id=COMPANY_ID,
            file_id=FILE_ID,
            document_id=DOCUMENT_ID,
            filename=filename,
            content=b"x",
        )
        assert client.store[key]["ContentType"] == expected


# --------------------------------------------------------------------------- #
# read
# --------------------------------------------------------------------------- #


async def test_save_then_read_round_trips_exact_bytes(backend: S3StorageBackend) -> None:
    content = b"%PDF-1.7\n...binary paystub bytes...\x00\xff"
    key = await backend.save(
        company_id=COMPANY_ID,
        file_id=FILE_ID,
        document_id=DOCUMENT_ID,
        filename="paystub.pdf",
        content=content,
    )
    assert await backend.read(key) == content


async def test_read_missing_key_raises_storage_error_not_botocore(
    backend: S3StorageBackend,
) -> None:
    """The critical mapping: callers catch StorageError, so botocore must never escape."""
    with pytest.raises(StorageError, match="No stored file"):
        await backend.read(f"{COMPANY_ID}/{FILE_ID}/{DOCUMENT_ID}.pdf")


async def test_read_missing_key_does_not_raise_client_error(backend: S3StorageBackend) -> None:
    """Explicitly assert the negative — a ClientError leaking breaks pipeline handling."""
    with pytest.raises(Exception) as exc_info:
        await backend.read("nope/nope/nope.pdf")
    assert not isinstance(exc_info.value, ClientError)
    assert isinstance(exc_info.value, StorageError)


async def test_read_non_missing_client_error_also_becomes_storage_error() -> None:
    """AccessDenied (an IAM problem, not an absent object) must not escape either."""
    backend, client, _ = make_backend()

    async def _boom(**_kwargs: Any) -> dict[str, Any]:
        raise _client_error("AccessDenied", "GetObject")

    client.get_object = _boom  # type: ignore[method-assign]
    with pytest.raises(StorageError, match="Failed to read"):
        await backend.read("a/b/c.pdf")


# --------------------------------------------------------------------------- #
# delete — idempotent, matching local.py's unlink(missing_ok=True)
# --------------------------------------------------------------------------- #


async def test_delete_removes_the_object(backend: S3StorageBackend) -> None:
    key = await backend.save(
        company_id=COMPANY_ID,
        file_id=FILE_ID,
        document_id=DOCUMENT_ID,
        filename="a.pdf",
        content=b"x",
    )
    await backend.delete(key)
    with pytest.raises(StorageError):
        await backend.read(key)


async def test_delete_is_idempotent_on_a_missing_key(backend: S3StorageBackend) -> None:
    key = f"{COMPANY_ID}/{FILE_ID}/{DOCUMENT_ID}.pdf"
    await backend.delete(key)
    await backend.delete(key)  # second delete must not raise


async def test_delete_swallows_a_missing_object_error_from_s3() -> None:
    """Some S3-compatible stores raise instead of succeeding; still idempotent."""
    backend, client, _ = make_backend()

    async def _missing(**_kwargs: Any) -> dict[str, Any]:
        raise _client_error("NoSuchKey", "DeleteObject")

    client.delete_object = _missing  # type: ignore[method-assign]
    await backend.delete("a/b/c.pdf")  # must not raise


async def test_delete_surfaces_a_real_failure() -> None:
    backend, client, _ = make_backend()

    async def _denied(**_kwargs: Any) -> dict[str, Any]:
        raise _client_error("AccessDenied", "DeleteObject")

    client.delete_object = _denied  # type: ignore[method-assign]
    with pytest.raises(StorageError, match="Failed to delete"):
        await backend.delete("a/b/c.pdf")


# --------------------------------------------------------------------------- #
# get_url — the one capability gain over local
# --------------------------------------------------------------------------- #


async def test_get_url_returns_presigned_url_with_bucket_and_expiry() -> None:
    backend, _client, _session = make_backend(presign_expiry=900)
    key = f"{COMPANY_ID}/{FILE_ID}/{DOCUMENT_ID}.pdf"
    url = await backend.get_url(key)

    assert url is not None
    assert BUCKET in url
    assert "X-Amz-Expires=900" in url
    assert key in url


async def test_get_url_uses_the_configured_expiry() -> None:
    backend, client, _ = make_backend(presign_expiry=60)
    await backend.get_url("a/b/c.pdf")
    assert client.presign_calls[0]["expires"] == 60
    assert client.presign_calls[0]["op"] == "get_object"


async def test_get_url_differs_from_local_which_returns_none(tmp_path: Path) -> None:
    """Documents the behavioural difference C0 introduces."""
    local = LocalStorageBackend(tmp_path / "storage")
    assert await local.get_url("a/b/c.pdf") is None
    s3_backend, _c, _s = make_backend()
    assert await s3_backend.get_url("a/b/c.pdf") is not None


# --------------------------------------------------------------------------- #
# Client lifecycle
# --------------------------------------------------------------------------- #


async def test_client_is_opened_per_operation_not_held() -> None:
    """The loop-safety property: each operation opens its own client (see s3.py)."""
    backend, _client, session = make_backend()
    key = await backend.save(
        company_id=COMPANY_ID,
        file_id=FILE_ID,
        document_id=DOCUMENT_ID,
        filename="a.pdf",
        content=b"x",
    )
    await backend.read(key)
    await backend.delete(key)
    assert len(session.client_kwargs) == 3


async def test_client_is_built_with_the_configured_region_and_endpoint() -> None:
    backend, _client, session = make_backend(
        region="eu-west-2", endpoint_url="http://localhost:9000"
    )
    await backend.get_url("a/b/c.pdf")
    assert session.client_kwargs[0]["region_name"] == "eu-west-2"
    assert session.client_kwargs[0]["endpoint_url"] == "http://localhost:9000"


def test_backend_refuses_an_empty_bucket() -> None:
    with pytest.raises(ValueError, match="requires a bucket"):
        S3StorageBackend(bucket="")


# --------------------------------------------------------------------------- #
# Factory
# --------------------------------------------------------------------------- #


@pytest.fixture
def _clear_factory_cache() -> Any:
    get_storage_backend.cache_clear()
    yield
    get_storage_backend.cache_clear()


@pytest.mark.usefixtures("_clear_factory_cache")
def test_factory_returns_s3_backend_when_configured_s3(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "storage_backend", "s3")
    monkeypatch.setattr(settings, "s3_bucket", BUCKET)
    assert isinstance(get_storage_backend(), S3StorageBackend)


@pytest.mark.usefixtures("_clear_factory_cache")
def test_factory_still_returns_local_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """The default path must be completely unaffected by C0."""
    monkeypatch.setattr(settings, "storage_backend", "local")
    assert isinstance(get_storage_backend(), LocalStorageBackend)


# --------------------------------------------------------------------------- #
# Startup validation — the A2 §10 item-14 gap this ticket closes
# --------------------------------------------------------------------------- #


def _settings_kwargs(**overrides: Any) -> dict[str, Any]:
    """A complete, valid Settings payload with the required fields filled in."""
    base = settings.model_dump()
    base.update(overrides)
    return base


def test_settings_reject_s3_backend_without_a_bucket() -> None:
    """Misconfiguration must fail at STARTUP, not at the first document read."""
    with pytest.raises(ValidationError, match="S3_BUCKET is required"):
        Settings(**_settings_kwargs(storage_backend="s3", s3_bucket=None))


def test_settings_reject_s3_backend_with_a_blank_bucket() -> None:
    """A present-but-empty S3_BUCKET= line is still 'unset'."""
    with pytest.raises(ValidationError, match="S3_BUCKET is required"):
        Settings(**_settings_kwargs(storage_backend="s3", s3_bucket="   "))


def test_settings_accept_s3_backend_with_a_bucket() -> None:
    cfg = Settings(**_settings_kwargs(storage_backend="s3", s3_bucket=BUCKET))
    assert cfg.s3_bucket == BUCKET


def test_settings_accept_local_backend_without_a_bucket() -> None:
    """The default configuration must remain valid — no new required setting."""
    cfg = Settings(**_settings_kwargs(storage_backend="local", s3_bucket=None))
    assert cfg.storage_backend == "local"


def test_blank_optional_s3_strings_normalize_to_none() -> None:
    """A blank S3_ENDPOINT_URL= must mean 'unset', not an invalid empty endpoint."""
    cfg = Settings(**_settings_kwargs(s3_endpoint_url="", s3_kms_key_id="  "))
    assert cfg.s3_endpoint_url is None
    assert cfg.s3_kms_key_id is None


def test_no_aws_credential_settings_exist() -> None:
    """Credentials come from the provider chain; key settings are the anti-pattern."""
    fields = set(Settings.model_fields)
    for forbidden in (
        "aws_access_key_id",
        "aws_secret_access_key",
        "s3_access_key",
        "s3_secret_key",
        "aws_session_token",
    ):
        assert forbidden not in fields
