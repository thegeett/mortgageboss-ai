"""S3 storage backend (C0) — object storage for document bytes.

The local backend (:mod:`app.storage.local`) relies on the host API and the
containerised Celery worker sharing a filesystem through a Docker bind mount. On
Fargate they are **separate tasks on separate hosts with no shared filesystem**,
so the worker's read at ``app/tasks/document_processing.py:115`` fails for every
document. This backend is the answer, and it is the hard prerequisite for
deployment.

Same contract as the local backend, so no calling code changes: paths come from
the shared :func:`app.storage.base.build_storage_path` (tenant-prefixed,
server-controlled UUIDs, sanitized extension — the security-relevant part lives
there and is NOT reimplemented here), a missing object raises
:class:`~app.storage.base.StorageError`, and ``delete`` is idempotent.

The one place this backend gains capability over local: :meth:`get_url` returns a
real presigned GET URL where local returns ``None``.

## Encryption

Every object is written encrypted at rest: **SSE-KMS** with ``s3_kms_key_id`` when
that setting is present, otherwise **SSE-S3** (``AES256``). There is no unencrypted
path — the ``ServerSideEncryption`` parameter is always sent.

## Error mapping — BOTH botocore exception families

Nothing from botocore escapes this module; every failure surfaces as
:class:`~app.storage.base.StorageError`. That takes two ``except`` clauses per
operation, because botocore's two error families are **siblings, not parent and
child** — ``ClientError`` and ``BotoCoreError`` each derive straight from
``Exception``, so catching one does not catch the other:

* ``ClientError`` — the service answered, with an error (``NoSuchKey``,
  ``AccessDenied``). It carries a code, so it can be classified; see ``_MISSING_CODES``.
* ``BotoCoreError`` — the call never got a usable answer: ``NoCredentialsError``,
  ``EndpointConnectionError``, ``ConnectTimeoutError``, ``ResponseStreamingError``
  (a reset mid-``Body.read()``). There is no code to classify, so these are never
  "missing" — always a hard failure.

The second family is not hypothetical; it is the Fargate day-one set: the task role
not yet attached, a NAT/VPC-endpoint hiccup.

## Client lifecycle — a SESSION on the instance, a CLIENT per operation

This is the deliberate choice, and the reasoning matters because the obvious
optimization is wrong here.

``aioboto3`` clients are built on ``aiohttp``, so **a client is bound to the event
loop that created it**. The Celery bridge runs **a fresh event loop per task** —
``run_async`` is literally ``asyncio.run(coro)`` (``app/tasks/base.py:41-43``). A
long-lived client cached on this instance would therefore be created in task N's
loop and reused in task N+1's *different, already-replaced* loop, raising
"Event loop is closed" / "attached to a different loop". The instance itself
survives across tasks because the factory is ``@lru_cache``d, which makes that
failure mode certain rather than unlikely.

The codebase already made exactly this call for the database:
``app/tasks/base.py:46-65`` builds a **fresh engine per task with NullPool**,
because "asyncpg connections are loop-bound". This backend follows that precedent
rather than inventing a second, contradictory answer.

So:

* The :class:`aioboto3.Session` is created once in ``__init__`` and held. A session
  is a credential/config resolver with **no sockets**, so it is both loop-agnostic
  and **fork-safe** — the standard boto3 guidance is to share a session and never
  share clients. That is what makes the ``@lru_cache`` on
  :func:`app.storage.get_storage_backend` safe under Celery prefork: each forked
  child lazily builds its own backend instance anyway, and even a shared one would
  carry no socket across the fork.
* A client is opened per operation via ``async with session.client(...)``.

**The cost, stated honestly:** a new client means a new connection pool, so an
operation pays a TLS handshake. On the worker this is not an amplification — the
pipeline performs exactly ONE storage read per document
(``document_processing.py:115``), so it is one handshake per task either way. On
the API (a single long-lived uvicorn loop) it *is* a real per-request cost, and
that is the case for revisiting this: a per-event-loop client cache would fix the
API path, but needs a close hook that ``asyncio.run`` does not provide without
leaking an unclosed ``aiohttp`` connector per task. Correctness first; see
``decisions.md`` ADR-357.
"""

