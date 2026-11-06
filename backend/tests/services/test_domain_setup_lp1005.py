"""LP-1005 — setting up a customer's mail subdomain.

- The real provider against stubbed Route 53 and SES v2 (botocore's Stubber): the exact zone,
  identity, MAIL FROM and record batch; "already exists" finds the same zone and reads the tokens.
- `is_delegated` against a mocked resolver.
- `advance_mail_domain`, stage by stage, with the fake and a recording provider: resume after a crash,
  nothing created twice, hand-linked rows untouched.
- The command's refusals and what it prints, and what `_main` prints for each kind of stop.
- The LP-991 hand-link refuses a row this setup owns (review #1).
- `--replace` corrects a mistyped pending domain; a root domain is refused (second review #1, #2).
"""

from __future__ import annotations

import argparse
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

import dns.exception
import dns.resolver
import pytest
from app.core.config import settings
from app.models.company_mail_domain import CompanyMailDomain, MailDomainStatus
from app.scripts import set_up_mail_domain as command
from app.scripts.set_company_mail_domain import run as hand_link
from app.services import domain_provider as dp
from app.services.domain_provider import (
    DomainProviderNotAllowed,
    DomainSetupError,
    FakeDomainProvider,
    Route53DomainProvider,
    get_domain_provider,
)
from app.services.mail_domain import (
    MailDomainError,
    advance_mail_domain,
    caller_reference,
    file_address,
    set_company_mail_domain,
)
from botocore.exceptions import ConnectTimeoutError, NoCredentialsError
from botocore.stub import Stubber
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.mail_address import link_mail_domain
from tests.outbound_send import ready_to_send

SUB = "mb-mail.abcmortgage.test"
REF = "mb-00000000-0000-0000-0000-000000000001-mb-mail.abcmortgage.test"
NS = ["ns-1.awsdns-01.org", "ns-2.awsdns-02.co.uk", "ns-3.awsdns-03.com", "ns-4.awsdns-04.net"]
TOKENS = ["tok1", "tok2", "tok3"]


