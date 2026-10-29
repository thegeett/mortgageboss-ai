"""LP-992 — `get_mail_storage()`: raw email files in the mail bucket (S3) or a local folder.

Same keys either way: `outbound/<id>.eml`, `inbound/<id>`. S3 is exercised through the in-memory
stub `test_s3_storage.py` uses (the repo has no moto), so the assertions are on the exact PutObject
the backend would send.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from app.core.config import Settings, settings
from app.storage import _mail_storage, get_mail_storage
from app.storage.base import StorageError
from app.storage.local import LocalStorageBackend
from app.storage.s3 import S3StorageBackend
from tests.storage.test_s3_storage import FakeS3Client, FakeSession

_EML = b"From: a@example.test\r\nTo: b@example.test\r\nSubject: LP-992\r\n\r\nHello.\r\n"


@pytest.fixture(autouse=True)
def _fresh_cache() -> Iterator[None]:
    """The helper is cached per configuration; a stubbed instance must not leak between tests."""
    _mail_storage.cache_clear()
    yield
    _mail_storage.cache_clear()


async def test_local_round_trip_under_storage_mail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "storage_backend", "local")
    monkeypatch.setattr(settings, "storage_local_path", str(tmp_path))

    store = get_mail_storage()
    assert isinstance(store, LocalStorageBackend)

    key = await store.save_at(storage_path="outbound/test.eml", content=_EML)
    assert key == "outbound/test.eml"
    # In the mail folder, not beside the documents.
    assert (tmp_path / "mail" / "outbound" / "test.eml").read_bytes() == _EML
    assert await store.read("outbound/test.eml") == _EML

    await store.delete("outbound/test.eml")
    with pytest.raises(StorageError):
        await store.read("outbound/test.eml")


@pytest.mark.parametrize("unset", [None, ""])
def test_s3_without_a_mail_bucket_is_refused(
    unset: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "storage_backend", "s3")
    monkeypatch.setattr(settings, "mail_bucket", unset)
    monkeypatch.setattr(settings, "mail_kms_key_id", "arn:aws:kms:us-east-1:1:key/mail")

    with pytest.raises(ValueError, match="MAIL_BUCKET is not set"):
        get_mail_storage()


def test_s3_without_the_mail_key_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """The documents key is not a fallback: it matches the mail bucket's only by coincidence."""
    monkeypatch.setattr(settings, "storage_backend", "s3")
    monkeypatch.setattr(settings, "mail_bucket", "mbai-mail-test")
    monkeypatch.setattr(settings, "s3_kms_key_id", "arn:aws:kms:us-east-1:1:key/documents")
    monkeypatch.setattr(settings, "mail_kms_key_id", None)

    with pytest.raises(ValueError, match="MAIL_KMS_KEY_ID is not set"):
        get_mail_storage()


def test_blank_mail_settings_read_as_unset() -> None:
    """`MAIL_BUCKET=` from .env.example is None, not "", so an `is None` check cannot pass "" on."""
    loaded = Settings(**(settings.model_dump() | {"mail_bucket": "  ", "mail_kms_key_id": ""}))
    assert (loaded.mail_bucket, loaded.mail_kms_key_id) == (None, None)


def test_the_local_backend_is_built_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Building it resolves and creates the root (blocking I/O); once per configuration, not per
    message. A changed setting still gets its own backend."""
    monkeypatch.setattr(settings, "storage_backend", "local")
    monkeypatch.setattr(settings, "storage_local_path", str(tmp_path / "a"))
    first = get_mail_storage()
    assert get_mail_storage() is first

    monkeypatch.setattr(settings, "storage_local_path", str(tmp_path / "b"))
    assert get_mail_storage() is not first
    assert (tmp_path / "b" / "mail").is_dir()


async def test_s3_writes_to_the_mail_bucket_with_the_kms_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "storage_backend", "s3")
    monkeypatch.setattr(settings, "s3_bucket", "mbai-documents-test")
    monkeypatch.setattr(settings, "mail_bucket", "mbai-mail-test")
    # Two different keys, so the assertion below shows which one is sent.
    monkeypatch.setattr(settings, "s3_kms_key_id", "arn:aws:kms:us-east-1:1:key/documents")
    monkeypatch.setattr(settings, "mail_kms_key_id", "arn:aws:kms:us-east-1:1:key/mail")

    store = get_mail_storage()
    assert isinstance(store, S3StorageBackend)
    client = FakeS3Client({})
    store._session = FakeSession(client)  # type: ignore[assignment]

    await store.save_at(storage_path="outbound/test.eml", content=_EML)

    put = client.store["outbound/test.eml"]
    # The mail bucket, not the documents bucket.
    assert put["Bucket"] == "mbai-mail-test"
    assert put["Body"] == _EML
    assert put["ContentType"] == "message/rfc822"
    assert (put["ServerSideEncryption"], put["SSEKMSKeyId"]) == (
        "aws:kms",
        "arn:aws:kms:us-east-1:1:key/mail",
    )
    assert await store.read("outbound/test.eml") == _EML
