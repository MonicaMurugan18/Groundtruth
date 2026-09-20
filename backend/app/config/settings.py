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

    # --- LLM provider selection ---
    # "openai" or "groq". Groq speaks the OpenAI wire protocol, so both are
    # driven through the same AsyncOpenAI client with a different base URL.
    llm_provider: str = "openai"

    # --- LLM (OpenAI) ---
    openai_api_key: str = ""
    openai_base_url: str = ""
    llm_model: str = "gpt-4o-mini"
    eval_llm_model: str = "gpt-4o-mini"
    llm_temperature: float = 0.0
    # Retries for transient provider errors. The OpenAI SDK honours Retry-After,
    # so this covers short rate-limit waits - Groq's free tier caps at 8000 TPM
    # and asks callers to retry after ~1-2s, which otherwise surfaces as a
    # metric that could not be computed.
    llm_max_retries: int = 5

    # --- LLM (Groq) ---
    groq_api_key: str = ""
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_model: str = "openai/gpt-oss-120b"
    groq_eval_model: str = "openai/gpt-oss-120b"

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
    # Second Moss stage: query the corpus with the generated answer to look for
    # corroborating passages. Costs one extra Moss call per evaluation, so it is
    # switchable for quota-constrained environments.
    moss_evidence_enabled: bool = True
    moss_evidence_top_k: int = 3
    # After a Moss failure, skip Moss for this many seconds. A failing call
    # costs ~2.5s (the SDK retries internally) and the pipeline makes two per
    # evaluation, so an outage would otherwise add ~5s to every request.
    moss_failure_cooldown_s: float = 60.0

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

    # ---- LLM provider resolution ----------------------------------------
    #
    # Everything downstream reads these instead of the provider-specific
    # fields, so adding a provider does not mean touching every call site.
    # Groq is OpenAI-wire-compatible, so both run through AsyncOpenAI and
    # differ only by base URL, key and model name.

    @property
    def active_provider(self) -> str:
        """The selected provider, normalised. Unknown values fall back to openai."""
        provider = self.llm_provider.strip().lower()
        return provider if provider in {"openai", "groq"} else "openai"

    @property
    def is_groq(self) -> bool:
        return self.active_provider == "groq"

    @property
    def llm_api_key(self) -> str:
        """API key for the active provider."""
        return (self.groq_api_key if self.is_groq else self.openai_api_key).strip()

    @property
    def llm_base_url(self) -> str:
        """Base URL for the active provider, or "" to use the OpenAI default."""
        if self.is_groq:
            return self.groq_base_url.strip()
        return self.openai_base_url.strip()

    @property
    def active_llm_model(self) -> str:
        """Model used to generate answers."""
        return (self.groq_model if self.is_groq else self.llm_model).strip()

    @property
    def active_eval_model(self) -> str:
        """Model used as the evaluation judge."""
        return (self.groq_eval_model if self.is_groq else self.eval_llm_model).strip()

    @property
    def llm_key_variable(self) -> str:
        """Name of the env var that supplies the active provider's key.

        Used in error messages so an operator running Groq is not told to set
        OPENAI_API_KEY.
        """
        return "GROQ_API_KEY" if self.is_groq else "OPENAI_API_KEY"

    @property
    def llm_configured(self) -> bool:
        """True when the active provider has a key.

        Generation and RAGAS scoring both require this. When it is False the
        pipeline reports the affected stages as unavailable instead of
        substituting placeholder scores.
        """
        return bool(self.llm_api_key)

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