from typing import Any
from uuid import UUID

import aioboto3
import structlog
from botocore.exceptions import BotoCoreError, ClientError

from app.storage.base import StorageBackend, StorageError, build_storage_path

logger = structlog.get_logger(__name__)

#: Extension → Content-Type stored on the object, so a presigned-URL download renders
#: in-browser instead of forcing a save. Keys mirror ``base.ALLOWED_EXTENSIONS``;
#: anything else (including the ``bin`` fallback) gets the generic binary type.
_CONTENT_TYPES: dict[str, str] = {
    "pdf": "application/pdf",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "tif": "image/tiff",
    "tiff": "image/tiff",
    "heic": "image/heic",
}
_DEFAULT_CONTENT_TYPE = "application/octet-stream"

#: Botocore error codes meaning "the object is not there". ``NoSuchKey`` comes from
#: GetObject; ``404`` / ``NotFound`` appear on HeadObject and on some S3-compatible
#: implementations. All map to StorageError, never a botocore exception.
#:
#: ``NoSuchBucket`` is deliberately NOT here. It is an object-scoped-looking code for a
#: deployment-scoped fault: a typo'd ``S3_BUCKET``, or a bucket in another account, makes
#: EVERY key report the same way a genuinely deleted document would — and would make
#: :meth:`S3StorageBackend.delete` return the idempotent "already gone" success having
#: deleted nothing. Treating it as missing turns one config error into an apparent
#: per-document data-loss story across the whole tenant, which is precisely what the
#: startup bucket validator exists to prevent. It falls through to the generic branch
#: and raises, loudly.
_MISSING_CODES = frozenset({"NoSuchKey", "404", "NotFound"})


def _content_type_for(storage_path: str) -> str:
    """The Content-Type for a storage key, from its (already sanitized) extension."""
    ext = storage_path.rsplit(".", 1)[-1].lower() if "." in storage_path else ""
    return _CONTENT_TYPES.get(ext, _DEFAULT_CONTENT_TYPE)


