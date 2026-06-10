import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings


def test_settings_accepts_database_url():
    s = Settings(DATABASE_URL="sqlite+aiosqlite:///./test.db")
    assert s.DATABASE_URL == "sqlite+aiosqlite:///./test.db"


def test_settings_has_default_database_url():
    s = Settings()
    assert s.DATABASE_URL.startswith("sqlite+aiosqlite://")


async def test_make_engine_connects():
    from app.db import make_engine

    engine = make_engine("sqlite+aiosqlite:///:memory:")
    async with engine.connect() as conn:
        result = await conn.execute(sa.text("SELECT 1"))
        assert result.scalar() == 1
    await engine.dispose()


async def test_make_session_factory_yields_async_session():
    from app.db import make_engine, make_session_factory

    engine = make_engine("sqlite+aiosqlite:///:memory:")
    factory = make_session_factory(engine)
    async with factory() as session:
        assert isinstance(session, AsyncSession)
    await engine.dispose()
