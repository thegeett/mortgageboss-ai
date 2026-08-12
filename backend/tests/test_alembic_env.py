"""Tests for the Alembic environment's database-URL handling.

Regression cover for the staging migration failure recorded in
``docs/findings/migrate-interpolation.md``: ``alembic/env.py`` used to push the
URL through ``config.set_main_option``, which stores it in a ConfigParser using
BasicInterpolation. Any ``%`` in the URL then raised

    ValueError: invalid interpolation syntax in '...' at position 46

before a connection was attempted, and the message named configparser rather
than the password.

The trap is not limited to hand-written passwords. ``settings.database_url`` is
a Pydantic ``PostgresDsn``, and ``str()`` on it re-encodes the userinfo, so a
password containing a literal ``;`` -- which the generated charset permits --
arrives as ``%3B``. Secrets Manager held a valid URL with no ``%`` in it; the
``%`` was manufactured inside the application.
"""

import configparser
from pathlib import Path

import pytest
from pydantic import PostgresDsn, TypeAdapter
from sqlalchemy.engine.url import make_url
from sqlalchemy.ext.asyncio import create_async_engine

ENV_PY = Path(__file__).resolve().parents[1] / "alembic" / "env.py"

HOST = "db.example.com"

# Passwords that survive the full Pydantic -> SQLAlchemy round trip. Each
# contains a character that has bitten this project.
ROUND_TRIP_SAFE = [
    pytest.param("pa%ss", id="literal-percent"),
    pytest.param("100%pure", id="percent-then-letters"),
    pytest.param("trailing%", id="trailing-percent"),
    pytest.param("Sb(x;y)Z", id="semicolon-and-parens"),
    pytest.param("Sb!x(y;z)Q-_.~", id="full-generated-charset"),
]


def _url(password: str) -> str:
    """A DSN string the way settings produces it -- through Pydantic."""
    adapter = TypeAdapter(PostgresDsn)
    dsn = adapter.validate_python(
        f"postgresql+asyncpg://user:{password}@{HOST}:5432/appdb?ssl=verify-full"
    )
    return str(dsn)


@pytest.mark.parametrize("password", ROUND_TRIP_SAFE)
def test_url_reaches_the_engine_with_the_password_intact(password: str) -> None:
    """A URL containing a percent survives env.py's handling.

    This is what env.py now does: ``str(settings.database_url)`` straight into
    ``create_async_engine``. Nothing goes through a ConfigParser, so no value
    can raise an interpolation error, and the password arrives unchanged.
    """
    engine = create_async_engine(_url(password), poolclass=None)
    try:
        assert engine.url.password == password
        assert engine.url.host == HOST
        assert engine.url.database == "appdb"
        assert engine.url.query["ssl"] == "verify-full"
    finally:
        engine.sync_engine.dispose()


def test_pydantic_manufactures_the_percent() -> None:
    """The mechanism itself: a literal ';' comes back out as '%3B'.

    This is what put a '%' into a URL that Secrets Manager stored without one.
    If a future Pydantic stops re-encoding, this test fails and the comment in
    env.py can be revisited -- the fix stays correct either way.
    """
    rendered = _url("Sb(x;y)Z")
    assert "%3B" in rendered
    assert ";" not in rendered


@pytest.mark.parametrize("password", ROUND_TRIP_SAFE)
def test_the_old_ini_route_would_still_break(password: str) -> None:
    """The regression this guards against, demonstrated rather than described.

    Every one of these renders to a URL containing a '%', and every one raises
    when routed through a ConfigParser with the default interpolation -- which
    is exactly what ``config.set_main_option`` does.
    """
    rendered = _url(password)
    assert "%" in rendered, "test case must exercise the interpolation path"

    parser = configparser.ConfigParser()
    parser.add_section("alembic")
    with pytest.raises(ValueError, match="invalid interpolation syntax"):
        parser.set("alembic", "sqlalchemy.url", rendered)


@pytest.mark.parametrize(
    ("password", "arrives_as"),
    [
        pytest.param("pa%3Bss", "pa;ss", id="percent-plus-two-hex"),
        pytest.param("a%25b", "a%b", id="percent-two-five"),
    ],
)
def test_percent_followed_by_hex_is_still_lossy(password: str, arrives_as: str) -> None:
    """A KNOWN LIMIT of the fix, pinned so nobody assumes it is covered.

    Pydantic passes '%' through unchanged rather than escaping it, and
    SQLAlchemy percent-DECODES the userinfo when parsing. A password containing
    '%' followed by two hex digits is therefore silently altered on the way to
    the driver -- the connection then fails authentication with no hint that the
    password was rewritten.

    env.py's change removes the configparser crash for these too, but it cannot
    fix this: the corruption happens in the URL layer, below Alembic. This is
    why ``modules/data/main.tf`` excludes '%' from ``override_special`` -- see
    ADR-377 and the comment there. A hand-set password containing '%' is still
    unsafe.
    """
    assert make_url(_url(password)).password == arrives_as
    assert make_url(_url(password)).password != password


def test_env_py_does_not_route_the_url_through_alembic_config() -> None:
    """env.py must not reintroduce the ini hop.

    A source-level guard, deliberately: the failure it prevents appears only at
    migration time, in a container, against a password nobody can predict.
    """
    source = ENV_PY.read_text(encoding="utf-8")
    code = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("#"))

    assert "set_main_option" not in code, (
        "env.py must not put the database URL through alembic's ConfigParser: "
        "any '%' in it raises before a connection is attempted. Pass the URL "
        "straight to create_async_engine / context.configure instead."
    )
    assert "async_engine_from_config" not in code, (
        "async_engine_from_config reads sqlalchemy.url back out of the ini "
        "section, reintroducing the interpolation hop. Use create_async_engine."
    )
    assert "create_async_engine" in code
