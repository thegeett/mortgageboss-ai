"""LP-993 — the mail senders: SES (stubbed with botocore's Stubber), SMTP (mocked), the factory."""

from __future__ import annotations

import smtplib
from typing import Any
from unittest.mock import MagicMock

import pytest
from app.core.config import settings
from app.scripts import send_test_email
from app.services import mail_sender
from app.services.mail_sender import (
    SendError,
    SesMailSender,
    SmtpMailSender,
    get_mail_sender,
)
from app.services.mail_transport import TransportError
from app.services.outbound_mime import build_mime
from botocore.exceptions import (
    BotoCoreError,
    ConnectionClosedError,
    ConnectTimeoutError,
    EndpointConnectionError,
    HTTPClientError,
    NoCredentialsError,
    ProxyConnectionError,
    ReadTimeoutError,
    SSLError,
)
from botocore.stub import Stubber


@pytest.fixture(autouse=True)
def _aws(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fake credentials, so a stubbed client never looks for real ones; the configuration set on."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    monkeypatch.setattr(settings, "s3_region", "us-east-1")
    monkeypatch.setattr(settings, "ses_configuration_set", "mbai-test-outbound")


def _message() -> Any:
    return build_mime(
        from_name="Priya Thaker, ABC Mortgage",
        from_address="lf-y36e@mb-mail.abcmortgage.test",
        to="success@simulator.amazonses.com",
        cc="priya@abcmortgage.test",
        reply_to="lf-y36e@mb-mail.abcmortgage.test",
        subject="Documents",
        body="Hello.\n",
        html=False,
    )


def test_ses_sends_the_raw_message_with_the_configuration_set() -> None:
    sender = SesMailSender()
    message = _message()
    with Stubber(sender._client) as stub:
        stub.add_response(
            "send_email",
            {"MessageId": "0100018f-abc"},
            expected_params={
                "FromEmailAddress": "lf-y36e@mb-mail.abcmortgage.test",
                "Content": {"Raw": {"Data": message.as_bytes()}},
                "ConfigurationSetName": "mbai-test-outbound",
            },
        )
        assert sender.send(message) == "0100018f-abc"
        stub.assert_no_pending_responses()


def test_ses_makes_exactly_one_attempt() -> None:
    """A retry after SES accepted the email but the answer was lost sends it twice.

    Counted on the wire, not read off the config: SES answers 500 (which botocore retries by
    default) and exactly one request may go out. `{"max_attempts": 1}` sends two."""
    from botocore.awsrequest import AWSResponse

    sender = SesMailSender()
    requests: list[str] = []

    def answer_500(request: Any, **_: Any) -> AWSResponse:
        requests.append(request.url)
        return AWSResponse(request.url, 500, {}, MagicMock(content=b"{}", stream=lambda: iter([])))

    sender._client.meta.events.register("before-send.sesv2.SendEmail", answer_500)
    with pytest.raises(SendError):
        sender.send(_message())

    assert len(requests) == 1
    config = sender._client.meta.config
    assert (config.connect_timeout, config.read_timeout) == (5, 30)
    assert sender._client.meta.region_name == "us-east-1"


@pytest.mark.parametrize(
    "code",
    ["MessageRejected", "AccountSendingPausedException", "MailFromDomainNotVerifiedException"],
)
def test_an_ses_refusal_is_a_transport_error_with_the_code(code: str) -> None:
    sender = SesMailSender()
    with Stubber(sender._client) as stub:
        stub.add_client_error("send_email", service_error_code=code, http_status_code=400)
        with pytest.raises(SendError) as caught:
            sender.send(_message())
    assert isinstance(caught.value, TransportError)
    assert caught.value.code == code
    assert caught.value.outcome_unknown is False


def test_a_lost_answer_is_outcome_unknown_and_a_failed_connect_is_not() -> None:
    sender = SesMailSender(client=MagicMock())
    sender._client.send_email.side_effect = ReadTimeoutError(endpoint_url="https://ses")
    with pytest.raises(SendError) as lost:
        sender.send(_message())
    assert (lost.value.code, lost.value.outcome_unknown) == ("ReadTimeoutError", True)

    sender._client.send_email.side_effect = EndpointConnectionError(endpoint_url="https://ses")
    with pytest.raises(SendError) as unreached:
        sender.send(_message())
    assert (unreached.value.code, unreached.value.outcome_unknown) == (
        "EndpointConnectionError",
        False,
    )


@pytest.mark.parametrize(
    ("error", "unknown"),
    [
        # The request may have been written: SES may have the email.
        (ReadTimeoutError(endpoint_url="https://ses"), True),
        (ConnectionClosedError(endpoint_url="https://ses"), True),
        (SSLError(endpoint_url="https://ses", error="eof"), True),
        # botocore's catch-all for any other exception mid-request: the case a list of the risky
        # errors missed.
        (HTTPClientError(error="boom"), True),
        # No connection was ever made, or nothing was sent at all.
        (EndpointConnectionError(endpoint_url="https://ses"), False),
        (ConnectTimeoutError(endpoint_url="https://ses"), False),
        (ProxyConnectionError(proxy_url="https://proxy"), False),
        (NoCredentialsError(), False),
    ],
    ids=lambda v: type(v).__name__ if isinstance(v, BotoCoreError) else str(v),
)
def test_ses_network_failures_are_unknown_unless_nothing_was_sent(
    error: BotoCoreError, unknown: bool
) -> None:
    sender = SesMailSender(client=MagicMock())
    sender._client.send_email.side_effect = error
    with pytest.raises(SendError) as caught:
        sender.send(_message())
    assert (caught.value.code, caught.value.outcome_unknown) == (type(error).__name__, unknown)


def test_ses_refuses_without_a_configuration_set(monkeypatch: pytest.MonkeyPatch) -> None:
    client = MagicMock()
    monkeypatch.setattr(settings, "ses_configuration_set", None)

    with pytest.raises(SendError, match="ConfigurationSetMissing"):
        SesMailSender(client=client).send(_message())
    client.send_email.assert_not_called()


def test_a_failure_logs_the_code_and_never_the_message(caplog: pytest.LogCaptureFixture) -> None:
    import structlog.testing

    sender = SesMailSender()
    with Stubber(sender._client) as stub, structlog.testing.capture_logs() as logs:
        stub.add_client_error("send_email", service_error_code="MessageRejected")
        with pytest.raises(SendError):
            sender.send(_message())
    assert logs == [
        {"event": "ses_send_refused", "error_code": "MessageRejected", "log_level": "warning"}
    ]


def test_smtp_sends_once_and_returns_the_message_id(monkeypatch: pytest.MonkeyPatch) -> None:
    smtp = MagicMock()
    monkeypatch.setattr(mail_sender.smtplib, "SMTP", smtp)
    monkeypatch.setattr(settings, "smtp_host", "mailhog")
    monkeypatch.setattr(settings, "smtp_port", 1025)
    message = _message()

    assert SmtpMailSender().send(message) == message["Message-ID"]
    smtp.assert_called_once_with("mailhog", 1025, timeout=10)
    smtp.return_value.send_message.assert_called_once_with(message)
    smtp.return_value.quit.assert_called_once_with()


def test_an_smtp_connect_failure_is_a_clean_transport_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    smtp = MagicMock(side_effect=ConnectionRefusedError())
    monkeypatch.setattr(mail_sender.smtplib, "SMTP", smtp)
    with pytest.raises(SendError) as caught:
        SmtpMailSender().send(_message())
    assert isinstance(caught.value, TransportError)
    assert (caught.value.code, caught.value.outcome_unknown) == ("ConnectionRefusedError", False)


@pytest.mark.parametrize(
    ("error", "unknown"),
    [
        # The server answered with a refusal: it did not take the message.
        (smtplib.SMTPRecipientsRefused({"b@x.test": (550, b"no")}), False),
        (smtplib.SMTPDataError(554, b"rejected"), False),
        (smtplib.SMTPSenderRefused(550, b"no", "lf@x.test"), False),
        # The connection went quiet or away while the message was being handed over.
        (TimeoutError(), True),
        (smtplib.SMTPServerDisconnected(), True),
        (ConnectionResetError(), True),
    ],
    ids=lambda v: type(v).__name__ if isinstance(v, Exception) else str(v),
)
def test_an_smtp_failure_mid_send_is_unknown_unless_refused(
    error: Exception, unknown: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    smtp = MagicMock()
    smtp.return_value.send_message.side_effect = error
    monkeypatch.setattr(mail_sender.smtplib, "SMTP", smtp)
    with pytest.raises(SendError) as caught:
        SmtpMailSender().send(_message())
    assert (caught.value.code, caught.value.outcome_unknown) == (type(error).__name__, unknown)


def test_a_failed_smtp_quit_after_a_send_is_still_sent(monkeypatch: pytest.MonkeyPatch) -> None:
    smtp = MagicMock()
    smtp.return_value.quit.side_effect = smtplib.SMTPServerDisconnected()
    monkeypatch.setattr(mail_sender.smtplib, "SMTP", smtp)
    message = _message()
    assert SmtpMailSender().send(message) == message["Message-ID"]
    smtp.return_value.close.assert_called_once_with()


@pytest.mark.parametrize(
    ("transport", "kind"), [("ses", SesMailSender), ("smtp", SmtpMailSender), (None, type(None))]
)
def test_get_mail_sender(
    transport: str | None, kind: type, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "mail_transport", transport)
    assert type(get_mail_sender()) is kind


def test_blank_transport_settings_read_as_unset() -> None:
    from app.core.config import Settings

    loaded = Settings(
        **(settings.model_dump() | {"mail_transport": " ", "ses_configuration_set": ""})
    )
    assert (loaded.mail_transport, loaded.ses_configuration_set) == (None, None)


def test_the_script_refuses_without_a_sender(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mail_transport", None)
    assert send_test_email.main(["--to", "borrower@example.test"]) == 1


def test_the_script_sends_only_to_the_simulator_through_ses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[Any] = []

    class _Recording(SesMailSender):
        def __init__(self) -> None:
            pass

        def send(self, message: Any) -> str:
            sent.append(message)
            return "sim-id"

    monkeypatch.setattr(settings, "mail_transport", "ses")
    monkeypatch.setattr(send_test_email, "get_mail_sender", _Recording)

    assert send_test_email.main(["--to", "someone@gmail.com"]) == 1
    assert sent == []
    # A list ending in a simulator address passes the suffix check; build_mime refuses it as more
    # than one address, so nothing is sent.
    with pytest.raises(ValueError, match="not one email address"):
        send_test_email.main(["--to", "someone@gmail.com, x@simulator.amazonses.com"])
    assert sent == []
    # The control: the simulator address goes through.
    assert send_test_email.main(["--to", "success@simulator.amazonses.com"]) == 0
    assert len(sent) == 1