@pytest.fixture(autouse=True)
def _aws(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    monkeypatch.setattr(settings, "s3_region", "us-east-1")


def _provider(resolver: Any | None = None) -> Route53DomainProvider:
    return Route53DomainProvider(resolver=resolver or _Resolver(NS))


def _zone(zone_id: str, ref: str, name: str = SUB + ".") -> dict[str, Any]:
    return {"Id": f"/hostedzone/{zone_id}", "Name": name, "CallerReference": ref}


# --------------------------------------------------------------------------------------------- #
# The real provider, stubbed
# --------------------------------------------------------------------------------------------- #
def test_create_zone_sends_the_reference_and_returns_the_bare_id() -> None:
    provider = _provider()
    with Stubber(provider._route53) as stub:
        stub.add_response(
            "create_hosted_zone",
            {
                "HostedZone": _zone("Z123", REF),
                "ChangeInfo": {
                    "Id": "/change/C1",
                    "Status": "PENDING",
                    "SubmittedAt": "2026-11-01",
                },
                "DelegationSet": {"NameServers": NS},
                "Location": "https://route53.amazonaws.com/2013-04-01/hostedzone/Z123",
            },
            expected_params={
                "Name": SUB,
                "CallerReference": REF,
                "HostedZoneConfig": {"Comment": "MortgageBoss mail domain (set_up_mail_domain)"},
            },
        )
        assert provider.create_zone(SUB, REF) == ("Z123", NS)
        stub.assert_no_pending_responses()


def test_an_existing_zone_for_the_same_reference_is_found_not_made_again() -> None:
    provider = _provider()
    with Stubber(provider._route53) as stub:
        stub.add_client_error("create_hosted_zone", service_error_code="HostedZoneAlreadyExists")
        stub.add_response(
            "list_hosted_zones_by_name",
            {
                "HostedZones": [
                    # Same name, another request: not ours.
                    _zone("ZOTHER", "someone-else"),
                    _zone("Z123", REF),
                ],
                "IsTruncated": False,
                "MaxItems": "100",
            },
            expected_params={"DNSName": SUB},
        )
        stub.add_response(
            "get_hosted_zone",
            {"HostedZone": _zone("Z123", REF), "DelegationSet": {"NameServers": NS}},
            expected_params={"Id": "Z123"},
        )
        assert provider.create_zone(SUB, REF) == ("Z123", NS)
        stub.assert_no_pending_responses()


def test_another_route53_refusal_is_a_setup_error_with_the_code() -> None:
    provider = _provider()
    with Stubber(provider._route53) as stub:
        stub.add_client_error("create_hosted_zone", service_error_code="InvalidDomainName")
        with pytest.raises(DomainSetupError) as raised:
            provider.create_zone(SUB, REF)
    assert raised.value.code == "InvalidDomainName"
    assert raised.value.retryable is False


@pytest.mark.parametrize(
    ("code", "http_status", "retryable"),
    [
        ("Throttling", 400, True),
        ("PriorRequestNotComplete", 400, True),
        ("ServiceUnavailable", 503, True),
        ("SomethingNew", 500, True),
        ("AccessDenied", 403, False),
        ("InvalidDomainName", 400, False),
    ],
)
def test_only_a_busy_aws_is_retryable(code: str, http_status: int, retryable: bool) -> None:
    provider = _provider()
    with Stubber(provider._route53) as stub:
        stub.add_client_error(
            "create_hosted_zone", service_error_code=code, http_status_code=http_status
        )
        with pytest.raises(DomainSetupError) as raised:
            provider.create_zone(SUB, REF)
    assert (raised.value.code, raised.value.retryable) == (code, retryable)


class _Raises:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    def get_email_identity(self, **_: Any) -> None:
        raise self.exc


@pytest.mark.parametrize(
    ("exc", "retryable"),
    [
        (ConnectTimeoutError(endpoint_url="https://route53.amazonaws.com"), True),
        (NoCredentialsError(), False),
    ],
)
def test_a_timeout_is_retryable_and_missing_credentials_are_not(
    exc: Exception, retryable: bool
) -> None:
    provider = _provider()
    with pytest.raises(DomainSetupError) as raised:
        provider._call(SUB, _Raises(exc), "get_email_identity", EmailIdentity=SUB)
    assert (raised.value.code, raised.value.retryable) == (type(exc).__name__, retryable)


def _expected_records() -> list[dict[str, Any]]:
    def rr(name: str, kind: str, value: str) -> dict[str, Any]:
        return {
            "Action": "UPSERT",
            "ResourceRecordSet": {
                "Name": name,
                "Type": kind,
                "TTL": 300,
                "ResourceRecords": [{"Value": value}],
            },
        }

    return [
        rr(f"tok1._domainkey.{SUB}", "CNAME", "tok1.dkim.amazonses.com"),
        rr(f"tok2._domainkey.{SUB}", "CNAME", "tok2.dkim.amazonses.com"),
        rr(f"tok3._domainkey.{SUB}", "CNAME", "tok3.dkim.amazonses.com"),
        rr(SUB, "MX", "10 inbound-smtp.us-east-1.amazonaws.com"),
        rr(f"bounce.{SUB}", "MX", "10 feedback-smtp.us-east-1.amazonses.com"),
        rr(f"bounce.{SUB}", "TXT", '"v=spf1 include:amazonses.com ~all"'),
        rr(f"_dmarc.{SUB}", "TXT", '"v=DMARC1; p=reject"'),
    ]


def _identity(tokens: list[str]) -> dict[str, Any]:
    return {
        "IdentityType": "DOMAIN",
        "VerifiedForSendingStatus": False,
        "DkimAttributes": {"Status": "PENDING", "Tokens": tokens},
    }


def _stub_mail_from_and_records(ses: Stubber, r53: Stubber) -> None:
    ses.add_response(
        "put_email_identity_mail_from_attributes",
        {},
        expected_params={
            "EmailIdentity": SUB,
            "MailFromDomain": f"bounce.{SUB}",
            "BehaviorOnMxFailure": "USE_DEFAULT_VALUE",
        },
    )
    r53.add_response(
        "change_resource_record_sets",
        {"ChangeInfo": {"Id": "/change/C2", "Status": "PENDING", "SubmittedAt": "2026-11-01"}},
        expected_params={
            "HostedZoneId": "Z123",
            "ChangeBatch": {
                "Comment": "MortgageBoss mail records (set_up_mail_domain)",
                "Changes": _expected_records(),
            },
        },
    )


def test_identity_mail_from_and_every_record_in_one_batch() -> None:
    provider = _provider()
    with Stubber(provider._sesv2) as ses, Stubber(provider._route53) as r53:
        ses.add_response(
            "create_email_identity",
            _identity(TOKENS),
            expected_params={"EmailIdentity": SUB},
        )
        _stub_mail_from_and_records(ses, r53)
        provider.set_up_identity_and_records(SUB, "Z123")
        ses.assert_no_pending_responses()
        r53.assert_no_pending_responses()


def test_the_dmarc_record_rejects_and_asks_for_no_reports() -> None:
    (dmarc,) = [r for r in dp.records(SUB, TOKENS, "us-east-1") if r["Name"].startswith("_dmarc.")]
    (value,) = [v["Value"] for v in dmarc["ResourceRecords"]]
    assert "p=reject" in value
    assert "rua" not in value


def test_an_existing_identity_is_read_for_its_tokens() -> None:
    provider = _provider()
    with Stubber(provider._sesv2) as ses, Stubber(provider._route53) as r53:
        ses.add_client_error("create_email_identity", service_error_code="AlreadyExistsException")
        ses.add_response(
            "get_email_identity", _identity(TOKENS), expected_params={"EmailIdentity": SUB}
        )
        _stub_mail_from_and_records(ses, r53)
        provider.set_up_identity_and_records(SUB, "Z123")
        ses.assert_no_pending_responses()
        r53.assert_no_pending_responses()


@pytest.mark.parametrize(
    ("dkim", "sending", "verified"),
    [("SUCCESS", True, True), ("PENDING", False, False), ("SUCCESS", False, False)],
)
def test_is_verified_needs_dkim_success_and_sending(
    dkim: str, sending: bool, verified: bool
) -> None:
    provider = _provider()
    with Stubber(provider._sesv2) as ses:
        ses.add_response(
            "get_email_identity",
            {
                "IdentityType": "DOMAIN",
                "VerifiedForSendingStatus": sending,
                "DkimAttributes": {"Status": dkim, "Tokens": TOKENS},
            },
            expected_params={"EmailIdentity": SUB},
        )
        assert provider.is_verified(SUB) is verified


# --------------------------------------------------------------------------------------------- #
# is_delegated, against a mocked resolver
# --------------------------------------------------------------------------------------------- #
class _Target:
    def __init__(self, name: str) -> None:
        self.target = name


class _Resolver:
    def __init__(self, answer: list[str] | None = None, error: Exception | None = None) -> None:
        self.answer = answer or []
        self.error = error
        self.asked: list[tuple[str, str]] = []

    def resolve(self, name: str, kind: str) -> list[_Target]:
        self.asked.append((name, kind))
        if self.error is not None:
            raise self.error
        return [_Target(value) for value in self.answer]


def test_delegated_when_the_ns_answer_is_ours() -> None:
    # Public DNS answers in any order, may upper-case, and ends each name with a dot.
    answer = [name.upper() + "." for name in reversed(NS)]
    resolver = _Resolver(answer)
    assert _provider(resolver).is_delegated(SUB, NS) is True
    assert resolver.asked == [(SUB, "NS")]


@pytest.mark.parametrize(
    "resolver",
    [
        _Resolver(["ns-1.other-dns.com.", "ns-2.other-dns.com."]),
        _Resolver(NS[:3]),
        _Resolver(error=dns.resolver.NXDOMAIN()),
        _Resolver(error=dns.exception.Timeout()),
        _Resolver(error=dns.resolver.NoAnswer()),
    ],
    ids=["wrong nameservers", "three of four", "NXDOMAIN", "timeout", "no answer"],
)
def test_not_delegated(resolver: _Resolver) -> None:
    assert _provider(resolver).is_delegated(SUB, NS) is False


def test_the_fake_refuses_outside_development(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "domain_provider", "fake")
    assert isinstance(get_domain_provider(), FakeDomainProvider)
    monkeypatch.setattr(settings, "environment", "staging")
    with pytest.raises(DomainProviderNotAllowed, match="Set DOMAIN_PROVIDER=route53"):
        get_domain_provider()


# --------------------------------------------------------------------------------------------- #
# advance_mail_domain
# --------------------------------------------------------------------------------------------- #
class Recording(FakeDomainProvider):
    """The fake, counting each call; `delegated`, `verified` and `fail_identity` steer it."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.delegated = True
        self.verified = True
        self.fail_identity = False

    def create_zone(self, subdomain: str, caller_reference: str) -> tuple[str, list[str]]:
        self.calls.append("create_zone")
        return super().create_zone(subdomain, caller_reference)

    def is_delegated(self, subdomain: str, nameservers: list[str]) -> bool:
        self.calls.append("is_delegated")
        return self.delegated

    def set_up_identity_and_records(self, subdomain: str, zone_id: str) -> None:
        self.calls.append("set_up_identity_and_records")
        if self.fail_identity:
            raise DomainSetupError("Throttling", subdomain)

    def is_verified(self, subdomain: str) -> bool:
        self.calls.append("is_verified")
        return self.verified


async def _new_row(db: AsyncSession) -> tuple[Any, CompanyMailDomain]:
    ready = await ready_to_send(db, with_domain=False)
    row = CompanyMailDomain(
        company_id=ready.company.id,
        domain=f"mb-mail-{uuid4().hex[:8]}.example.test",
        status=MailDomainStatus.PENDING_NS,
    )
    db.add(row)
    await db.flush()
    return ready, row


async def test_each_stage_with_the_fake_ends_active_with_an_address(
    db_session: AsyncSession,
) -> None:
    ready, row = await _new_row(db_session)
    provider = FakeDomainProvider()
    assert await file_address(db_session, ready.loan_file) is None  # the control

    assert await advance_mail_domain(db_session, row, provider) is MailDomainStatus.PENDING_NS
    assert row.zone_id is not None
    assert row.nameservers == list(FakeDomainProvider.NAMESERVERS)
    assert await file_address(db_session, ready.loan_file) is None

    assert await advance_mail_domain(db_session, row, provider) is MailDomainStatus.VERIFYING
    assert row.sending_enabled is False
    assert await file_address(db_session, ready.loan_file) is None

    assert await advance_mail_domain(db_session, row, provider) is MailDomainStatus.ACTIVE
    assert row.sending_enabled is True
    assert await file_address(db_session, ready.loan_file) == (
        f"{ready.loan_file.display_id.lower()}@{row.domain}"
    )


async def test_waits_while_the_ns_record_is_not_live(db_session: AsyncSession) -> None:
    _, row = await _new_row(db_session)
    provider = Recording()
    provider.delegated = False
    await advance_mail_domain(db_session, row, provider)
    assert await advance_mail_domain(db_session, row, provider) is MailDomainStatus.PENDING_NS
    assert provider.calls == ["create_zone", "is_delegated"]


async def test_waits_while_aws_verifies(db_session: AsyncSession) -> None:
    _, row = await _new_row(db_session)
    provider = Recording()
    provider.verified = False
    for _ in range(3):
        await advance_mail_domain(db_session, row, provider)
    assert row.status is MailDomainStatus.VERIFYING
    assert row.sending_enabled is False


async def test_a_crash_between_stages_resumes_without_a_second_zone(
    db_session: AsyncSession,
) -> None:
    _, row = await _new_row(db_session)
    provider = Recording()
    provider.fail_identity = True
    await advance_mail_domain(db_session, row, provider)  # zone created and saved
    zone_id = row.zone_id
    with pytest.raises(DomainSetupError):
        await advance_mail_domain(db_session, row, provider)
    assert row.status is MailDomainStatus.PENDING_NS

    provider.fail_identity = False
    await advance_mail_domain(db_session, row, provider)
    await advance_mail_domain(db_session, row, provider)
    assert row.status is MailDomainStatus.ACTIVE
    assert row.zone_id == zone_id
    assert provider.calls.count("create_zone") == 1


@pytest.mark.parametrize(
    "status",
    [
        MailDomainStatus.ACTIVE,
        MailDomainStatus.INACTIVE,
        MailDomainStatus.VERIFYING,
        MailDomainStatus.PROBLEM,
    ],
)
async def test_a_hand_linked_row_is_never_touched(
    db_session: AsyncSession, status: MailDomainStatus
) -> None:
    ready = await ready_to_send(db_session, with_domain=False)
    await link_mail_domain(db_session, ready.company.id)
    row = await db_session.scalar(
        select(CompanyMailDomain).where(CompanyMailDomain.company_id == ready.company.id)
    )
    assert row is not None and row.zone_id is None and row.sending_enabled is False
    row.status = status
    provider = Recording()
    assert await advance_mail_domain(db_session, row, provider) is status
    assert provider.calls == []
    assert row.sending_enabled is False


async def test_an_active_domain_switched_off_stays_off(db_session: AsyncSession) -> None:
    """The switch is the emergency off (decision 10-31): only the move to active turns it on."""
    _, row = await _new_row(db_session)
    provider = Recording()
    for _ in range(3):
        await advance_mail_domain(db_session, row, provider)
    assert row.status is MailDomainStatus.ACTIVE
    row.sending_enabled = False
    await advance_mail_domain(db_session, row, provider)
    assert row.sending_enabled is False


def test_the_caller_reference_is_stable_and_fits() -> None:
    company_id = uuid4()
    assert caller_reference(company_id, SUB) == f"mb-{company_id}-{SUB}"
    assert caller_reference(company_id, SUB) == caller_reference(company_id, SUB)
    long_domain = ".".join(["a" * 60] * 4) + ".test"
    reference = caller_reference(company_id, long_domain)
    assert len(reference) <= 128
    assert reference == caller_reference(company_id, long_domain)


# --------------------------------------------------------------------------------------------- #
# The command
# --------------------------------------------------------------------------------------------- #
async def test_the_command_runs_to_active_and_prints_the_ns_record(
    db_session: AsyncSession,
) -> None:
    ready = await ready_to_send(db_session, with_domain=False)
    provider = Recording()
    company, row, created, _ = await command.run(
        db_session, company_ref=str(ready.company.id), subdomain=SUB.upper(), provider=provider
    )
    assert row.domain == SUB and row.status is MailDomainStatus.ACTIVE and created
    text = "\n".join(command.describe(company, row, zone_created=created))
    assert f"Name: {SUB}   Type: NS" in text
    assert all(name in text for name in FakeDomainProvider.NAMESERVERS)
    assert f"Active. Files of {company.name} now use lf-…@{SUB}." in text

    # Again: nothing created twice, and it says Active without the NS record.
    company, row, created, _ = await command.run(
        db_session, company_ref=str(ready.company.id), subdomain=SUB, provider=provider
    )
    assert not created
    assert provider.calls.count("create_zone") == 1
    assert provider.calls.count("set_up_identity_and_records") == 1
    assert "Type: NS" not in "\n".join(command.describe(company, row, zone_created=created))


async def test_the_command_stops_at_pending_ns_with_what_to_do(db_session: AsyncSession) -> None:
    ready = await ready_to_send(db_session, with_domain=False)
    provider = Recording()
    provider.delegated = False
    company, row, created, _ = await command.run(
        db_session, company_ref=str(ready.company.id), subdomain=SUB, provider=provider
    )
    lines = command.describe(company, row, zone_created=created)
    assert row.status is MailDomainStatus.PENDING_NS
    assert lines[1] == "Ask the customer to add this record at their DNS provider:"
    assert lines[-1] == "Then run this command again (or wait for the hourly check)."


@pytest.mark.parametrize("subdomain", ["mortgageboss.ai", "mb-mail.staging.mortgageboss.ai"])
async def test_the_command_refuses_our_own_domain(db_session: AsyncSession, subdomain: str) -> None:
    ready = await ready_to_send(db_session, with_domain=False)
    with pytest.raises(MailDomainError, match=re.escape("is under mortgageboss.ai")):
        await command.run(
            db_session, company_ref=str(ready.company.id), subdomain=subdomain, provider=Recording()
        )


async def test_the_command_refuses_another_companys_subdomain(db_session: AsyncSession) -> None:
    owner = await ready_to_send(db_session, with_domain=False)
    taken = await link_mail_domain(db_session, owner.company.id)
    other = await ready_to_send(db_session, with_domain=False)
    with pytest.raises(MailDomainError, match="already belongs to another company"):
        await command.run(
            db_session,
            company_ref=str(other.company.id),
            subdomain=taken,
            provider=Recording(),
            custom_subdomain=True,
        )


async def test_the_command_refuses_a_company_with_a_different_domain(
    db_session: AsyncSession,
) -> None:
    ready = await ready_to_send(db_session)
    provider = Recording()
    with pytest.raises(
        MailDomainError, match="changing a domain past pending_ns is manual for now"
    ):
        await command.run(
            db_session, company_ref=str(ready.company.id), subdomain=SUB, provider=provider
        )
    assert provider.calls == []


# --------------------------------------------------------------------------------------------- #
# What `_main` prints (review #2, #3)
# --------------------------------------------------------------------------------------------- #
_ARGS = argparse.Namespace(company="Any Co", subdomain=SUB, replace=False, custom_subdomain=False)


def _no_db() -> None:
    raise AssertionError("the database was opened")


async def test_the_fake_in_staging_says_which_setting_to_change(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(settings, "environment", "staging")
    monkeypatch.setattr(settings, "domain_provider", "fake")
    monkeypatch.setattr(command, "async_session_maker", _no_db)

    assert await command._main(_ARGS) == 1
    err = capsys.readouterr().err
    assert err == (
        "Refused: DOMAIN_PROVIDER is 'fake', which only runs in development (this is staging). "
        "Set DOMAIN_PROVIDER=route53.\n"
    )

    # The positive control: with route53 it gets past the check, to the database.
    monkeypatch.setattr(settings, "domain_provider", "route53")
    with pytest.raises(AssertionError, match="database was opened"):
        await command._main(_ARGS)


@pytest.mark.parametrize(
    ("retryable", "advice"),
    [
        (True, "Run the command again to resume."),
        (False, "AWS refused it, so running again fails the same way; this needs a fix first."),
    ],
)
async def test_a_stop_says_whether_running_again_helps(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    retryable: bool,
    advice: str,
) -> None:
    @asynccontextmanager
    async def session() -> AsyncIterator[None]:
        yield None

    async def stopped(*_: Any, **__: Any) -> None:
        raise DomainSetupError("SomeCode", SUB, retryable=retryable)

    monkeypatch.setattr(settings, "domain_provider", "fake")
    monkeypatch.setattr(command, "async_session_maker", session)
    monkeypatch.setattr(command, "run", stopped)

    assert await command._main(_ARGS) == 2
    assert capsys.readouterr().err == (
        f"Stopped: AWS did not complete the step for {SUB} (SomeCode). {advice}\n"
    )


# --------------------------------------------------------------------------------------------- #
# The LP-991 hand-link leaves a set-up row alone (review #1)
# --------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("stages", [0, 1, 2, 3])
async def test_the_hand_link_refuses_a_row_this_setup_owns(
    db_session: AsyncSession, stages: int
) -> None:
    """0: pending_ns with no zone yet (a crash before the zone); 1: pending_ns with a zone;
    2: verifying; 3: active. The domain, zone and status must all be left as they were."""
    ready, row = await _new_row(db_session)
    for _ in range(stages):
        await advance_mail_domain(db_session, row, FakeDomainProvider())
    before = (row.domain, row.status, row.zone_id, row.nameservers)

    with pytest.raises(MailDomainError, match="is managed by set_up_mail_domain"):
        await set_company_mail_domain(
            db_session, company_id=ready.company.id, domain="other-domain.example.test"
        )
    with pytest.raises(MailDomainError, match="is managed by set_up_mail_domain"):
        await hand_link(db_session, company_ref=str(ready.company.id), domain=row.domain)
    await db_session.refresh(row)
    assert (row.domain, row.status, row.zone_id, row.nameservers) == before


async def test_the_hand_link_still_changes_a_hand_linked_row(db_session: AsyncSession) -> None:
    """The control: a row with no zone, linked by hand, is still the hand-link's to change."""
    ready = await ready_to_send(db_session, with_domain=False)
    await link_mail_domain(db_session, ready.company.id)
    _, row = await hand_link(
        db_session, company_ref=str(ready.company.id), domain="mail.relinked.test", inactive=True
    )
    assert (row.domain, row.status) == ("mail.relinked.test", MailDomainStatus.INACTIVE)


# --------------------------------------------------------------------------------------------- #
# Correcting a typo, and refusing a root domain (second review #1, #2)
# --------------------------------------------------------------------------------------------- #
TYPO = "mb-mail.abcmortage.test"


def _args(company: Any, subdomain: str, **flags: bool) -> argparse.Namespace:
    return argparse.Namespace(
        company=str(company.id),
        subdomain=subdomain,
        replace=flags.get("replace", False),
        custom_subdomain=flags.get("custom_subdomain", False),
    )


@pytest.fixture
def real_main(monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession) -> Recording:
    """`_main` on the test's session, with a provider that stops at pending_ns."""

    @asynccontextmanager
    async def session() -> AsyncIterator[AsyncSession]:
        yield db_session

    provider = Recording()
    provider.delegated = False
    monkeypatch.setattr(command, "async_session_maker", session)
    monkeypatch.setattr(command, "get_domain_provider", lambda: provider)
    return provider


async def test_a_typo_is_refused_then_replaced_with_what_to_clean_up(
    db_session: AsyncSession, capsys: pytest.CaptureFixture[str], real_main: Recording
) -> None:
    ready = await ready_to_send(db_session, with_domain=False)
    assert await command._main(_args(ready.company, TYPO)) == 0
    row = await db_session.scalar(
        select(CompanyMailDomain).where(CompanyMailDomain.company_id == ready.company.id)
    )
    assert row is not None
    old_zone = row.zone_id
    assert old_zone is not None
    capsys.readouterr()

    # Without the flag: refused, unchanged, and it says how.
    assert await command._main(_args(ready.company, SUB)) == 1
    assert "To correct it, run this again with --replace." in capsys.readouterr().err
    assert (row.domain, row.zone_id) == (TYPO, old_zone)

    assert await command._main(_args(ready.company, SUB, replace=True)) == 0
    out = capsys.readouterr().out
    assert f"Replaced {TYPO}; nothing uses it now." in out
    assert f"Route 53 zone {old_zone}, and the SES identity {TYPO}" in out
    assert f"Name: {SUB}   Type: NS" in out
    assert row.domain == SUB and row.status is MailDomainStatus.PENDING_NS
    assert row.zone_id is not None and row.zone_id != old_zone
    assert real_main.calls.count("create_zone") == 2

    # Running the corrected domain again replaces nothing.
    assert await command._main(_args(ready.company, SUB, replace=True)) == 0
    assert "Replaced" not in capsys.readouterr().out
    assert real_main.calls.count("create_zone") == 2


@pytest.mark.parametrize(
    "status",
    [
        MailDomainStatus.VERIFYING,
        MailDomainStatus.ACTIVE,
        MailDomainStatus.PROBLEM,
        MailDomainStatus.INACTIVE,
    ],
)
async def test_replace_refuses_past_pending_ns(
    db_session: AsyncSession, status: MailDomainStatus
) -> None:
    ready, row = await _new_row(db_session)
    await advance_mail_domain(db_session, row, FakeDomainProvider())
    row.status = status
    before = (row.domain, row.zone_id, row.nameservers)
    with pytest.raises(MailDomainError, match="past pending_ns is manual"):
        await command.run(
            db_session,
            company_ref=str(ready.company.id),
            subdomain=SUB,
            provider=Recording(),
            replace=True,
        )
    assert (row.domain, row.zone_id, row.nameservers) == before


async def test_replace_refuses_another_companys_domain(db_session: AsyncSession) -> None:
    owner = await ready_to_send(db_session, with_domain=False)
    await command.run(
        db_session, company_ref=str(owner.company.id), subdomain=SUB, provider=Recording()
    )
    ready, row = await _new_row(db_session)
    before = row.domain
    with pytest.raises(MailDomainError, match="already belongs to another company"):
        await command.run(
            db_session,
            company_ref=str(ready.company.id),
            subdomain=SUB,
            provider=Recording(),
            replace=True,
        )
    assert row.domain == before


@pytest.mark.parametrize(
    "subdomain",
    ["abcmortgage.test", "abcmortgage.co.uk", "co.uk", "mb-mail.com", "email.abcmortgage.test"],
)
async def test_a_root_domain_or_other_prefix_is_refused_before_any_aws_call(
    db_session: AsyncSession, subdomain: str
) -> None:
    ready = await ready_to_send(db_session, with_domain=False)
    provider = Recording()
    with pytest.raises(MailDomainError, match="doesn't look like a subdomain"):
        await command.run(
            db_session, company_ref=str(ready.company.id), subdomain=subdomain, provider=provider
        )
    assert provider.calls == []
    assert (
        await db_session.scalar(
            select(CompanyMailDomain).where(CompanyMailDomain.company_id == ready.company.id)
        )
        is None
    )


async def test_the_flag_allows_a_customers_prefix_but_never_two_labels(
    db_session: AsyncSession,
) -> None:
    ready = await ready_to_send(db_session, with_domain=False)
    with pytest.raises(MailDomainError, match="doesn't look like a subdomain"):
        await command.run(
            db_session,
            company_ref=str(ready.company.id),
            subdomain="abcmortgage.test",
            provider=Recording(),
            custom_subdomain=True,
        )
    # The control: the flag does let a customer's own prefix through.
    _, row, _, _ = await command.run(
        db_session,
        company_ref=str(ready.company.id),
        subdomain="email.abcmortgage.test",
        provider=Recording(),
        custom_subdomain=True,
    )
    assert row.domain == "email.abcmortgage.test"


async def test_replace_also_refuses_a_root_domain(db_session: AsyncSession) -> None:
    ready, row = await _new_row(db_session)
    before = row.domain
    with pytest.raises(MailDomainError, match="doesn't look like a subdomain"):
        await command.run(
            db_session,
            company_ref=str(ready.company.id),
            subdomain="abcmortgage.test",
            provider=Recording(),
            replace=True,
        )
    assert row.domain == before


def test_the_flags_reach_main(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[argparse.Namespace] = []

    async def fake_main(args: argparse.Namespace) -> int:
        seen.append(args)
        return 0

    monkeypatch.setattr(command, "_main", fake_main)
    assert command.main(["Co", SUB]) == 0
    assert command.main(["Co", SUB, "--replace", "--custom-subdomain"]) == 0
    assert [(a.replace, a.custom_subdomain) for a in seen] == [(False, False), (True, True)]
