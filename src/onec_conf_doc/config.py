"""Application configuration loaded from YAML and environment."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class EmbeddingsConfig(BaseModel):
    provider: Literal["openai", "ollama", "sentence_transformers"] = "sentence_transformers"
    model: str = "paraphrase-multilingual-MiniLM-L12-v2"
    batch_size: int = 32
    openai_api_key: str | None = None
    base_url: str | None = None  # OpenAI-compatible API (e.g. https://polza.ai/api/v1)
    ollama_base_url: str = "http://localhost:11434"


class FaissConfig(BaseModel):
    index_type: Literal["flat", "hnsw"] = "flat"
    hnsw_m: int = 32


class ChunkingConfig(BaseModel):
    max_tokens: int = 1500
    overlap_tokens: int = 100


class LLMConfig(BaseModel):
    provider: Literal["openai", "ollama", "none"] = "none"
    model: str = "llama3.2"
    openai_api_key: str | None = None
    ollama_base_url: str = "http://localhost:11434"


class APIConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000


class AppConfig(BaseModel):
    source: Path = Path("./data/export")
    output: Path = Path("./output")
    configuration: str | None = None  # имя из Configuration.xml
    embeddings: EmbeddingsConfig = Field(default_factory=EmbeddingsConfig)
    faiss: FaissConfig = Field(default_factory=FaissConfig)
    chunking: ChunkingConfig = Field(default_factory=ChunkingConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    api: APIConfig = Field(default_factory=APIConfig)

    def docs_dir_for(self, configuration_name: str) -> Path:
        return self.output / "docs" / configuration_name

    def vectors_dir_for(self, configuration_name: str) -> Path:
        return self.output / "vectors" / configuration_name

    @property
    def docs_dir(self) -> Path:
        if self.configuration:
            return self.docs_dir_for(self.configuration)
        return self.output / "docs"

    @property
    def db_path(self) -> Path:
        return self.output / "db" / "metadata.db"

    @property
    def vectors_dir(self) -> Path:
        if self.configuration:
            return self.vectors_dir_for(self.configuration)
        return self.output / "vectors"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CONF_DOC_", extra="ignore")

    config_path: Path = Path("config.yaml")


def load_config(config_path: Path | None = None) -> AppConfig:
    path = config_path or Settings().config_path
    if path.exists():
        with path.open(encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
        return AppConfig.model_validate(raw)
    return AppConfig()
