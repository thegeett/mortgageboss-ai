"""Where a customer's mail domain is set up: the Route 53 zone, the SES identity, the DNS records
(LP-1005).

Two versions, chosen by `settings.domain_provider`:

- `Route53DomainProvider` (staging): real AWS. One attempt per call, short timeouts, like the mail
  sender (LP-993): `set_up_mail_domain` is re-run by a person or the hourly check, so a failed call
  simply waits for the next run.
- `FakeDomainProvider` (dev, tests): every stage succeeds at once. It refuses to run in staging or
  production, where it would mark a domain active that AWS has never heard of.

SYNC, ON PURPOSE (boto3 and dnspython are). From async code, run it in a thread
(`asyncio.to_thread`).

SAFE TO CALL AGAIN. `create_zone` is keyed on a deterministic `CallerReference`, so a second call
finds the first zone instead of making another. `set_up_identity_and_records` reads an identity that
already exists, and writes every record as an UPSERT.

NOTHING HERE LOGS MORE THAN THE DOMAIN AND AWS'S ERROR CODE.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar

import boto3
import dns.exception
import dns.resolver
import structlog
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError, HTTPClientError
from botocore.exceptions import ConnectionError as BotoConnectionError

from app.core.config import settings

logger = structlog.get_logger(__name__)

#: Every record is written with this TTL (seconds): short enough that a mistake is fixed quickly.
RECORD_TTL = 300
#: Customer subdomains reject a forged email outright and send no reports (loan-email.md §3, 10-31:
#: "DMARC on customer subdomains").
DMARC_POLICY = "v=DMARC1; p=reject"
SPF_POLICY = "v=spf1 include:amazonses.com ~all"


#: AWS error codes that pass on their own: AWS was busy or slow, not refusing the request.
_RETRYABLE_CODES = frozenset(
    {
        "Throttling",
        "ThrottlingException",
        "TooManyRequestsException",
        "PriorRequestNotComplete",
        "RequestTimeout",
        "ServiceUnavailable",
        "InternalError",
        "InternalFailure",
    }
)


class DomainSetupError(RuntimeError):
    """AWS refused or could not be reached. `code` is AWS's error code, or the exception name.
    `retryable`: AWS was busy or unreachable, so running again can pass. Otherwise AWS refused (no
    permission, a bad name), and running again fails the same way until someone fixes the cause."""

    def __init__(self, code: str, domain: str, *, retryable: bool = False) -> None:
        super().__init__(f"AWS did not complete the step for {domain} ({code}).")
        self.code = code
        self.domain = domain
        self.retryable = retryable


class DomainProviderNotAllowed(RuntimeError):
    """The configured provider may not run here: the fake, outside development."""


class DomainProvider(ABC):
    """Sets up one customer subdomain, one stage per call."""

    @abstractmethod
    def create_zone(self, subdomain: str, caller_reference: str) -> tuple[str, list[str]]:
        """Create (or find, for the same `caller_reference`) the hosted zone. Returns its bare id
        (`Z…`) and its four nameservers."""

    @abstractmethod
    def is_delegated(self, subdomain: str, nameservers: list[str]) -> bool:
        """Public DNS answers the subdomain's NS query with exactly our nameservers."""

    @abstractmethod
    def set_up_identity_and_records(self, subdomain: str, zone_id: str) -> None:
        """Create the SES identity (Easy DKIM), set MAIL FROM, and write every record."""

    @abstractmethod
    def is_verified(self, subdomain: str) -> bool:
        """SES has verified the identity's DKIM and it can send."""


def _bare(name: str) -> str:
    return name.strip().lower().rstrip(".")


def mail_from_domain(subdomain: str) -> str:
    return f"bounce.{subdomain}"


def records(subdomain: str, dkim_tokens: list[str], region: str) -> list[dict[str, Any]]:
    """The DNS records a customer subdomain needs, as Route 53 `ResourceRecordSet`s."""

    def record(name: str, kind: str, *values: str) -> dict[str, Any]:
        return {
            "Name": name,
            "Type": kind,
            "TTL": RECORD_TTL,
            "ResourceRecords": [{"Value": value} for value in values],
        }

    bounce = mail_from_domain(subdomain)
    return [
        *(
            record(f"{token}._domainkey.{subdomain}", "CNAME", f"{token}.dkim.amazonses.com")
            for token in dkim_tokens
        ),
        record(subdomain, "MX", f"10 inbound-smtp.{region}.amazonaws.com"),
        record(bounce, "MX", f"10 feedback-smtp.{region}.amazonses.com"),
        record(bounce, "TXT", f'"{SPF_POLICY}"'),
        record(f"_dmarc.{subdomain}", "TXT", f'"{DMARC_POLICY}"'),
    ]


