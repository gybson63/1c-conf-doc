"""Sentence-transformers local embedding provider."""

from __future__ import annotations

from onec_conf_doc.config import EmbeddingsConfig


class SentenceTransformersProvider:
    def __init__(self, config: EmbeddingsConfig) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            msg = "Install sentence-transformers: pip install '1c-conf-doc[embeddings]'"
            raise ImportError(msg) from exc

        self._model = SentenceTransformer(config.model)
        self._batch_size = config.batch_size
        sample = self._model.encode(["test"], show_progress_bar=False)
        self._dimension = len(sample[0])

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors = self._model.encode(
            texts,
            batch_size=self._batch_size,
            show_progress_bar=False,
            normalize_embeddings=True,
        )
        return [vec.tolist() for vec in vectors]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]
