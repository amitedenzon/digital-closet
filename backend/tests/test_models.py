from app.config import Settings


def test_settings_accepts_database_url():
    s = Settings(DATABASE_URL="sqlite+aiosqlite:///./test.db")
    assert s.DATABASE_URL == "sqlite+aiosqlite:///./test.db"


def test_settings_has_default_database_url():
    s = Settings()
    assert s.DATABASE_URL.startswith("sqlite+aiosqlite://")
