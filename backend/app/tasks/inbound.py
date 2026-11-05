"""Inbound mail task (LP-803, LP-1008) — read the queue, and store what is on it.

REGISTERED IN ``_TASK_MODULES``. A module left out of that list is never imported by the worker, the
task is never registered, and every enqueued message is discarded with no error anywhere — the LP-78
worker-seam bug, which this module would have reproduced exactly.
"""

from __future__ import annotations

import json
from typing import Any

from celery.exceptions import SoftTimeLimitExceeded

from app.core.config import settings
from app.core.logging import get_logger
from app.tasks.base import run_async, task_session
from app.tasks.celery_app import celery_app

logger = get_logger(__name__)

#: How many SQS messages one poll takes. Ten is the API maximum for a single ReceiveMessage.
_BATCH_SIZE = 10


async def _ingest_message(
    *, bucket: str, key: str, receipt: dict[str, Any] | None, ses_message_id: str | None = None
) -> str:
    """Pull one raw message out of the bucket and store it. Committed when this returns.

    `task_session`, not the app's pooled engine: each run has its own event loop, and a pooled
    connection from the last one fails with "Event loop is closed" (`tasks/base.py`).

    NOTHING ABOUT THE MESSAGE IS LOGGED — not the key, which is an SES message id identifying one
    borrower's mail, and certainly not the bytes.
    """
    from app.services.inbound_ingest import process_raw_message
    from app.storage.s3 import S3StorageBackend

    storage = S3StorageBackend(bucket=bucket, region=settings.s3_region)
    raw = await storage.read(key)

    async with task_session() as session:
        # THE WHOLE CHAIN, not just the row. `process_raw_message` stores, assesses (LP-804b) and
        # routes (LP-805). Calling `ingest_raw_message` alone — which is what this did until LP-807 —
        # left every message PENDING and unrouted forever, with both service test suites green.
        #
        # `store_raw=False`: SES already put the object in its own bucket and the path is passed in.
        result = await process_raw_message(
            session,
            raw=raw,
            raw_storage_path=f"s3://{bucket}/{key}",
            # THE SES MESSAGE ID IS NOT ON THE `receipt` OBJECT. AWS documents it on the `mail`
            # object ("Contents of notifications for Amazon SES email receiving"), whose fields are
            # destination / messageId / source / timestamp / headers / commonHeaders; `receipt`
            # carries action, the verdicts, recipients and timestamps and no id at all. Reading it
            # from `receipt` returned None for every real message, so `ingest_key` fell through to
            # its next source — the SENDER-WRITTEN `Message-ID` header — as a globally unique dedup
            # key. That is the cross-tenant suppression LP-807 escalated as unreachable on the SES
            # path; it was reachable on every message.
            #
            # The object key is the same value: AWS says of the S3 action's `objectKey` that "this
            # is the same as the messageId in the mail object". It is used as the fallback rather
            # than the source, so the id travels explicitly and this does not silently depend on
            # the delivery action being S3.
            ses_message_id=ses_message_id or key,
            receipt=receipt,
        )
        await session.commit()
    return result.message_id


@celery_app.task(name="inbound.poll_queue")  # type: ignore[untyped-decorator]
def poll_queue() -> int:
    """Store up to one batch from the inbound SQS queue, deleting each message once it is saved.

    DELETED ONLY AFTER THE COMMIT (LP-1008). A message that fails stays on the queue: SQS redelivers
    it after the visibility timeout, and after 5 receives it goes to the DLQ, where the alarm sees it.
    Ingest is idempotent, so a redelivery of one already saved is a no-op that then gets deleted.

    STORED HERE, NOT IN A SEPARATE TASK, so the message is not waiting behind other work in the
    worker's queue while its visibility timeout runs out and its receive count climbs. The hard time
    limit (180s) is under the visibility timeout (300s).

    A BEAT TASK RATHER THAN A SECOND DAEMON, per the plan. A long-running consumer process would be
    a new deployable with its own health check, restart policy and scaling story, for work that is
    already idempotent and already retried.

    NO-OPS WHEN THE QUEUE IS NOT CONFIGURED, as in local dev, where `inbound_queue_url` is None.
    Returning 0 rather than raising keeps the schedule from filling the log with failures there.

    ON THE BEAT SCHEDULE every minute since LP-1008 (`tasks/celery_app.py`).
    """
    if not settings.inbound_queue_url:
        return 0

    import boto3

    client = boto3.client("sqs", region_name=settings.s3_region)
    received = client.receive_message(
        QueueUrl=settings.inbound_queue_url,
        MaxNumberOfMessages=_BATCH_SIZE,
        WaitTimeSeconds=10,
    )
    handled = 0
    for message in received.get("Messages", []):
        try:
            notification = json.loads(message["Body"])
        except (KeyError, json.JSONDecodeError):
            # Left on the queue deliberately: it will be redelivered and then go to the DLQ, which
            # is where something unparseable should end up. Deleting it here would discard the only
            # copy of whatever went wrong.
            logger.warning("inbound_queue_unparseable_body")
            continue

        record = _s3_record(notification)
        if record is None:
            logger.warning("inbound_queue_unexpected_shape")
            continue

        try:
            run_async(
                _ingest_message(
                    bucket=record[0],
                    key=record[1],
                    receipt=notification.get("receipt"),
                    ses_message_id=_ses_message_id(notification),
                )
            )
        except SoftTimeLimitExceeded:
            # Out of time for the whole batch: stop, rather than carry on until the hard kill.
            raise
        except Exception as exc:  # broad: one bad message must not take the batch down with it
            # The type only. An exception's text can carry the key, which identifies one person's mail.
            logger.warning("inbound_ingest_failed", error_type=type(exc).__name__)
            continue

        client.delete_message(
            QueueUrl=settings.inbound_queue_url, ReceiptHandle=message["ReceiptHandle"]
        )
        handled += 1
    return handled


def _ses_message_id(notification: dict[str, Any]) -> str | None:
    """The id SES assigned this delivery, from the `mail` object.

    A NAMED FUNCTION so it can be tested against a real notification shape rather than re-derived in
    a test that would then assert its own copy. AWS documents `messageId` on `mail`; the `receipt`
    object carries `action`, the verdicts, `recipients` and timestamps and no id at all. Reading it
    from `receipt` returned None for every real message, and `compute_ingest_key` then fell through
    to the SENDER-WRITTEN `Message-ID` header as a globally unique dedup key.
    """
    mail = notification.get("mail")
    message_id = mail.get("messageId") if isinstance(mail, dict) else None
    return message_id if isinstance(message_id, str) and message_id else None


def _s3_record(notification: dict[str, Any]) -> tuple[str, str] | None:
    """``(bucket, key)`` from an SES-to-SNS notification, or None.

    SES's `action` object carries the bucket and object key it wrote to. Read defensively: this is
    the one place where a shape we did not expect must not raise, because raising here fails the
    whole batch and takes the well-formed messages down with the malformed one.
    """
    action = notification.get("receipt", {}).get("action", {})
    bucket = action.get("bucketName")
    key = action.get("objectKey")
    if isinstance(bucket, str) and isinstance(key, str) and bucket and key:
        return bucket, key
    return None