class Route53DomainProvider(DomainProvider):
    """Real AWS: Route 53 for the zone and records, SES v2 for the identity."""

    def __init__(
        self,
        route53: Any | None = None,
        sesv2: Any | None = None,
        resolver: dns.resolver.Resolver | None = None,
    ) -> None:
        config = Config(connect_timeout=5, read_timeout=15, retries={"total_max_attempts": 1})
        self._region = settings.s3_region
        self._route53 = route53 or boto3.client("route53", region_name=self._region, config=config)
        self._sesv2 = sesv2 or boto3.client("sesv2", region_name=self._region, config=config)
        if resolver is None:
            resolver = dns.resolver.Resolver()
            resolver.lifetime = 5.0
        self._resolver = resolver

    def _call(self, domain: str, client: Any, operation: str, **params: Any) -> Any:
        try:
            return getattr(client, operation)(**params)
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", "ClientError"))
            status = int(exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0))
            logger.warning("domain_setup_refused", domain=domain, error_code=code)
            raise DomainSetupError(
                code, domain, retryable=code in _RETRYABLE_CODES or status >= 500
            ) from exc
        except BotoCoreError as exc:
            code = type(exc).__name__
            logger.warning("domain_setup_failed", domain=domain, error_code=code)
            # A timeout or a dropped connection passes on its own; missing credentials or a bad
            # parameter does not.
            raise DomainSetupError(
                code, domain, retryable=isinstance(exc, (BotoConnectionError, HTTPClientError))
            ) from exc

    def create_zone(self, subdomain: str, caller_reference: str) -> tuple[str, list[str]]:
        try:
            response = self._call(
                subdomain,
                self._route53,
                "create_hosted_zone",
                Name=subdomain,
                CallerReference=caller_reference,
                HostedZoneConfig={"Comment": "MortgageBoss mail domain (set_up_mail_domain)"},
            )
        except DomainSetupError as exc:
            # The same CallerReference was used before: that zone is ours. Find it rather than
            # make a second one (a second zone has different nameservers from the first).
            if exc.code != "HostedZoneAlreadyExists":
                raise
            return self._find_zone(subdomain, caller_reference)
        zone_id = response["HostedZone"]["Id"].rsplit("/", 1)[-1]
        return zone_id, list(response["DelegationSet"]["NameServers"])

    def _find_zone(self, subdomain: str, caller_reference: str) -> tuple[str, list[str]]:
        listed = self._call(
            subdomain, self._route53, "list_hosted_zones_by_name", DNSName=subdomain
        )
        for zone in listed["HostedZones"]:
            if _bare(zone["Name"]) == subdomain and zone["CallerReference"] == caller_reference:
                zone_id = zone["Id"].rsplit("/", 1)[-1]
                found = self._call(subdomain, self._route53, "get_hosted_zone", Id=zone_id)
                return zone_id, list(found["DelegationSet"]["NameServers"])
        raise DomainSetupError("HostedZoneNotFoundForReference", subdomain)

    def is_delegated(self, subdomain: str, nameservers: list[str]) -> bool:
        try:
            answer = self._resolver.resolve(subdomain, "NS")
        except dns.exception.DNSException:
            return False
        found = {_bare(str(item.target)) for item in answer}
        return found == {_bare(name) for name in nameservers}

    def set_up_identity_and_records(self, subdomain: str, zone_id: str) -> None:
        try:
            created = self._call(
                subdomain, self._sesv2, "create_email_identity", EmailIdentity=subdomain
            )
        except DomainSetupError as exc:
            if exc.code != "AlreadyExistsException":
                raise
            created = self._call(
                subdomain, self._sesv2, "get_email_identity", EmailIdentity=subdomain
            )
        tokens = list(created["DkimAttributes"]["Tokens"])
        self._call(
            subdomain,
            self._sesv2,
            "put_email_identity_mail_from_attributes",
            EmailIdentity=subdomain,
            MailFromDomain=mail_from_domain(subdomain),
            BehaviorOnMxFailure="USE_DEFAULT_VALUE",
        )
        self._call(
            subdomain,
            self._route53,
            "change_resource_record_sets",
            HostedZoneId=zone_id,
            ChangeBatch={
                "Comment": "MortgageBoss mail records (set_up_mail_domain)",
                "Changes": [
                    {"Action": "UPSERT", "ResourceRecordSet": record}
                    for record in records(subdomain, tokens, self._region)
                ],
            },
        )

    def is_verified(self, subdomain: str) -> bool:
        identity = self._call(subdomain, self._sesv2, "get_email_identity", EmailIdentity=subdomain)
        dkim = identity.get("DkimAttributes", {})
        return dkim.get("Status") == "SUCCESS" and bool(identity.get("VerifiedForSendingStatus"))


class FakeDomainProvider(DomainProvider):
    """Dev and tests: every stage succeeds at once."""

    NAMESERVERS: ClassVar[tuple[str, ...]] = tuple(f"ns-{n}.fake-dns.example" for n in range(1, 5))

    def create_zone(self, subdomain: str, caller_reference: str) -> tuple[str, list[str]]:
        return "ZFAKE" + subdomain.replace(".", "").upper()[:20], list(self.NAMESERVERS)

    def is_delegated(self, subdomain: str, nameservers: list[str]) -> bool:
        return True

    def set_up_identity_and_records(self, subdomain: str, zone_id: str) -> None:
        return None

    def is_verified(self, subdomain: str) -> bool:
        return True


def get_domain_provider() -> DomainProvider:
    """The configured provider. The fake refuses to run outside development."""
    if settings.domain_provider == "route53":
        return Route53DomainProvider()
    if settings.environment != "development":
        raise DomainProviderNotAllowed(
            f"DOMAIN_PROVIDER is 'fake', which only runs in development (this is "
            f"{settings.environment}). Set DOMAIN_PROVIDER=route53."
        )
    return FakeDomainProvider()


__all__ = [
    "DMARC_POLICY",
    "DomainProvider",
    "DomainProviderNotAllowed",
    "DomainSetupError",
    "FakeDomainProvider",
    "Route53DomainProvider",
    "get_domain_provider",
    "records",
]
