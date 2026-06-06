"""OpenAI embedding provider."""

from __future__ import annotations

from onec_conf_doc.config import EmbeddingsConfig


class OpenAIEmbeddingProvider:
    def __init__(self, config: EmbeddingsConfig) -> None:
        try:
            from openai import OpenAI
        except ImportError as exc:
            msg = "Install openai: pip install '1c-conf-doc[openai]'"
            raise ImportError(msg) from exc

        api_key = config.openai_api_key
        if not api_key:
            import os

            api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            msg = "OpenAI API key is required (embeddings.openai_api_key or OPENAI_API_KEY)"
            raise ValueError(msg)

        client_kwargs: dict[str, str] = {"api_key": api_key}
        if config.base_url:
            client_kwargs["base_url"] = config.base_url.rstrip("/")
        self._client = OpenAI(**client_kwargs)  # type: ignore[arg-type]
        self._model = config.model
        self._batch_size = config.batch_size
        if "embedding-3-large" in config.model:
            self._dimension = 3072
        elif "embedding-3-small" in config.model:
            self._dimension = 1536
        else:
            self._dimension = 1536

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for i in range(0, len(texts), self._batch_size):
            batch = texts[i : i + self._batch_size]
            response = self._client.embeddings.create(input=batch, model=self._model)
            vectors.extend(item.embedding for item in response.data)
        if vectors:
            self._dimension = len(vectors[0])
        return vectors

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]