class S3StorageBackend(StorageBackend):
    """Store document bytes as S3 objects, keyed by the shared storage path."""

    def __init__(
        self,
        *,
        bucket: str,
        region: str = "us-east-1",
        endpoint_url: str | None = None,
        kms_key_id: str | None = None,
        presign_expiry: int = 900,
    ) -> None:
        if not bucket:
            # Defence in depth: the settings validator already refuses to start
            # without a bucket, but this class must not be constructible into a
            # state where every operation targets an empty bucket name.
            raise ValueError("S3StorageBackend requires a bucket name")
        self._bucket = bucket
        self._region = region
        self._endpoint_url = endpoint_url
        self._kms_key_id = kms_key_id
        self._presign_expiry = presign_expiry
        # Fork-safe and loop-agnostic (no sockets) — see the module docstring.
        self._session = aioboto3.Session()

    def _client(self) -> Any:
        """An async-context-manager client for one operation (see module docstring)."""
        return self._session.client("s3", region_name=self._region, endpoint_url=self._endpoint_url)

    def _encryption_args(self) -> dict[str, str]:
        """SSE-KMS when a key is configured, else SSE-S3. Never unencrypted."""
        if self._kms_key_id:
            return {"ServerSideEncryption": "aws:kms", "SSEKMSKeyId": self._kms_key_id}
        return {"ServerSideEncryption": "AES256"}

    async def save(
        self,
        *,
        company_id: UUID,
        file_id: UUID,
        document_id: UUID,
        filename: str,
        content: bytes,
    ) -> str:
        storage_path = build_storage_path(company_id, file_id, document_id, filename)
        try:
            async with self._client() as client:
                await client.put_object(
                    Bucket=self._bucket,
                    Key=storage_path,
                    Body=content,
                    ContentType=_content_type_for(storage_path),
                    **self._encryption_args(),
                )
        except ClientError as exc:
            # Metadata only — the key is server-controlled UUIDs, never document bytes.
            logger.warning("s3_save_failed", key=storage_path, error_code=_error_code(exc))
            raise StorageError(f"Failed to store object at {storage_path!r}") from exc
        except BotoCoreError as exc:
            logger.warning("s3_save_failed", key=storage_path, error_type=type(exc).__name__)
            raise StorageError(f"Failed to store object at {storage_path!r}") from exc
        return storage_path

    async def read(self, storage_path: str) -> bytes:
        try:
            async with self._client() as client:
                response = await client.get_object(Bucket=self._bucket, Key=storage_path)
                body: bytes = await response["Body"].read()
                return body
        except ClientError as exc:
            code = _error_code(exc)
            if code in _MISSING_CODES:
                # Same contract as local.py:65-73 — a missing object is a StorageError.
                raise StorageError(f"No stored file at {storage_path!r}") from exc
            logger.warning("s3_read_failed", key=storage_path, error_code=code)
            raise StorageError(f"Failed to read object at {storage_path!r}") from exc
        except BotoCoreError as exc:
            # Includes a stream reset during ``Body.read()`` above (ResponseStreamingError).
            logger.warning("s3_read_failed", key=storage_path, error_type=type(exc).__name__)
            raise StorageError(f"Failed to read object at {storage_path!r}") from exc

    async def delete(self, storage_path: str) -> None:
        # IDEMPOTENT, matching local.py's unlink(missing_ok=True): S3's DeleteObject
        # already succeeds on an absent key, so there is deliberately no existence
        # pre-check here — adding one would reintroduce the raise this contract forbids.
        try:
            async with self._client() as client:
                await client.delete_object(Bucket=self._bucket, Key=storage_path)
        except ClientError as exc:
            code = _error_code(exc)
            if code in _MISSING_CODES:
                return  # already gone — the idempotent outcome
            logger.warning("s3_delete_failed", key=storage_path, error_code=code)
            raise StorageError(f"Failed to delete object at {storage_path!r}") from exc
        except BotoCoreError as exc:
            # Never the idempotent "already gone" path: an unanswered call is no evidence
            # the object is absent, so reporting success here would be a silent no-op.
            logger.warning("s3_delete_failed", key=storage_path, error_type=type(exc).__name__)
            raise StorageError(f"Failed to delete object at {storage_path!r}") from exc

    async def get_url(self, storage_path: str) -> str | None:
        """A presigned GET URL valid for ``presign_expiry`` seconds.

        The one method that gains real capability over the local backend (which
        returns ``None``). Presigning is a local signing operation — no network call
        — so a failure here is a signing/credential problem, not a missing object;
        it does NOT prove the object exists.
        """
        try:
            async with self._client() as client:
                url: str = await client.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": self._bucket, "Key": storage_path},
                    ExpiresIn=self._presign_expiry,
                )
                return url
        except ClientError as exc:
            logger.warning("s3_presign_failed", key=storage_path, error_code=_error_code(exc))
            raise StorageError(f"Failed to presign {storage_path!r}") from exc
        except BotoCoreError as exc:
            # Signing is local, so this is the credential-resolution failure
            # (NoCredentialsError) rather than anything network-shaped.
            logger.warning("s3_presign_failed", key=storage_path, error_type=type(exc).__name__)
            raise StorageError(f"Failed to presign {storage_path!r}") from exc


def _error_code(exc: ClientError) -> str:
    """The botocore error code, or ``"Unknown"`` — tolerant of a malformed response."""
    response = getattr(exc, "response", None)
    if not isinstance(response, dict):
        return "Unknown"
    error = response.get("Error")
    if not isinstance(error, dict):
        return "Unknown"
    return str(error.get("Code", "Unknown"))


__all__ = ["S3StorageBackend"]
