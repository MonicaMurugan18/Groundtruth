"""Centralised, validated application configuration.

Every secret and tunable enters the application here and nowhere else. Modules
import the cached :func:`get_settings` accessor rather than reading ``os.environ``
directly, so configuration stays testable and there is a single place to audit
for credential handling.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/config/settings.py -> parents[2] == backend/
BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Application settings, loaded from ``backend/.env`` and the environment."""

    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Application ---
    app_env: str = "development"
    log_level: str = "INFO"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: str = "http://localhost:3000"

    # --- Security ---
    jwt_secret_key: str = "dev-only-insecure-secret-change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60
    auth_disabled: bool = True
    rate_limit_per_minute: int = 30

    # --- Database ---
    database_url: str = "sqlite+aiosqlite:///./data/groundtruth.db"

    # --- LLM (OpenAI) ---
    openai_api_key: str = ""
    openai_base_url: str = ""
    llm_model: str = "gpt-4o-mini"
    eval_llm_model: str = "gpt-4o-mini"
    llm_temperature: float = 0.0

    # --- Embeddings ---
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_device: str = "cpu"
    chunk_size: int = 800
    chunk_overlap: int = 120

    # --- FAISS ---
    faiss_index_path: str = "./data/faiss"
    upload_dir: str = "./data/uploads"
    retrieval_top_k: int = 5

    # --- Moss ---
    moss_project_id: str = ""
    moss_project_key: str = ""
    moss_index_name: str = "groundtruth-knowledge"
    moss_model_id: str = "moss-minilm"
    moss_top_k: int = 5
    moss_alpha: float = 0.8
    retrieval_backend: str = "moss"

    # --- Reliability thresholds ---
    faithfulness_threshold: float = 0.70
    relevance_threshold: float = 0.70
    context_precision_threshold: float = 0.50

    # --- LiveKit ---
    livekit_url: str = ""
    livekit_api_key: str = ""
    livekit_api_secret: str = ""
    livekit_agent_name: str = "groundtruth-agent"

    @field_validator("log_level")
    @classmethod
    def _upper_log_level(cls, value: str) -> str:
        return value.upper()

    # ---- Derived helpers -------------------------------------------------

    @property
    def cors_origin_list(self) -> list[str]:
        """CORS origins as a list. An explicit ``*`` disables the allowlist."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def faiss_path(self) -> Path:
        return self._resolve(self.faiss_index_path)

    @property
    def uploads_path(self) -> Path:
        return self._resolve(self.upload_dir)

    @property
    def llm_configured(self) -> bool:
        """True when an LLM key is present.

        Generation and RAGAS scoring both require this. When it is False the
        pipeline reports the affected stages as unavailable instead of
        substituting placeholder scores.
        """
        return bool(self.openai_api_key.strip())

    @property
    def moss_configured(self) -> bool:
        """True only when *both* Moss credentials are present."""
        return bool(self.moss_project_id.strip() and self.moss_project_key.strip())

    @property
    def livekit_configured(self) -> bool:
        return bool(
            self.livekit_url.strip()
            and self.livekit_api_key.strip()
            and self.livekit_api_secret.strip()
        )

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() in {"production", "prod"}

    def _resolve(self, value: str) -> Path:
        """Resolve a possibly-relative configured path against ``backend/``."""
        path = Path(value)
        return path if path.is_absolute() else (BACKEND_DIR / path).resolve()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    return Settings()
