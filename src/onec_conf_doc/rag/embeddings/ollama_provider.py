"""Ollama embedding provider."""

from __future__ import annotations

import httpx

from onec_conf_doc.config import EmbeddingsConfig


class OllamaEmbeddingProvider:
    def __init__(self, config: EmbeddingsConfig) -> None:
        self._base_url = config.ollama_base_url.rstrip("/")
        self._model = config.model
        self._batch_size = config.batch_size
        self._dimension = 768
        probe = self.embed_query("test")
        self._dimension = len(probe)

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for i in range(0, len(texts), self._batch_size):
            batch = texts[i : i + self._batch_size]
            for text in batch:
                vectors.append(self._embed_one(text))
        return vectors

    def embed_query(self, text: str) -> list[float]:
        return self._embed_one(text)

    def _embed_one(self, text: str) -> list[float]:
        with httpx.Client(timeout=120.0) as client:
            response = client.post(
                f"{self._base_url}/api/embeddings",
                json={"model": self._model, "prompt": text},
            )
            response.raise_for_status()
            data = response.json()
        embedding = data.get("embedding")
        if not isinstance(embedding, list):
            msg = "Invalid Ollama embedding response"
            raise ValueError(msg)
        return [float(x) for x in embedding]
