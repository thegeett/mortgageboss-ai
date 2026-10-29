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
from typing import Any, NoReturn

import boto3
import structlog
from botocore.config import Config
from botocore.exceptions import (
    BotoCoreError,
    ClientError,
    ConnectTimeoutError,
    EndpointConnectionError,
    HTTPClientError,
    ProxyConnectionError,
)
from botocore.exceptions import ConnectionError as BotoConnectionError

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


#: Network failures that happen BEFORE the request is written: no connection was ever made, so
#: SES cannot have the email. Every other network failure is outcome-unknown.
#:
#: LISTED BY WHAT IS SAFE, NOT BY WHAT IS RISKY. botocore turns a read timeout, a dropped connection,
#: an SSL error, and ANY OTHER exception during the request (a bare `HTTPClientError`) into its own
#: types; a list of the risky ones missed that catch-all and called it a clean failure. A new or
#: unlisted error now lands on "not confirmed", the side where a person checks before a resend.
_NOT_SENT: tuple[type[Exception], ...] = (
    EndpointConnectionError,
    ConnectTimeoutError,
    ProxyConnectionError,
)


def _outcome_unknown(exc: BotoCoreError) -> bool:
    """True when the request may have reached SES. A non-network error (no credentials, a bad
    parameter) is raised before anything is sent."""
    if isinstance(exc, _NOT_SENT):
        return False
    return isinstance(exc, HTTPClientError | BotoConnectionError)


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
            unknown = _outcome_unknown(exc)
            logger.warning("ses_send_failed", error_code=code, outcome_unknown=unknown)
            raise SendError(code, outcome_unknown=unknown) from exc
        return str(response["MessageId"])


class SmtpMailSender(MailSender):
    """MailHog in dev. Returns the message's own Message-ID, the only id SMTP gives back.

    `outcome_unknown` means what it means for SES. A failure to connect, or a reply refusing the
    sender, a recipient or the data, is a clean failure. A timeout or a dropped connection once the
    message is being handed over is not: the server may have taken it.
    """

    def send(self, message: EmailMessage) -> str:
        try:
            smtp = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10)
        except (smtplib.SMTPException, OSError) as exc:
            self._fail(exc, outcome_unknown=False)
        try:
            smtp.send_message(message)
        except (smtplib.SMTPResponseException, smtplib.SMTPRecipientsRefused) as exc:
            self._fail(exc, outcome_unknown=False)
        except (smtplib.SMTPException, OSError) as exc:
            self._fail(exc, outcome_unknown=True)
        finally:
            # The message is handed over (or not) by now; a failed QUIT changes neither.
            try:
                smtp.quit()
            except (smtplib.SMTPException, OSError):
                smtp.close()
        return str(message["Message-ID"])

    @staticmethod
    def _fail(exc: Exception, *, outcome_unknown: bool) -> NoReturn:
        code = type(exc).__name__
        logger.warning("smtp_send_failed", error_code=code, outcome_unknown=outcome_unknown)
        raise SendError(code, outcome_unknown=outcome_unknown) from exc


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
