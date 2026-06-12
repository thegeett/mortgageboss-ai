"""Storage backend abstraction.

The application saves and reads document BYTES through this interface,
independent of where they live (local filesystem in dev, S3 in production —
Phase 7). Calling code never touches the filesystem or S3 directly; it talks
only to :class:`StorageBackend`, so swapping backends is a config change, not a
rewrite. This realizes the LP-15 decision (ADR-057) that a ``Document`` row
holds a ``storage_path``, not the bytes.

Storage paths are built from SERVER-CONTROLLED UUIDs (company/file/document),
never from user input, and the extension is sanitized — this prevents path
traversal and filename collisions. The path is tenant-prefixed::

    {company_id}/{file_id}/{document_id}.{ext}

The leading ``company_id`` organizes bytes by tenant and leaves room for future
per-tenant storage controls.
"""

from abc import ABC, abstractmethod
from uuid import UUID

#: Extension used when the filename has no/odd extension or one we don't allow.
SAFE_DEFAULT_EXT = "bin"

#: Allowlist of extensions we expect. Mortgage documents are PDFs and scans
#: (images). Anything outside this set falls back to ``SAFE_DEFAULT_EXT`` — the
#: extension is metadata for the stored blob, never used to decide execution
#: (stored files are data, never run).
ALLOWED_EXTENSIONS = frozenset({"pdf", "jpg", "jpeg", "png", "tif", "tiff", "heic", "bin"})


class StorageError(Exception):
    """Raised on storage failures: missing file, path traversal, or I/O error."""


def _sanitize_extension(filename: str) -> str:
    """Derive a safe, lowercase extension from a (user-controlled) filename.

    Takes the last dot-segment, lowercases it, strips anything non-alphanumeric,
    and enforces the allowlist. Anything missing, junk, or unrecognized becomes
    :data:`SAFE_DEFAULT_EXT`. The result is always a short ``[a-z0-9]`` token —
    it can never carry a path separator, ``..``, or other traversal characters.
    """
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    ext = "".join(ch for ch in ext if ch.isalnum())
    if not ext or ext not in ALLOWED_EXTENSIONS:
        return SAFE_DEFAULT_EXT
    return ext


def build_storage_path(
    company_id: UUID,
    file_id: UUID,
    document_id: UUID,
    filename: str,
) -> str:
    """Build a tenant-prefixed, collision-free, traversal-safe storage path.

    Every path component is a server-controlled UUID; only the extension derives
    from the (sanitized) filename. The returned value is the relative
    ``storage_path`` to persist on ``Document.storage_path`` — never an absolute
    filesystem path.
    """
    ext = _sanitize_extension(filename)
    return f"{company_id}/{file_id}/{document_id}.{ext}"


class StorageBackend(ABC):
    """Abstract interface for document byte storage.

    Implementations: :class:`~app.storage.local.LocalStorageBackend` (dev); an
    S3 backend lands in production (Phase 7), selected via settings. The factory
    :func:`app.storage.get_storage_backend` returns the configured one.
    """

    @abstractmethod
    async def save(
        self,
        *,
        company_id: UUID,
        file_id: UUID,
        document_id: UUID,
        filename: str,
        content: bytes,
    ) -> str:
        """Store ``content``; return the ``storage_path`` to persist on the Document.

        The path is built from the server-controlled UUIDs (see
        :func:`build_storage_path`); ``filename`` only contributes a sanitized
        extension. The return value is the relative path, not an absolute one.
        """

    @abstractmethod
    async def read(self, storage_path: str) -> bytes:
        """Return the bytes for a stored path. Raise :class:`StorageError` if missing."""

    @abstractmethod
    async def delete(self, storage_path: str) -> None:
        """Remove a stored file. Idempotent: deleting an absent file is a no-op."""

    @abstractmethod
    async def get_url(self, storage_path: str) -> str | None:
        """A URL to access the file directly.

        ``None`` when there is no direct URL — local files are served only
        through the auth'd download endpoint (LP-36). The S3 backend will return
        a short-lived presigned URL here.
        """
