"""Tests for the local filesystem storage backend (LP-35).

These cover the round-trip, the tenant-prefixed UUID path format, extension
sanitization, the missing-file/delete contracts, ``get_url``, and — the
critical security property — path-traversal rejection. Every test uses a
``tmp_path`` root, never the real storage directory.
"""

from pathlib import Path
from uuid import UUID

import pytest
from app.storage.base import (
    SAFE_DEFAULT_EXT,
    StorageError,
    build_storage_path,
)
from app.storage.local import LocalStorageBackend

# Stable, server-controlled UUIDs for predictable path assertions.
COMPANY_ID = UUID("11111111-1111-1111-1111-111111111111")
FILE_ID = UUID("22222222-2222-2222-2222-222222222222")
DOCUMENT_ID = UUID("33333333-3333-3333-3333-333333333333")


@pytest.fixture
def backend(tmp_path: Path) -> LocalStorageBackend:
    """A LocalStorageBackend rooted at an isolated temp directory."""
    return LocalStorageBackend(tmp_path / "storage")


# --------------------------------------------------------------------------- #
# Round-trip and path format
# --------------------------------------------------------------------------- #


async def test_save_then_read_round_trips_exact_bytes(backend: LocalStorageBackend) -> None:
    content = b"%PDF-1.7\n...binary paystub bytes...\x00\xff"
    storage_path = await backend.save(
        company_id=COMPANY_ID,
        file_id=FILE_ID,
        document_id=DOCUMENT_ID,
        filename="paystub.pdf",
        content=content,
    )
    assert await backend.read(storage_path) == content


async def test_save_returns_tenant_prefixed_uuid_path(backend: LocalStorageBackend) -> None:
    storage_path = await backend.save(
        company_id=COMPANY_ID,
        file_id=FILE_ID,
        document_id=DOCUMENT_ID,
        filename="paystub.pdf",
        content=b"x",
    )
    assert storage_path == f"{COMPANY_ID}/{FILE_ID}/{DOCUMENT_ID}.pdf"


async def test_save_returns_relative_not_absolute_path(
    backend: LocalStorageBackend, tmp_path: Path
) -> None:
    storage_path = await backend.save(
        company_id=COMPANY_ID,
        file_id=FILE_ID,
        document_id=DOCUMENT_ID,
        filename="scan.png",
        content=b"x",
    )
    # The returned path is the key persisted on Document.storage_path — relative,
    # never the absolute filesystem location.
    assert not Path(storage_path).is_absolute()
    assert str(tmp_path) not in storage_path


async def test_save_writes_under_the_root(backend: LocalStorageBackend, tmp_path: Path) -> None:
    storage_path = await backend.save(
        company_id=COMPANY_ID,
        file_id=FILE_ID,
        document_id=DOCUMENT_ID,
        filename="scan.png",
        content=b"hello",
    )
    on_disk = tmp_path / "storage" / storage_path
    assert on_disk.is_file()
    assert on_disk.read_bytes() == b"hello"


# --------------------------------------------------------------------------- #
# Extension sanitization
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("filename", "expected_ext"),
    [
        ("Paystub.PDF", "pdf"),  # uppercase -> lowercase
        ("scan.JPEG", "jpeg"),  # allowlisted
        ("photo.heic", "heic"),
        ("noextension", SAFE_DEFAULT_EXT),  # no dot -> safe default
        ("trailingdot.", SAFE_DEFAULT_EXT),  # empty ext -> safe default
        ("archive.zip", SAFE_DEFAULT_EXT),  # not allowlisted -> safe default
        ("weird.p df", "pdf"),  # junk stripped to alnum, then allowlisted
        ("evil.pdf/../x", SAFE_DEFAULT_EXT),  # path chars stripped, not allowlisted
        ("dotfile.tar.gz", SAFE_DEFAULT_EXT),  # last segment "gz" not allowlisted
    ],
)
def test_build_storage_path_sanitizes_extension(filename: str, expected_ext: str) -> None:
    path = build_storage_path(COMPANY_ID, FILE_ID, DOCUMENT_ID, filename)
    assert path == f"{COMPANY_ID}/{FILE_ID}/{DOCUMENT_ID}.{expected_ext}"


