"""Alembic migration environment, configured for async SQLAlchemy.

The database URL and target metadata come from the application itself:
the URL from the cached Pydantic ``settings`` singleton, and the metadata
from ``app.models.Base``. Importing the models package ensures every table
is registered on the metadata so autogenerate can discover it.
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from app.core.config import settings
from app.models import Base
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

# Alembic Config object, providing access to values in alembic.ini.
config = context.config

# The database URL from app settings (single source of truth). It already uses
# the asyncpg driver (postgresql+asyncpg://), which the async engine requires.
#
# ⚠️ THIS MUST NOT GO THROUGH config.set_main_option / the alembic.ini section.
#
# Alembic keeps main options in a ConfigParser using BasicInterpolation, which
# treats '%' as an escape character. Any '%' in the URL therefore raises
#     ValueError: invalid interpolation syntax in '...' at position N
# BEFORE a connection is ever attempted, and the message names configparser
# rather than the password, so it reads like a config-file problem.
#
# This is not hypothetical and it is not about hand-written passwords:
# settings.database_url is a Pydantic PostgresDsn, and str() on it RE-ENCODES
# the userinfo. A password containing a literal ';' -- which the generated
# charset permits -- comes back out as '%3B'. The staging migration failed
# exactly this way, twice, while Secrets Manager held a perfectly valid URL with
# no '%' in it at all. See docs/findings/migrate-interpolation.md.
#
# Escaping ('%' -> '%%') would also work, but leaves the trap armed for the next
# person who sets the option. Handing the URL straight to the engine removes the
# ini hop entirely. Nothing is lost: alembic.ini deliberately leaves
# `sqlalchemy.url` commented out and defines no other `sqlalchemy.*` options.
#
# Note the ini still uses interpolation elsewhere on purpose (`%(here)s`,
# `%%(year)d`), so disabling it globally is not an option.
DATABASE_URL = str(settings.database_url)

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Target metadata for 'autogenerate' support.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL without a DB connection)."""
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Run migrations given an active synchronous connection."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create an async engine and run migrations through it."""
    # create_async_engine, not async_engine_from_config: the latter reads
    # `sqlalchemy.url` back out of the ini section, which is the hop this module
    # deliberately avoids. SQLAlchemy percent-DECODES the userinfo when parsing,
    # so a '%3B' from Pydantic's serialisation becomes ';' again here -- the
    # password reaching asyncpg is the one in Secrets Manager either way.
    connectable = create_async_engine(DATABASE_URL, poolclass=pool.NullPool)

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (with a live async DB connection)."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
