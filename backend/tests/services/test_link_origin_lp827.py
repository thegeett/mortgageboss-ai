"""LP-827 — the origin a borrower's secure link is built from, checked where it is read.

REPORTED FROM STAGING: the secure link did not open. `UPLOAD_LINK_BASE_URL` was assigned in no
`.tf`, `.tfvars`, `.yml`, `.env` or script in this repository, so staging ran on the development
default and every minted link pointed at `http://localhost:3000/upload/<token>` — the reader's own
machine.

WHY THESE TESTS ARE HERE AND NOT ON `Settings`. The first fix was a `Settings` validator, which
refuses to build the settings object and therefore fires in EVERY process — including
`alembic upgrade head`, which `scripts/deploy` runs on the NEW image under the CURRENTLY DEPLOYED
task definition, one step BEFORE the apply that sets the variable. Running the real migration
command under that environment killed it. `tests/test_config.py` holds the regression for that;
this file holds the rule itself, at its one reader.
"""

from __future__ import annotations

import pytest
from app.core.config import settings
from app.services.upload_links import (
    LinkOriginNotConfigured,
    MintedLink,
    usable_link_origin,
)


@pytest.fixture(autouse=True)
def _restore_settings() -> object:
    """The settings singleton is process-wide; put it back however the test left it."""
    before = (settings.environment, settings.upload_link_base_url)
    yield
    settings.__dict__["environment"], settings.__dict__["upload_link_base_url"] = before


def _configure(*, environment: str, base_url: str) -> None:
    settings.__dict__["environment"] = environment
    settings.__dict__["upload_link_base_url"] = base_url


@pytest.mark.parametrize(
    "base_url",
    [
        "http://localhost:3000",  # the one that shipped
        "http://LOCALHOST:3000",  # case is not a difference a browser makes
        "http://localhost.",  # a trailing dot is still the same name
        "http://127.0.0.1:3000",
        "http://127.0.0.53:3000",  # the whole 127/8 block, not one address
        "http://[::1]:3000",
        "http://[::ffff:127.0.0.1]",  # IPv4-mapped, which a hand-written list misses
        "http://0.0.0.0:3000",
    ],
)
def test_a_deployed_environment_refuses_a_loopback_origin(base_url: str) -> None:
    """An asymmetry is a class, not an instance — so the rule is `ipaddress`, not a list of
    spellings. Every one of these resolves, in the borrower's browser, to the borrower's own
    machine, and a guard that knew only the word "localhost" would pass six of them."""
    _configure(environment="staging", base_url=base_url)

    with pytest.raises(LinkOriginNotConfigured, match="UPLOAD_LINK_BASE_URL"):
        usable_link_origin()


@pytest.mark.parametrize(
    "base_url",
    [
        "localhost:3000",  # THE ONE THE FIRST VERSION MISSED
        "staging.mortgageboss.ai",
        "",
        "https://",
        "   ",
    ],
)
def test_an_origin_with_no_scheme_or_no_host_is_refused(base_url: str) -> None:
    """`urlparse("localhost:3000").hostname` is None — "localhost" parses as the SCHEME. So the most
    natural way to write the reported misconfiguration into a tfvars file passed a check that read
    only the hostname, and the link would have gone out pointing at the reader's own machine again.

    The others are the same class: an origin with no host cannot be clicked from an email, whatever
    environment it is in, which is why this rule has no development exemption.
    """
    _configure(environment="staging", base_url=base_url)

    with pytest.raises(LinkOriginNotConfigured, match="UPLOAD_LINK_BASE_URL"):
        usable_link_origin()


def test_the_same_no_host_rule_applies_in_development() -> None:
    """The exemption is for LOOPBACK, not for nonsense. A developer whose value has no scheme has
    the same broken link as anyone else, and telling them so at the moment they mint one is the
    whole point of checking here."""
    _configure(environment="development", base_url="localhost:3000")

    with pytest.raises(LinkOriginNotConfigured):
        usable_link_origin()


def test_development_still_mints_localhost_links() -> None:
    """THE POSITIVE CONTROL, and it is the point of the default. A rule that refused loopback
    everywhere would break every developer's machine, and every refusal test above would still
    pass."""
    _configure(environment="development", base_url="http://localhost:3000")

    assert usable_link_origin() == "http://localhost:3000"


def test_a_real_origin_is_accepted_in_a_deployed_environment() -> None:
    """The second positive control. Without it, a rule that refused EVERY value outside development
    would satisfy both refusal groups above and no borrower would ever get a link at all."""
    _configure(environment="staging", base_url="https://staging.mortgageboss.ai")

    assert usable_link_origin() == "https://staging.mortgageboss.ai"


def test_the_minted_url_is_built_from_the_configured_origin() -> None:
    """The link a borrower clicks, asserted end to end from the setting — the trailing slash
    included, because a doubled one is the kind of thing that renders as a broken link only after it
    has been sent."""
    _configure(environment="staging", base_url="https://staging.mortgageboss.ai/")

    url = MintedLink(link=None, token="tok123").url  # type: ignore[arg-type]

    assert url == "https://staging.mortgageboss.ai/upload/tok123"


def test_minting_a_link_refuses_rather_than_producing_a_broken_one() -> None:
    """The refusal reaches the caller as an exception, not as a URL nobody can open. Both readers of
    `.url` — the API response and the auto-reply nudge — are a link about to reach a person."""
    _configure(environment="production", base_url="http://localhost:3000")

    with pytest.raises(LinkOriginNotConfigured):
        _ = MintedLink(link=None, token="tok123").url  # type: ignore[arg-type]
