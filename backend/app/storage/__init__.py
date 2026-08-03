"""Storage package — the document byte-storage abstraction.

Calling code obtains a backend via :func:`get_storage_backend` and talks only
to the :class:`~app.storage.base.StorageBackend` interface; it never knows or
cares whether bytes live on the local filesystem (dev) or S3 (production).
"""

from functools import lru_cache

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
