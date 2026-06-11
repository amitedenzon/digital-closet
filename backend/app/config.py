from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite+aiosqlite:///./closet.db"
    GMAIL_CREDENTIALS_FILE: str = "credentials.json"
    GMAIL_TOKEN_FILE: str = "token.json"
    GMAIL_ACCOUNT: str = ""
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "qwen2.5:7b"
    BODY_TEXT_MAX_CHARS: int = 6_000
    IMAGE_STORE_DIR: str = "data/images"
    IMAGE_MIN_DIMENSION: int = 100
    IMAGE_CONCURRENCY: int = 5

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}
