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

__all__ = [
    "StorageBackend",
    "StorageError",
    "build_storage_path",
    "get_storage_backend",
]


@lru_cache(maxsize=1)
def get_storage_backend() -> StorageBackend:
    """Return the configured storage backend (cached singleton).

    Settings-driven (``storage_backend``): ``"local"`` today; an ``"s3"`` branch
    is a trivial future addition (Phase 7) with no calling-code changes. An
    unknown value raises a clear :class:`ValueError`.
    """
    if settings.storage_backend == "local":
        return LocalStorageBackend(settings.storage_local_path)
    # Future (Phase 7):
    #     if settings.storage_backend == "s3":
    #         return S3StorageBackend(...)
    raise ValueError(f"Unknown storage backend: {settings.storage_backend!r}")
