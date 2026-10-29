"""The mail sender: hands a finished email to a provider and returns its message id (LP-993).

Two versions, chosen by `settings.mail_transport`:

- `SesMailSender` (staging): Amazon SES v2 raw send, with the configuration set that brings delivery
  events back. No automatic retries; see the class.
- `SmtpMailSender` (dev): MailHog.

`get_mail_sender()` returns None when no transport is configured, which means nothing transmits and
the processor copies the message out herself (copy-and-send).

SYNC, ON PURPOSE. LP-994 calls it from the worker, which is sync. From async code, run it in a
thread (`asyncio.to_thread`) so a 30-second SES timeout does not block the event loop.

NOTHING HERE LOGS A RECIPIENT, A SUBJECT OR A BODY. A failure logs the provider's error code and
nothing else; the message itself is the evidence record's job, not the log's.

This is not the mailbox-connection registry in `services/mail_transport.py` (Route A/B, which LP-994
rewires). Only `TransportError` is shared.
"""

from __future__ import annotations

import smtplib
from abc import ABC, abstractmethod
from email.message import EmailMessage
from email.utils import parseaddr
from typing import Any

import boto3
import structlog
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError, ConnectionClosedError, ReadTimeoutError

from app.core.config import settings
from app.services.mail_transport import TransportError

logger = structlog.get_logger(__name__)


class SendError(TransportError):
    """The provider did not take the message.

    `code` is the provider's own error code (`MessageRejected`, `AccountSendingPausedException`,
    `MailFromDomainNotVerifiedException`, …) or the exception name for a network failure.

    `outcome_unknown` is True when the request may have reached SES and only the answer was lost (a
    read timeout, a dropped connection). The email MAY HAVE GONE. LP-994 must not treat that as
    "failed, safe to resend": it is "not confirmed", for a person to check.
    """

    def __init__(self, code: str, *, outcome_unknown: bool = False) -> None:
        super().__init__(f"The mail provider did not accept the message ({code}).")
        self.code = code
        self.outcome_unknown = outcome_unknown


class MailSender(ABC):
    """Sends one finished email."""

    @abstractmethod
    def send(self, message: EmailMessage) -> str:
        """Hand `message` to the provider. Returns the provider's message id. Raises `SendError`."""


#: A network failure after the request was written: SES may have accepted it.
_MAYBE_SENT: tuple[type[Exception], ...] = (ReadTimeoutError, ConnectionClosedError)


class SesMailSender(MailSender):
    """Amazon SES v2, raw message, with our configuration set.

    NO AUTOMATIC RETRIES (`total_max_attempts=1`). botocore retries a timeout or a 5xx by default. If
    SES accepted the email and only its answer was lost, a retry sends the borrower the same email
    twice, and nothing downstream can take one back. One attempt; a lost answer surfaces as
    `SendError(outcome_unknown=True)` and a person decides.

    `total_max_attempts`, NOT `max_attempts`: botocore's `max_attempts` counts RETRIES, so
    `{"max_attempts": 1}` means one retry and two sends (measured: it becomes
    `total_max_attempts: 2`). `test_ses_makes_exactly_one_attempt` counts the HTTP requests.

    Recipients come from the message's To and Cc headers: no `Destination` is passed, so SES reads
    them from the raw message, and the envelope cannot disagree with what the borrower sees.
    """

    def __init__(self, client: Any | None = None) -> None:
        self._client = client or boto3.client(
            "sesv2",
            region_name=settings.s3_region,
            config=Config(connect_timeout=5, read_timeout=30, retries={"total_max_attempts": 1}),
        )

    def send(self, message: EmailMessage) -> str:
        configuration_set = settings.ses_configuration_set
        if not configuration_set:
            # Without it no delivery, bounce or complaint event comes back, and a bounce would
            # never suppress the address. Refused before anything is sent.
            raise SendError("ConfigurationSetMissing")
        from_address = parseaddr(str(message["From"]))[1]
        try:
            response = self._client.send_email(
                FromEmailAddress=from_address,
                Content={"Raw": {"Data": message.as_bytes()}},
                ConfigurationSetName=configuration_set,
            )
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", "ClientError"))
            logger.warning("ses_send_refused", error_code=code)
            raise SendError(code) from exc
        except BotoCoreError as exc:
            code = type(exc).__name__
            unknown = isinstance(exc, _MAYBE_SENT)
            logger.warning("ses_send_failed", error_code=code, outcome_unknown=unknown)
            raise SendError(code, outcome_unknown=unknown) from exc
        return str(response["MessageId"])


class SmtpMailSender(MailSender):
    """MailHog in dev. Returns the message's own Message-ID, the only id SMTP gives back."""

    def send(self, message: EmailMessage) -> str:
        try:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
                smtp.send_message(message)
        except (smtplib.SMTPException, OSError) as exc:
            code = type(exc).__name__
            logger.warning("smtp_send_failed", error_code=code)
            raise SendError(code) from exc
        return str(message["Message-ID"])


def get_mail_sender() -> MailSender | None:
    """The configured sender, or None (nothing transmits; copy-and-send)."""
    if settings.mail_transport == "ses":
        return SesMailSender()
    if settings.mail_transport == "smtp":
        return SmtpMailSender()
    return None


__all__ = [
    "MailSender",
    "SendError",
    "SesMailSender",
    "SmtpMailSender",
    "get_mail_sender",
]
