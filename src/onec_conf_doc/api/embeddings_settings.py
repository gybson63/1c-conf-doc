"""Shared helpers for per-configuration embeddings settings."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field

from onec_conf_doc.config import AppConfig, EmbeddingsConfig, save_config

if TYPE_CHECKING:
    from onec_conf_doc.rag.pipeline import Pipeline


class EmbeddingsSettingsUpdate(BaseModel):
    provider: Literal["openai", "ollama", "sentence_transformers"]
    model: str = Field(..., min_length=1)
    batch_size: int = Field(default=32, ge=1, le=256)
    base_url: str | None = None
    ollama_base_url: str = "http://localhost:11434"
    openai_api_key: str | None = None


def merge_embeddings_settings(
    current: EmbeddingsConfig,
    body: EmbeddingsSettingsUpdate,
) -> EmbeddingsConfig:
    api_key = body.openai_api_key
    if not api_key or str(api_key).strip() in {"", "***"}:
        api_key = current.openai_api_key
    return EmbeddingsConfig(
        provider=body.provider,
        model=body.model,
        batch_size=body.batch_size,
        base_url=body.base_url,
        ollama_base_url=body.ollama_base_url,
        openai_api_key=api_key,
    )


def apply_configuration_embeddings(
    config: AppConfig,
    pipeline: Pipeline,
    configuration_name: str,
    body: EmbeddingsSettingsUpdate,
    *,
    config_path: Path | None = None,
) -> EmbeddingsConfig:
    """Persist embeddings profile for a configuration and refresh provider cache."""
    updated = merge_embeddings_settings(config.embeddings_for(configuration_name), body)
    config.configuration_embeddings[configuration_name] = updated
    pipeline.config.configuration_embeddings = dict(config.configuration_embeddings)
    pipeline.reset_embedding_provider(configuration_name)
    if config_path is not None:
        save_config(config, config_path)
    return updated
