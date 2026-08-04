#!/usr/bin/env python
"""Verify the S3 storage backend against a REAL bucket (C0, task 6).

The unit tests in ``tests/storage/test_s3_storage.py`` stub the client, so they prove
the backend's *contract* but nothing about the world it runs in. They cannot tell you
whether the task role has the right permissions, whether the bucket policy accepts your
encryption arguments, or whether a presigned URL actually resolves. This script does —
it drives the real :class:`app.storage.s3.S3StorageBackend` against a real bucket.

**Run this before anything on Fargate depends on the backend.**

    cd backend
    uv run python scripts/verify-s3.py --bucket my-bucket
    uv run python scripts/verify-s3.py --bucket my-bucket --kms-key-id arn:aws:kms:...
    uv run python scripts/verify-s3.py --bucket my-bucket --endpoint-url http://localhost:9000

Credentials come from botocore's default provider chain — SSO or a profile locally, the
task role on ECS. There is no credential flag here on purpose; see ADR-356.

Steps, in order (encryption is checked BEFORE deletion, since the object must exist):

  1. save      — write a small payload through the backend
  2. read      — read it back and assert byte equality
  3. presign   — get a presigned URL and confirm it resolves HTTP 200
  4. encrypt   — HeadObject and confirm the expected SSE header
  5. delete    — remove the object
  6. delete    — remove it AGAIN, proving idempotency

Every step prints its outcome. The script exits non-zero on the first failure, so it is
safe to use as a deployment gate.

It writes exactly ONE object and deletes it. The key comes from the app's own
:func:`~app.storage.base.build_storage_path` — deliberately, since proving the real key
path is half the point — so it looks like any document key
(``{uuid}/{uuid}/{uuid}.pdf``) and carries no "this is a test" marker. The key is
printed at the save step; if the run fails before the delete steps, that object is left
behind and you should remove it yourself. Use ``--keep`` to retain it on purpose.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from uuid import uuid4

# Only the extension survives build_storage_path's sanitization, so this name never
# reaches the key — it exists to make the intent obvious at the call site.
VERIFY_FILENAME = "c0-verify.pdf"
PAYLOAD = b"%PDF-1.7\nC0 s3 verification payload\x00\xff\n"

_OK = "  ok  "
_FAIL = " FAIL "


def _step(label: str, detail: str = "") -> None:
    print(f"[{_OK}] {label}" + (f" — {detail}" if detail else ""), flush=True)


def _fail(label: str, detail: str) -> None:
    print(f"[{_FAIL}] {label} — {detail}", file=sys.stderr, flush=True)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="verify-s3.py",
        description="Verify the S3 storage backend against a real bucket (C0).",
        epilog=(
            "Credentials come from the default AWS provider chain (SSO/profile locally, "
            "task role on ECS). Exits non-zero on the first failure."
        ),
    )
    parser.add_argument("--bucket", required=True, help="Target S3 bucket name")
    parser.add_argument("--region", default="us-east-1", help="AWS region (default: us-east-1)")
    parser.add_argument("--endpoint-url", default=None, help="Custom endpoint for MinIO/LocalStack")
    parser.add_argument(
        "--kms-key-id",
        default=None,
        help="KMS key for SSE-KMS; omit to verify SSE-S3 (AES256)",
    )
    parser.add_argument(
        "--presign-expiry",
        type=int,
        default=900,
        help="Presigned URL expiry in seconds (default: 900)",
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help="Skip the delete steps and leave the object in place for inspection",
    )
    return parser.parse_args(argv)


async def _run(args: argparse.Namespace) -> int:
    # Imported here, not at module scope, so `--help` works without app settings
    # (importing app.storage builds the Settings singleton, which needs backend/.env).
    import aioboto3
    import httpx
    from app.storage.base import StorageError
    from app.storage.s3 import S3StorageBackend

    expected_sse = "aws:kms" if args.kms_key_id else "AES256"
    backend = S3StorageBackend(
        bucket=args.bucket,
        region=args.region,
        endpoint_url=args.endpoint_url,
        kms_key_id=args.kms_key_id,
        presign_expiry=args.presign_expiry,
    )

    # Fresh server-controlled UUIDs, exactly as the app builds them — so this exercises
    # the real key derivation rather than a hand-written key.
    company_id = uuid4()
    file_id = uuid4()
    document_id = uuid4()

    print(f"bucket={args.bucket} region={args.region} expected_sse={expected_sse}")
    if args.endpoint_url:
        print(f"endpoint={args.endpoint_url}")
    print("-" * 68)

    key: str | None = None

    # --- 1. save ---------------------------------------------------------------
    try:
        key = await backend.save(
            company_id=company_id,
            file_id=file_id,
            document_id=document_id,
            filename=VERIFY_FILENAME,
            content=PAYLOAD,
        )
        _step("save", f"key={key} ({len(PAYLOAD)} bytes)")
    except Exception as exc:
        _fail("save", f"{type(exc).__name__}: {exc}")
        return 1

    # --- 2. read ---------------------------------------------------------------
    try:
        got = await backend.read(key)
        if got != PAYLOAD:
            _fail("read", f"byte mismatch: wrote {len(PAYLOAD)} bytes, read {len(got)}")
            return 1
        _step("read", f"{len(got)} bytes, byte-identical")
    except Exception as exc:
        _fail("read", f"{type(exc).__name__}: {exc}")
        return 1

    # --- 3. presign + fetch ----------------------------------------------------
    try:
        url = await backend.get_url(key)
        if not url:
            _fail("presign", "get_url returned None")
            return 1
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as http:
            resp = await http.get(url)
        if resp.status_code != 200:
            _fail("presign", f"URL resolved HTTP {resp.status_code} (expected 200)")
            return 1
        if resp.content != PAYLOAD:
            _fail("presign", "URL resolved 200 but returned different bytes")
            return 1
        _step("presign", f"HTTP 200, {len(resp.content)} bytes, expiry={args.presign_expiry}s")
    except Exception as exc:
        _fail("presign", f"{type(exc).__name__}: {exc}")
        return 1

    # --- 4. encryption header (BEFORE deletion — the object must still exist) ---
    try:
        session = aioboto3.Session()
        async with session.client(
            "s3", region_name=args.region, endpoint_url=args.endpoint_url
        ) as client:
            head = await client.head_object(Bucket=args.bucket, Key=key)
        actual_sse = head.get("ServerSideEncryption")
        if actual_sse != expected_sse:
            _fail("encrypt", f"ServerSideEncryption={actual_sse!r}, expected {expected_sse!r}")
            return 1
        detail = f"ServerSideEncryption={actual_sse}"
        if args.kms_key_id:
            detail += f", SSEKMSKeyId={head.get('SSEKMSKeyId')}"
        detail += f", ContentType={head.get('ContentType')}"
        _step("encrypt", detail)
    except Exception as exc:
        _fail("encrypt", f"{type(exc).__name__}: {exc}")
        return 1

    if args.keep:
        print("-" * 68)
        print(f"--keep set: object retained at s3://{args.bucket}/{key}")
        return 0

    # --- 5 & 6. delete, then delete again (idempotency) ------------------------
    try:
        await backend.delete(key)
        _step("delete", "object removed")
    except Exception as exc:
        _fail("delete", f"{type(exc).__name__}: {exc}")
        return 1

    try:
        await backend.delete(key)
        _step("delete (again)", "no error on a missing key — idempotent")
    except Exception as exc:
        _fail("delete (again)", f"NOT idempotent: {type(exc).__name__}: {exc}")
        return 1

    # Belt and braces: the object really is gone, and read maps it to StorageError.
    try:
        await backend.read(key)
    except StorageError:
        _step("read after delete", "StorageError as expected")
    except Exception as exc:
        _fail("read after delete", f"expected StorageError, got {type(exc).__name__}: {exc}")
        return 1
    else:
        _fail("read after delete", "object still readable after delete")
        return 1

    print("-" * 68)
    print("ALL CHECKS PASSED — the S3 backend works against this bucket.")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        return asyncio.run(_run(args))
    except KeyboardInterrupt:
        _fail("aborted", "interrupted")
        return 130


if __name__ == "__main__":
    sys.exit(main())
