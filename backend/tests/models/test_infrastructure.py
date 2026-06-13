"""Tests for the model-layer foundations (LP-10).

Exercises the shared types, enum pattern, soft-delete helper, and the
transaction-rollback test infrastructure against a real (throwaway) model.

The throwaway model deliberately uses its **own** ``MetaData`` (a separate
declarative base), so it never registers on the application's ``Base.metadata``.
That keeps it out of ``create_all`` for the real schema and out of Alembic
autogenerate (which imports ``app.models`` only) — and lets us assert that
absence directly. Its table is created on the test engine by an autouse fixture
and dropped at the end of the module.
"""

from collections.abc import AsyncIterator
from decimal import Decimal

import pytest_asyncio
from app.models import Base, Money, RecordStatus, ShortStr, only_active, str_enum
from app.models.base import NAMING_CONVENTION, SoftDeleteMixin, TimestampMixin, UUIDMixin, utcnow
from sqlalchemy import MetaData, func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class _ThrowawayBase(DeclarativeBase):
    """Separate declarative base so the throwaway model stays off app Base."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Widget(UUIDMixin, TimestampMixin, SoftDeleteMixin, _ThrowawayBase):
    """Throwaway model used only to exercise the foundations.

    Composes every mixin and uses the shared Money/ShortStr types and the enum
    pattern, so a single table verifies the whole stack.
    """

    __tablename__ = "throwaway_widget"

    name: Mapped[ShortStr]
    price: Mapped[Money]
    status: Mapped[RecordStatus] = mapped_column(
        str_enum(RecordStatus),
        default=RecordStatus.ACTIVE,
        nullable=False,
    )


@pytest_asyncio.fixture(autouse=True)
async def _throwaway_schema(test_engine: AsyncEngine) -> AsyncIterator[None]:
    """Create the throwaway table on the test engine, drop it afterwards.

    Committed via its own connection so every test (each in its own rolled-back
    db_session transaction) can see the table.
    """
    async with test_engine.begin() as conn:
        await conn.run_sync(_ThrowawayBase.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(_ThrowawayBase.metadata.drop_all)


async def _count(session: AsyncSession) -> int:
    """Count rows currently visible in the throwaway table."""
    result = await session.scalar(select(func.count()).select_from(Widget))
    return result or 0


async def test_db_session_provides_working_session(db_session: AsyncSession) -> None:
    """The db_session fixture yields a usable async session."""
    assert await db_session.scalar(text("SELECT 1")) == 1


async def test_create_and_query(db_session: AsyncSession) -> None:
    """A record can be created, flushed, and read back by id."""
    widget = Widget(name="alpha", price=Decimal("10.00"))
    db_session.add(widget)
    await db_session.flush()

    fetched = await db_session.get(Widget, widget.id)
    assert fetched is not None
    assert fetched.name == "alpha"
    assert fetched.created_at is not None
    assert fetched.updated_at is not None


async def test_soft_delete_and_only_active(db_session: AsyncSession) -> None:
    """Soft delete sets deleted_at; only_active() filters such rows out."""
    live = Widget(name="live", price=Decimal("1.00"))
    gone = Widget(name="gone", price=Decimal("2.00"))
    db_session.add_all([live, gone])
    await db_session.flush()

    assert live.is_deleted is False

    gone.deleted_at = utcnow()
    await db_session.flush()
    assert gone.is_deleted is True

    # Without the helper: both rows are visible.
    all_rows = (await db_session.scalars(select(Widget))).all()
    assert {w.name for w in all_rows} == {"live", "gone"}

    # With the helper: the soft-deleted row is excluded.
    active_rows = (await db_session.scalars(only_active(select(Widget), Widget))).all()
    assert {w.name for w in active_rows} == {"live"}


async def test_money_roundtrips_as_decimal(db_session: AsyncSession) -> None:
    """The Money column stores and returns an exact Decimal, never a float."""
    widget = Widget(name="priced", price=Decimal("1234.56"))
    db_session.add(widget)
    await db_session.flush()
    await db_session.refresh(widget)  # re-read the value the DB actually stored

    assert isinstance(widget.price, Decimal)
    assert widget.price == Decimal("1234.56")


async def test_enum_roundtrips(db_session: AsyncSession) -> None:
    """The enum column round-trips and is stored as its string value."""
    widget = Widget(name="archived", price=Decimal("3.00"), status=RecordStatus.ARCHIVED)
    db_session.add(widget)
    await db_session.flush()
    await db_session.refresh(widget)

    assert widget.status is RecordStatus.ARCHIVED

    # native_enum=False means it is persisted as a plain VARCHAR value.
    raw = await db_session.scalar(
        text("SELECT status FROM throwaway_widget WHERE id = :id"),
        {"id": widget.id},
    )
    assert raw == "archived"


async def test_default_enum_value(db_session: AsyncSession) -> None:
    """The enum default (ACTIVE) is applied when not specified."""
    widget = Widget(name="defaulted", price=Decimal("4.00"))
    db_session.add(widget)
    await db_session.flush()
    await db_session.refresh(widget)
    assert widget.status is RecordStatus.ACTIVE


# --- Isolation: these two tests both create data; neither sees the other's. ---


async def test_isolation_first(db_session: AsyncSession) -> None:
    """Starts empty, adds one row."""
    assert await _count(db_session) == 0
    db_session.add(Widget(name="first", price=Decimal("1.00")))
    await db_session.flush()
    assert await _count(db_session) == 1


async def test_isolation_second(db_session: AsyncSession) -> None:
    """Also starts empty — proving the previous test's row was rolled back."""
    assert await _count(db_session) == 0
    db_session.add(Widget(name="second", price=Decimal("1.00")))
    await db_session.flush()
    assert await _count(db_session) == 1


def test_throwaway_does_not_leak_into_app_metadata() -> None:
    """The throwaway table must not appear on the app Base (hence not in
    migrations, which autogenerate from Base.metadata)."""
    assert "throwaway_widget" not in Base.metadata.tables
    assert "throwaway_widget" in _ThrowawayBase.metadata.tables
