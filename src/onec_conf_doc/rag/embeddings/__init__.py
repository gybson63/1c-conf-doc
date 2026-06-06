"""Factory for embedding providers."""

from __future__ import annotations

from onec_conf_doc.config import EmbeddingsConfig
from onec_conf_doc.rag.embeddings.base import EmbeddingProvider
from onec_conf_doc.rag.embeddings.ollama_provider import OllamaEmbeddingProvider
from onec_conf_doc.rag.embeddings.openai_provider import OpenAIEmbeddingProvider
from onec_conf_doc.rag.embeddings.sentence_transformers_provider import SentenceTransformersProvider


def create_embedding_provider(config: EmbeddingsConfig) -> EmbeddingProvider:
    if config.provider == "openai":
        return OpenAIEmbeddingProvider(config)
    if config.provider == "ollama":
        return OllamaEmbeddingProvider(config)
    if config.provider == "sentence_transformers":
        return SentenceTransformersProvider(config)
    msg = f"Unknown embedding provider: {config.provider}"
    raise ValueError(msg)
