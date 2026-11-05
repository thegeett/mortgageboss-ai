"""LP-1008 — the reader: a message leaves the queue only once it is saved."""

from __future__ import annotations

import asyncio
import json
from email.message import EmailMessage
from typing import Any
from uuid import uuid4

import pytest
from app.core.config import settings
from app.models.inbound_message import InboundMessage
from app.storage.s3 import S3StorageBackend
from app.tasks import inbound
from app.tasks.base import run_async, task_session
from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncEngine


def _body(key: str) -> str:
    return json.dumps(
        {
            "mail": {"messageId": key},
            "receipt": {
                "recipients": ["lf-abcd@mb.example.test"],
                "action": {"bucketName": "the-mail-bucket", "objectKey": f"inbound/{key}"},
            },
        }
    )


class _FakeSqs:
    def __init__(self, messages: list[dict[str, str]], log: list[str]) -> None:
        self.messages = messages
        self.log = log

    def receive_message(self, **_: Any) -> dict[str, Any]:
        return {"Messages": self.messages}

    def delete_message(self, *, QueueUrl: str, ReceiptHandle: str) -> None:
        self.log.append(f"delete {ReceiptHandle}")


def _poll(
    monkeypatch: pytest.MonkeyPatch, bodies: dict[str, str], *, fails: dict[str, Exception]
) -> tuple[int | None, list[str]]:
    """Run `poll_queue` with a fake queue. The handle is the key, so the log reads in order."""
    log: list[str] = []
    messages = [{"Body": body, "ReceiptHandle": key} for key, body in bodies.items()]
    monkeypatch.setattr(settings, "inbound_queue_url", "https://sqs.example.test/q")
    monkeypatch.setattr("boto3.client", lambda *_a, **_k: _FakeSqs(messages, log))

    async def fake_ingest(*, key: str, **_: Any) -> str:
        name = key.removeprefix("inbound/")
        if name in fails:
            log.append(f"failed {name}")
            raise fails[name]
        log.append(f"saved {name}")
        return name

    monkeypatch.setattr(inbound, "_ingest_message", fake_ingest)
    return inbound.poll_queue(), log


def test_a_message_is_deleted_only_after_it_is_saved(monkeypatch: pytest.MonkeyPatch) -> None:
    handled, log = _poll(monkeypatch, {"a": _body("a")}, fails={})
    assert log == ["saved a", "delete a"]
    assert handled == 1


def test_a_failed_save_stays_on_the_queue_and_the_rest_carry_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handled, log = _poll(
        monkeypatch,
        {"a": _body("a"), "b": _body("b"), "c": _body("c")},
        fails={"b": RuntimeError("s3 down")},
    )
    assert log == ["saved a", "delete a", "failed b", "saved c", "delete c"]
    assert handled == 2


def test_running_out_of_time_stops_the_batch_without_deleting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log: list[str] = []
    with pytest.raises(SoftTimeLimitExceeded):
        _, log = _poll(
            monkeypatch,
            {"a": _body("a"), "b": _body("b")},
            fails={"a": SoftTimeLimitExceeded()},
        )
    assert not any(entry.startswith("delete") for entry in log)


def test_an_unparseable_body_stays_on_the_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    handled, log = _poll(monkeypatch, {"a": "not json", "b": _body("b")}, fails={})
    assert log == ["saved b", "delete b"]
    assert handled == 1


def test_real_ingests_in_one_process_each_save_and_a_redelivery_adds_nothing(
    test_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE EVENT LOOP BUG, which only shows on a second run in one process, as in a worker child:
    with the app's pooled engine the second run raises "Event loop is closed". Real database."""
    monkeypatch.setattr(
        settings, "database_url", test_engine.url.render_as_string(hide_password=False)
    )

    message = EmailMessage()
    message["From"] = "jane@borrower.example"
    message["To"] = "nobody@example.test"
    message.set_content("hello")
    raw = message.as_bytes()

    async def fake_read(_self: S3StorageBackend, _key: str) -> bytes:
        return raw

    monkeypatch.setattr(S3StorageBackend, "read", fake_read)
    keys = [f"lp1008-{uuid4().hex}" for _ in range(3)]

    def ingest(key: str) -> str:
        return run_async(
            inbound._ingest_message(
                bucket="the-mail-bucket", key=f"inbound/{key}", receipt=None, ses_message_id=key
            )
        )

    async def count() -> int:
        async with task_session() as db:
            stored = await db.scalar(
                select(func.count())
                .select_from(InboundMessage)
                .where(InboundMessage.ingest_key.in_(keys))
            )
            return int(stored or 0)

    async def clean_up() -> None:
        async with task_session() as db:
            await db.execute(delete(InboundMessage).where(InboundMessage.ingest_key.in_(keys)))
            await db.commit()

    try:
        ids = [ingest(key) for key in keys]
        assert len(set(ids)) == 3
        assert asyncio.run(count()) == 3

        # Redelivered after a lost delete: same row, no error, so it can then be deleted.
        assert ingest(keys[0]) == ids[0]
        assert asyncio.run(count()) == 3
    finally:
        asyncio.run(clean_up())
