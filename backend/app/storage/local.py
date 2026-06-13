"""Local filesystem storage backend (development).

Stores document bytes under a configured root directory using the
tenant-prefixed UUID path pattern from :mod:`app.storage.base`. The root sits
OUTSIDE any web-served/static directory, so stored files are reachable only
through the auth'd download endpoint (LP-36), never via a direct URL.

Every operation resolves the full path and verifies it stays within the root
before touching the filesystem — the path-traversal defense (see
:meth:`LocalStorageBackend._resolve_within_root`). Blocking file I/O is wrapped
in :func:`asyncio.to_thread` so the interface is genuinely async and never
blocks the event loop.
"""

import asyncio
from pathlib import Path
from uuid import UUID

from app.storage.base import StorageBackend, StorageError, build_storage_path


class LocalStorageBackend(StorageBackend):
    """Store document bytes on the local filesystem under a root directory."""

    def __init__(self, root: str | Path) -> None:
        # Resolve once so the root is absolute and symlink-free; every later
        # path check compares against this canonical root.
        self._root = Path(root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def _resolve_within_root(self, storage_path: str) -> Path:
        """Resolve ``storage_path`` under the root, rejecting traversal.

        Joins the (relative) storage path onto the root and fully resolves it,
        then confirms the result is the root itself or sits beneath it. An
        absolute ``storage_path``, a ``..`` sequence that climbs out, or a
        symlink that points elsewhere all resolve outside the root and are
        rejected with :class:`StorageError` — and crucially, this check runs
        BEFORE any filesystem read/write, so a rejected path touches nothing.
        """
        candidate = (self._root / storage_path).resolve()
        if candidate != self._root and self._root not in candidate.parents:
            raise StorageError(f"Resolved path escapes the storage root: {storage_path!r}")
        return candidate

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
        full = self._resolve_within_root(storage_path)

        def _write() -> None:
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_bytes(content)

        await asyncio.to_thread(_write)
        return storage_path

    async def read(self, storage_path: str) -> bytes:
        full = self._resolve_within_root(storage_path)

        def _read() -> bytes:
            if not full.is_file():
                raise StorageError(f"No stored file at {storage_path!r}")
            return full.read_bytes()

        return await asyncio.to_thread(_read)

    async def delete(self, storage_path: str) -> None:
        full = self._resolve_within_root(storage_path)

        def _delete() -> None:
            # Idempotent: deleting an absent file is a no-op (missing_ok).
            full.unlink(missing_ok=True)

        await asyncio.to_thread(_delete)

    async def get_url(self, storage_path: str) -> str | None:
        # Local files have no direct URL — they are served only through the
        # auth'd download endpoint (LP-36). Presigned URLs are an S3-era feature.
        return None
