"""Application settings, loaded from environment / .env.

Every setting is prefixed with ``CT200_`` so the process can be configured
without touching code.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_prefix="CT200_", extra="ignore"
    )

    # --- storage ---
    database_url: str = "sqlite:///./ct200.db"
    generation_store: str = "json"  # json | mongo
    generation_store_path: str = "./data/generations.jsonl"
    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db: str = "ct200"

    # --- llm ---
    llm_provider: str = "mock"  # mock | openai | groq | openrouter | gemini
    llm_model: str = "llama-3.1-8b-instant"
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_timeout: float = 30.0
    llm_max_retries: int = 2
    prompt_version: str = "v1"

    # --- parser ---
    ocr_enabled: bool = True
    ocr_min_chars_per_page: int = 40
    ocr_dpi: int = 200

    # --- security / ops ---
    # Ingestion may only read files under this directory (see app/security.py).
    document_root: str = "./data"
    log_level: str = "INFO"
    # Upper bound on rows returned by list/search endpoints.
    max_page_size: int = 200


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
