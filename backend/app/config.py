from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite+aiosqlite:///./closet.db"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}