def test_build_storage_path_extension_never_contains_separators() -> None:
    # Even a hostile "extension" cannot inject a path separator.
    path = build_storage_path(COMPANY_ID, FILE_ID, DOCUMENT_ID, "x.pd/f")
    ext = path.rsplit(".", 1)[-1]
    assert "/" not in ext and ".." not in ext


# --------------------------------------------------------------------------- #
# Missing-file and delete contracts
# --------------------------------------------------------------------------- #


async def test_read_missing_path_raises_storage_error(backend: LocalStorageBackend) -> None:
    missing = f"{COMPANY_ID}/{FILE_ID}/{DOCUMENT_ID}.pdf"
    with pytest.raises(StorageError):
        await backend.read(missing)


async def test_delete_removes_the_file(backend: LocalStorageBackend, tmp_path: Path) -> None:
    storage_path = await backend.save(
        company_id=COMPANY_ID,
        file_id=FILE_ID,
        document_id=DOCUMENT_ID,
        filename="paystub.pdf",
        content=b"x",
    )
    on_disk = tmp_path / "storage" / storage_path
    assert on_disk.is_file()

    await backend.delete(storage_path)
    assert not on_disk.exists()


async def test_delete_missing_file_is_a_noop(backend: LocalStorageBackend) -> None:
    # Idempotent contract: deleting an absent file must not raise.
    await backend.delete(f"{COMPANY_ID}/{FILE_ID}/{DOCUMENT_ID}.pdf")


# --------------------------------------------------------------------------- #
# get_url
# --------------------------------------------------------------------------- #


async def test_get_url_returns_none_for_local(backend: LocalStorageBackend) -> None:
    # Local files are served via the auth'd download endpoint (LP-36).
    assert await backend.get_url(f"{COMPANY_ID}/{FILE_ID}/{DOCUMENT_ID}.pdf") is None


# --------------------------------------------------------------------------- #
# CRITICAL: path-traversal rejection — must raise and touch NOTHING outside root
# --------------------------------------------------------------------------- #

TRAVERSAL_PATHS = [
    "../escape.pdf",
    "../../etc/passwd",
    f"{COMPANY_ID}/../../escape.pdf",
    "/etc/passwd",  # absolute path
    "/tmp/evil.pdf",  # absolute path
    "subdir/../../../escape.pdf",
]


@pytest.mark.parametrize("evil_path", TRAVERSAL_PATHS)
async def test_read_rejects_path_traversal(backend: LocalStorageBackend, evil_path: str) -> None:
    with pytest.raises(StorageError):
        await backend.read(evil_path)


@pytest.mark.parametrize("evil_path", TRAVERSAL_PATHS)
async def test_delete_rejects_path_traversal(backend: LocalStorageBackend, evil_path: str) -> None:
    with pytest.raises(StorageError):
        await backend.delete(evil_path)


async def test_traversal_does_not_write_or_delete_outside_root(tmp_path: Path) -> None:
    """A crafted path must not create, read, or remove anything outside the root."""
    root = tmp_path / "storage"
    backend = LocalStorageBackend(root)

    # A sentinel file OUTSIDE the root that traversal might try to clobber.
    outside = tmp_path / "secret.txt"
    outside.write_text("do not touch")
    evil_path = "../secret.txt"

    # delete must reject and leave the outside file untouched.
    with pytest.raises(StorageError):
        await backend.delete(evil_path)
    assert outside.read_text() == "do not touch"

    # read must reject (and not read the outside file).
    with pytest.raises(StorageError):
        await backend.read(evil_path)

    # Nothing escaped the root: the only thing under root is what we control.
    assert outside.exists()


async def test_resolve_within_root_allows_legitimate_nested_path(
    backend: LocalStorageBackend,
) -> None:
    # The normal tenant-prefixed path is several levels deep and must be allowed.
    legit = f"{COMPANY_ID}/{FILE_ID}/{DOCUMENT_ID}.pdf"
    resolved = backend._resolve_within_root(legit)
    assert backend._root in resolved.parents
