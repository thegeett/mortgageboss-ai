"""Storage package — the document byte-storage abstraction.

Calling code obtains a backend via :func:`get_storage_backend` and talks only
to the :class:`~app.storage.base.StorageBackend` interface; it never knows or
cares whether bytes live on the local filesystem (dev) or S3 (production).
"""

from functools import lru_cache
from pathlib import Path

from app.core.config import settings
from app.storage.base import (
    StorageBackend,
    StorageError,
    build_storage_path,
)
from app.storage.local import LocalStorageBackend
from app.storage.s3 import S3StorageBackend

__all__ = [
    "LocalStorageBackend",
    "S3StorageBackend",
    "StorageBackend",
    "StorageError",
    "build_storage_path",
    "get_mail_storage",
    "get_storage_backend",
]


@lru_cache(maxsize=1)
def get_storage_backend() -> StorageBackend:
    """Return the configured storage backend (cached singleton).

    Settings-driven (``storage_backend``): ``"local"`` for dev, ``"s3"`` for
    Fargate (C0), where the API and worker are separate tasks with no shared
    filesystem. Calling code is unchanged either way — it sees only
    :class:`~app.storage.base.StorageBackend`. An unknown value raises a clear
    :class:`ValueError`.

    The ``s3_bucket`` here cannot be ``None``: the settings validator refuses to
    start with ``storage_backend="s3"`` and no bucket
    (:meth:`app.core.config.Settings._require_s3_bucket_when_s3`), so the assert
    documents an invariant rather than guarding a reachable path.

    **The ``lru_cache`` is safe under Celery prefork.** It caches the *backend
    instance*, and the S3 instance holds only an ``aioboto3.Session`` — a
    credential/config resolver with no sockets, which is fork-safe. Clients (the
    non-fork-safe part, and the loop-bound part) are opened per operation and never
    held. See :mod:`app.storage.s3` for the full reasoning.
    """
    if settings.storage_backend == "local":
        return LocalStorageBackend(settings.storage_local_path)
    if settings.storage_backend == "s3":
        # Invariant, not a reachable guard — the settings validator already refused
        # to start without a bucket. Narrows the type for mypy and fails loudly if
        # someone ever patches the setting past the validator (as the tests do).
        if settings.s3_bucket is None:
            raise ValueError('storage_backend is "s3" but s3_bucket is not set')
        return S3StorageBackend(
            bucket=settings.s3_bucket,
            region=settings.s3_region,
            endpoint_url=settings.s3_endpoint_url,
            kms_key_id=settings.s3_kms_key_id,
            presign_expiry=settings.s3_presign_expiry_seconds,
        )
    raise ValueError(f"Unknown storage backend: {settings.storage_backend!r}")


def get_mail_storage() -> StorageBackend:
    """Raw email files: the mail bucket on S3, a folder in local dev (LP-992).

    The same keys in both: ``outbound/<communication_id>.eml`` (a copy of each sent message, written
    by the worker from LP-994) and ``inbound/<id>`` (what SES writes). Use ``save_at`` / ``read`` /
    ``delete`` with those keys; ``save`` would build a document-shaped tenant path instead.

    ``"s3"`` → the existing S3 backend on ``settings.mail_bucket``, refusing loudly when it is
    unset. ``"local"`` → the existing local backend rooted at ``<storage_local_path>/mail``.

    ENCRYPTION: it sends ``s3_kms_key_id``, the documents key. In staging that is the SAME CMK as
    the mail bucket's default (`module.secrets.kms_key_arn` feeds both; `infra/envs/staging/
    main.tf`), and the worker's `MailKey` statement allows GenerateDataKey on it. If the two keys
    are ever split, this must send the mail key instead, or the write is refused by KMS.

    WHAT THE WORKER MAY DO with it in staging (LP-986 IAM): PutObject under ``outbound/`` and
    GetObject under ``inbound/``. Reading back or deleting an ``outbound/`` object is AccessDenied
    there, by design: a sent-mail copy is a record.

    Not cached, unlike :func:`get_storage_backend`: building either backend is cheap, and the
    setting is read on each call.
    """
    if settings.storage_backend == "s3":
        if not settings.mail_bucket:
            raise ValueError(
                'storage_backend is "s3" but MAIL_BUCKET is not set; raw email has nowhere to go'
            )
        return S3StorageBackend(
            bucket=settings.mail_bucket,
            region=settings.s3_region,
            endpoint_url=settings.s3_endpoint_url,
            kms_key_id=settings.s3_kms_key_id,
            presign_expiry=settings.s3_presign_expiry_seconds,
        )
    if settings.storage_backend == "local":
        return LocalStorageBackend(Path(settings.storage_local_path) / "mail")
    raise ValueError(f"Unknown storage backend: {settings.storage_backend!r}")
