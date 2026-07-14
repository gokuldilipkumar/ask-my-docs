from typing import Tuple, Type

from pydantic import BaseModel, Field
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)


class ChunkingConfig(BaseModel):
    min_tokens: int = 400
    max_tokens: int = 600
    overlap_pct: float = 0.15
    # 0-based inclusive page-index range of retrievable content; pages outside it
    # (cover/TOC front matter, back-of-book index) are excluded before chunking
    body_page_start: int = 0
    body_page_end: int | None = None


class RetrievalConfig(BaseModel):
    rrf_k: int = 60
    bm25_weight: float = 1.0
    vector_weight: float = 1.0
    top_n: int = 20


class RerankConfig(BaseModel):
    enabled: bool = True
    model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    top_k: int = 5


class GenerationConfig(BaseModel):
    model: str = "claude-sonnet-5"
    max_tokens: int = 2048
    max_retries: int = 3
    timeout_seconds: float = 30.0


class CitationConfig(BaseModel):
    low_confidence_threshold: float = 0.7
    judge_model: str = "claude-haiku-4-5-20251001"
    judge_temperature: float = 0.0
    max_tokens: int = 1024
    max_retries: int = 3
    timeout_seconds: float = 30.0


class EvalConfig(BaseModel):
    judge_model: str = "claude-haiku-4-5-20251001"  # verify against current Anthropic model list at build time
    judge_temperature: float = 0.0
    golden_path: str = "eval/golden/questions.yaml"
    judge_max_tokens: int = 1024
    judge_max_retries: int = 3
    judge_timeout_seconds: float = 30.0


class ObservabilityConfig(BaseModel):
    langfuse_enabled: bool = True
    daily_cost_cap_usd: float = 5.0


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_nested_delimiter="__",
        yaml_file="config.yaml",
        extra="ignore",
    )

    anthropic_api_key: str
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None

    chunking: ChunkingConfig = Field(default_factory=ChunkingConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    rerank: RerankConfig = Field(default_factory=RerankConfig)
    generation: GenerationConfig = Field(default_factory=GenerationConfig)
    citations: CitationConfig = Field(default_factory=CitationConfig)
    eval: EvalConfig = Field(default_factory=EvalConfig)
    observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: Type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> Tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            YamlConfigSettingsSource(settings_cls),
            file_secret_settings,
        )


def get_settings() -> Settings:
    return Settings()
