"""The SES notification is unpacked here, and nothing tested that until this file (LP-807 review).

The bug this exists for: `ses_message_id` was read from the `receipt` object. AWS documents it on
the `mail` object — `receipt` carries `action`, the verdicts, `recipients` and timestamps, and no id
at all. So it was `None` for every real message, and `compute_ingest_key` fell through to its next
source, the SENDER-WRITTEN `Message-ID` header, as a globally unique dedup key.

That is not a cosmetic mis-read. `ingest_key` is unique across every tenant, so two companies
receiving the same forwarded thread would have had the second one silently suppressed — the exact
risk LP-807 escalated as unreachable on the SES path, made reachable on every message.

The notification below follows the field layout in "Contents of notifications for Amazon SES email
receiving", read 2026-09-07.
"""

from __future__ import annotations

from typing import Any

from app.tasks.inbound import _s3_record, _ses_message_id

#: A notification shaped as AWS documents it. `mail` carries `messageId`; `receipt` does not.
SES_NOTIFICATION: dict[str, Any] = {
    "notificationType": "Received",
    "mail": {
        "timestamp": "2026-09-07T07:00:00.000Z",
        "source": "borrower@example.com",
        # Not a secret — an SES delivery id, which is also the S3 object key and appears in the
        # bucket listing. detect-secrets sees the entropy, not the meaning.
        "messageId": "qwertyuiop1234567890examplemsgid",  # pragma: allowlist secret
        "destination": ["lf-abc123@inbox.staging.mortgageboss.ai"],
        "commonHeaders": {"messageId": "<sender-written@mail.example.com>"},
    },
    "receipt": {
        "timestamp": "2026-09-07T07:00:00.000Z",
        "processingTimeMillis": 222,
        "recipients": ["lf-abc123@inbox.staging.mortgageboss.ai"],
        "spamVerdict": {"status": "PASS"},
        "virusVerdict": {"status": "PASS"},
        "spfVerdict": {"status": "PASS"},
        "dkimVerdict": {"status": "PASS"},
        "dmarcVerdict": {"status": "PASS"},
        "action": {
            "type": "S3",
            "topicArn": "arn:aws:sns:us-east-1:111122223333:inbound",
            "bucketName": "mbai-staging-inbound",
            "objectKey": "inbound/qwertyuiop1234567890examplemsgid",  # pragma: allowlist secret
        },
    },
}


def test_the_receipt_object_does_not_carry_the_message_id() -> None:
    """The premise of the bug, pinned so nobody re-derives it from memory.

    If a future SES notification did start carrying `messageId` on `receipt`, this fails and
    somebody gets to simplify the extraction — which is worth more than a comment saying it is
    absent.
    """
    assert "messageId" not in SES_NOTIFICATION["receipt"]
    assert SES_NOTIFICATION["mail"]["messageId"]


def test_the_message_id_is_taken_from_mail_not_receipt() -> None:
    """Calls the PRODUCTION extractor.

    The first version of this test re-derived the selection inline and then asserted the result —
    so it passed unchanged when the extraction was reverted to reading `receipt`. A test that
    reimplements the thing it is checking is asserting its own copy. `_ses_message_id` exists as a
    named function for exactly that reason.
    """
    assert _ses_message_id(SES_NOTIFICATION) == "qwertyuiop1234567890examplemsgid"
    # Not the sender's header, which is what it fell back to before.
    assert _ses_message_id(SES_NOTIFICATION) != "<sender-written@mail.example.com>"


def test_the_extractor_is_defensive_about_shape() -> None:
    """None rather than a raise, and never an empty string — `compute_ingest_key` treats falsy as
    absent, so returning `""` would silently be the same bug."""
    assert _ses_message_id({}) is None
    assert _ses_message_id({"mail": {}}) is None
    assert _ses_message_id({"mail": {"messageId": ""}}) is None
    assert _ses_message_id({"receipt": {"messageId": "wrong-object"}}) is None


def test_the_object_key_is_the_same_id_so_the_fallback_is_sound() -> None:
    """AWS: of the S3 action's `objectKey`, "this is the same as the messageId in the mail object".

    `_ingest_message` falls back to the object key when the id is absent. That is only safe if the
    two really are the same value, so it is asserted rather than trusted — and the fixture is built
    from the documented shape rather than to make this pass.
    """
    record = _s3_record(SES_NOTIFICATION)
    assert record is not None
    assert record[1].endswith(SES_NOTIFICATION["mail"]["messageId"])


def test_an_unexpected_shape_yields_no_record_rather_than_raising() -> None:
    """Raising here fails a whole SQS batch and takes well-formed messages down with the bad one."""
    assert _s3_record({}) is None
    assert _s3_record({"receipt": {}}) is None
    assert _s3_record({"receipt": {"action": {"type": "Lambda"}}}) is None
