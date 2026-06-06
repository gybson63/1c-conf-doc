"""FAISS vector index persistence and search."""

from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

import faiss
import numpy as np

from onec_conf_doc.config import FaissConfig
from onec_conf_doc.rag.embeddings.base import EmbeddingProvider


def _write_faiss_index(index: faiss.Index, destination: Path) -> None:
    """Write FAISS index; workaround for non-ASCII paths on Windows."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix=".faiss", delete=False) as tmp:
        temp_path = Path(tmp.name)
    try:
        faiss.write_index(index, str(temp_path))
        shutil.copy2(temp_path, destination)
    finally:
        temp_path.unlink(missing_ok=True)


def _read_faiss_index(source: Path) -> faiss.Index:
    """Read FAISS index; workaround for non-ASCII paths on Windows."""
    with tempfile.NamedTemporaryFile(suffix=".faiss", delete=False) as tmp:
        temp_path = Path(tmp.name)
    try:
        shutil.copy2(source, temp_path)
        return faiss.read_index(str(temp_path))
    finally:
        temp_path.unlink(missing_ok=True)


@dataclass
class SearchResult:
    chunk_id: int
    score: float
    vector_id: int


class FaissIndex:
    def __init__(
        self,
        vectors_dir: Path,
        config: FaissConfig,
        dimension: int,
    ) -> None:
        self.vectors_dir = vectors_dir
        self.config = config
        self.dimension = dimension
        self.index_path = vectors_dir / "index.faiss"
        self.map_path = vectors_dir / "chunk_map.json"
        self._index: faiss.Index | None = None
        self._vector_to_chunk: dict[int, int] = {}

    def _create_index(self) -> faiss.Index:
        if self.config.index_type == "hnsw":
            index = faiss.IndexHNSWFlat(self.dimension, self.config.hnsw_m)
            index.hnsw.efConstruction = 200
            return index
        return faiss.IndexFlatIP(self.dimension)

    def build(self, vectors: np.ndarray, chunk_ids: list[int]) -> None:
        if vectors.size == 0:
            self._index = self._create_index()
            self._vector_to_chunk = {}
            return

        faiss.normalize_L2(vectors)
        index = self._create_index()
        index.add(vectors)
        self._index = index
        self._vector_to_chunk = {i: chunk_id for i, chunk_id in enumerate(chunk_ids)}

    def save(self) -> None:
        if self._index is None:
            self._index = self._create_index()
        _write_faiss_index(self._index, self.index_path)
        self.vectors_dir.mkdir(parents=True, exist_ok=True)
        with self.map_path.open("w", encoding="utf-8") as fh:
            json.dump(
                {
                    "dimension": self.dimension,
                    "vector_to_chunk": {str(k): v for k, v in self._vector_to_chunk.items()},
                },
                fh,
                ensure_ascii=False,
                indent=2,
            )

    def load(self) -> bool:
        if not self.index_path.exists() or not self.map_path.exists():
            return False
        self._index = _read_faiss_index(self.index_path)
        with self.map_path.open(encoding="utf-8") as fh:
            data = json.load(fh)
        self.dimension = int(data.get("dimension", self.dimension))
        self._vector_to_chunk = {int(k): int(v) for k, v in data.get("vector_to_chunk", {}).items()}
        return True

    def search(
        self,
        provider: EmbeddingProvider,
        query: str,
        *,
        top_k: int = 5,
    ) -> list[SearchResult]:
        if self._index is None and not self.load():
            return []
        if self._index is None or self._index.ntotal == 0:
            return []

        vector = np.array([provider.embed_query(query)], dtype=np.float32)
        faiss.normalize_L2(vector)
        scores, indices = self._index.search(vector, min(top_k, self._index.ntotal))

        results: list[SearchResult] = []
        for score, vector_id in zip(scores[0], indices[0], strict=True):
            if vector_id < 0:
                continue
            chunk_id = self._vector_to_chunk.get(int(vector_id))
            if chunk_id is None:
                continue
            results.append(
                SearchResult(
                    chunk_id=chunk_id,
                    score=float(score),
                    vector_id=int(vector_id),
                )
            )
        return results
