"""End-to-end indexing and RAG pipeline."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from onec_conf_doc.config import AppConfig
from onec_conf_doc.markdown.generator import write_markdown
from onec_conf_doc.models.metadata import ConfigurationInfo
from onec_conf_doc.parser.scanner import scan_export
from onec_conf_doc.parser.xml_parser import parse_configuration, parse_metadata_file
from onec_conf_doc.progress import iter_progress, use_progress
from onec_conf_doc.rag.chunker import chunk_file
from onec_conf_doc.rag.embeddings import create_embedding_provider
from onec_conf_doc.rag.embeddings.base import EmbeddingProvider
from onec_conf_doc.rag.faiss_index import FaissIndex, SearchResult
from onec_conf_doc.rag.llm import LLMProvider, create_llm_provider
from onec_conf_doc.rag.search_ranking import (
    apply_name_match_boost,
    hit_score,
    object_type_rank,
    query_match_strength,
)
from onec_conf_doc.storage.sqlite import SQLiteIndexer, StoredConfiguration


@dataclass
class IndexStats:
    configuration_name: str = ""
    configuration_synonym: str = ""
    objects_total: int = 0
    objects_updated: int = 0
    objects_skipped: int = 0
    chunks_total: int = 0


class Pipeline:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.indexer = SQLiteIndexer(config.db_path)
        self.indexer.init_schema()
        self._embedding_provider: EmbeddingProvider | None = None
        self._faiss: FaissIndex | None = None
        self._llm: LLMProvider | None = None
        self._active_config: StoredConfiguration | None = None

    def resolve_active_configuration(self) -> StoredConfiguration:
        if self._active_config is not None:
            return self._active_config
        if self.config.configuration:
            cfg = self.indexer.resolve_configuration(self.config.configuration)
            if cfg is None:
                from onec_conf_doc.config_names import configuration_not_found_message

                candidates = [c.name for c in self.indexer.list_configurations()]
                raise ValueError(
                    configuration_not_found_message(self.config.configuration, candidates)
                )
            self._active_config = cfg
            return cfg
        configs = self.indexer.list_configurations()
        if not configs:
            msg = "No configurations indexed. Run conf-doc index first."
            raise ValueError(msg)
        if len(configs) > 1:
            names = ", ".join(c.name for c in configs)
            msg = (
                f"Multiple configurations in database ({names}). Set configuration: in config.yaml"
            )
            raise ValueError(msg)
        self._active_config = configs[0]
        return self._active_config

    @property
    def active_configuration(self) -> StoredConfiguration:
        return self.resolve_active_configuration()

    @property
    def embedding_provider(self) -> EmbeddingProvider:
        if self._embedding_provider is None:
            self._embedding_provider = create_embedding_provider(self.config.embeddings)
        return self._embedding_provider

    def faiss_index_for(self, configuration_name: str) -> FaissIndex:
        return FaissIndex(
            self.config.vectors_dir_for(configuration_name),
            self.config.faiss,
            self.embedding_provider.dimension,
        )

    @property
    def faiss_index(self) -> FaissIndex:
        cfg = self.active_configuration
        if self._faiss is None:
            self._faiss = self.faiss_index_for(cfg.name)
            self._faiss.load()
        return self._faiss

    @property
    def llm(self) -> LLMProvider:
        if self._llm is None:
            self._llm = create_llm_provider(self.config.llm)
        return self._llm

    def index_export(
        self,
        *,
        skip_embeddings: bool = False,
        show_progress: bool | None = None,
    ) -> IndexStats:
        progress = use_progress(show_progress)
        source = self.config.source
        stats = IndexStats()

        config_path = source / "Configuration.xml"
        if config_path.exists():
            config_info = parse_configuration(config_path, export_root=source)
        else:
            config_info = ConfigurationInfo(export_path=str(source))
            if self.config.configuration:
                config_info.name = self.config.configuration

        if not config_info.name:
            msg = "Cannot determine configuration name. Add Configuration.xml to export."
            raise ValueError(msg)

        config_info.source_path = str(config_path if config_path.exists() else source)
        config_id = self.indexer.upsert_configuration(config_info)
        stored = self.indexer.get_configuration(config_info.name)
        if stored is None:
            msg = f"Failed to store configuration {config_info.name}"
            raise RuntimeError(msg)

        self._active_config = stored
        self.config.configuration = config_info.name
        stats.configuration_name = config_info.name
        stats.configuration_synonym = config_info.synonym

        docs_dir = self.config.docs_dir_for(config_info.name)
        run_id = self.indexer.start_index_run(config_id)

        refs = scan_export(source)
        parse_bar = iter_progress(
            refs,
            total=len(refs),
            desc="Объекты",
            unit="obj",
            disable=not progress,
        )
        for ref in parse_bar:
            stats.objects_total += 1
            existing_hash = self.indexer.get_object_hash(config_id, ref.object_type, ref.name)
            obj = parse_metadata_file(ref.path, ref.object_type, source_root=source)

            if existing_hash == obj.content_hash:
                stats.objects_skipped += 1
            else:
                md_path = write_markdown(
                    obj,
                    docs_dir,
                    configuration_name=config_info.name,
                    configuration_synonym=config_info.synonym,
                )
                self.indexer.upsert_object(config_id, obj, md_path)
                stats.objects_updated += 1

            set_postfix = getattr(parse_bar, "set_postfix", None)
            if set_postfix is not None:
                set_postfix(
                    updated=stats.objects_updated,
                    skipped=stats.objects_skipped,
                    refresh=False,
                )

        self._build_chunks(config_id, show_progress=progress)
        if not skip_embeddings:
            stats.chunks_total = self.build_embeddings(
                config_id,
                config_info.name,
                show_progress=progress,
            )

        self.indexer.finish_index_run(run_id, stats.objects_total, stats.chunks_total)
        return stats

    def _build_chunks(self, config_id: int, *, show_progress: bool = False) -> None:
        self.indexer.clear_chunks(config_id)
        max_tokens = self.config.chunking.max_tokens
        overlap = self.config.chunking.overlap_tokens

        objects = self.indexer.get_all_objects_with_md(config_id)
        chunk_bar = iter_progress(
            objects,
            total=len(objects),
            desc="Чанки",
            unit="obj",
            disable=not show_progress,
        )
        for object_id, _object_type, _name, md_path in chunk_bar:
            path = Path(md_path)
            if not path.exists():
                continue
            chunks = chunk_file(path, max_tokens=max_tokens, overlap_tokens=overlap)
            payload = [
                (idx, text, str(path), tokens, content_hash)
                for idx, text, tokens, content_hash in chunks
            ]
            self.indexer.insert_chunks(object_id, payload)

    def build_embeddings(
        self,
        config_id: int | None = None,
        configuration_name: str | None = None,
        *,
        show_progress: bool = False,
    ) -> int:
        if config_id is None or configuration_name is None:
            cfg = self.active_configuration
            config_id = cfg.id
            configuration_name = cfg.name

        chunks = self.indexer.get_chunks_for_embedding(config_id)
        faiss_idx = self.faiss_index_for(configuration_name)
        if not chunks:
            empty = np.array([], dtype=np.float32).reshape(0, self.embedding_provider.dimension)
            faiss_idx.build(empty, [])
            faiss_idx.save()
            return 0

        texts = [text for _cid, text, _hash in chunks]
        chunk_ids = [cid for cid, _text, _hash in chunks]
        batch_size = self.config.embeddings.batch_size
        vectors_list: list[list[float]] = []

        batch_count = (len(texts) + batch_size - 1) // batch_size
        embed_bar = iter_progress(
            range(0, len(texts), batch_size),
            total=batch_count,
            desc="Эмбеддинги",
            unit="batch",
            disable=not show_progress,
        )
        for start in embed_bar:
            batch = texts[start : start + batch_size]
            vectors_list.extend(self.embedding_provider.embed_documents(batch))

        vectors = np.array(vectors_list, dtype=np.float32)

        faiss_idx.dimension = vectors.shape[1]
        faiss_idx.build(vectors, chunk_ids)
        faiss_idx.save()

        if show_progress:
            from tqdm import tqdm

            tqdm.write(f"FAISS: сохранено {len(chunk_ids)} векторов", file=sys.stderr)

        mapping = {chunk_id: i for i, chunk_id in enumerate(chunk_ids)}
        self.indexer.update_chunk_vector_ids(mapping)
        if configuration_name == self.config.configuration:
            self._faiss = faiss_idx
        return len(chunk_ids)

    def embedding_status(self) -> str | None:
        """Return a user-facing hint when embeddings/FAISS are missing or stale."""
        cfg = self.active_configuration
        chunks = self.indexer.get_chunks_for_embedding(cfg.id)
        if not chunks:
            return "Нет чанков в базе. Выполните: conf-doc index"

        faiss_idx = self.faiss_index_for(cfg.name)
        index_path = faiss_idx.index_path
        legacy_path = self.config.output / "vectors" / "index.faiss"

        if not index_path.exists():
            if legacy_path.exists():
                return (
                    "Индекс векторов в старом расположении (output/vectors/). "
                    "После переиндексации нужно пересобрать эмбеддинги: conf-doc embed"
                )
            return f"Индекс векторов не найден ({index_path}). Выполните: conf-doc embed"

        if not faiss_idx.load():
            return f"Не удалось загрузить индекс ({index_path}). Выполните: conf-doc embed"

        db_chunk_ids = {cid for cid, _text, _hash in chunks}
        mapped_ids = set(faiss_idx._vector_to_chunk.values())
        if not mapped_ids & db_chunk_ids:
            return (
                "Индекс векторов не соответствует чанкам в базе (устарел после index). "
                "Выполните: conf-doc embed"
            )
        return None

    def rebuild_embeddings(self, *, show_progress: bool | None = None) -> int:
        progress = use_progress(show_progress)
        cfg = self.active_configuration
        return self.build_embeddings(cfg.id, cfg.name, show_progress=progress)

    def search(self, query: str, *, top_k: int = 5) -> list[dict[str, object]]:
        cfg = self.active_configuration
        self._faiss = self.faiss_index_for(cfg.name)
        self._faiss.load()
        fetch_k = max(top_k * 8, top_k)
        results = self._faiss.search(self.embedding_provider, query, top_k=fetch_k)
        hits = [self._result_to_dict(r) for r in results]
        hits = [h for h in hits if h.get("name")]
        lexical = self._lexical_name_hits(query, cfg.id)
        hits = apply_name_match_boost(hits, query, lexical)
        deduped = self._dedupe_hits(hits, top_k=top_k * 3)
        return self._rank_hits(deduped, top_k=top_k)

    def _lexical_name_hits(self, query: str, config_id: int) -> list[dict[str, object]]:
        objects = self.indexer.find_objects_by_exact_name(config_id, query)
        hits: list[dict[str, object]] = []
        for obj in objects:
            strength = query_match_strength(query, str(obj["name"]), str(obj.get("synonym") or ""))
            if strength <= 0:
                continue
            chunk = self.indexer.get_preferred_chunk(int(str(obj["id"])))
            if chunk is None:
                continue
            hits.append(
                {
                    "chunk_id": chunk["id"],
                    "score": 0.0,
                    "text": chunk.get("text", ""),
                    "object_type": chunk.get("object_type", ""),
                    "name": chunk.get("name", ""),
                    "synonym": chunk.get("synonym", ""),
                    "configuration_name": chunk.get("configuration_name", ""),
                    "configuration_synonym": chunk.get("configuration_synonym", ""),
                    "md_path": chunk.get("md_path", ""),
                    "chunk_index": chunk.get("chunk_index", 0),
                    "_match_strength": strength,
                }
            )
        hits.sort(key=lambda h: object_type_rank(str(h.get("object_type", ""))))
        return hits

    @staticmethod
    def _rank_hits(hits: list[dict[str, object]], *, top_k: int) -> list[dict[str, object]]:
        return sorted(
            hits,
            key=lambda h: (
                -hit_score(h),
                object_type_rank(str(h.get("object_type", ""))),
            ),
        )[:top_k]

    @staticmethod
    def _dedupe_hits(hits: list[dict[str, object]], *, top_k: int) -> list[dict[str, object]]:
        best: dict[tuple[object, object], dict[str, object]] = {}
        for hit in hits:
            key = (hit.get("object_type"), hit.get("name"))
            text = str(hit.get("text", ""))
            score = hit_score(hit)
            has_help = "## Справка" in text or "предназначен" in text.lower()
            prev = best.get(key)
            if prev is None:
                best[key] = hit
                continue
            prev_score = hit_score(prev)
            prev_text = str(prev.get("text", ""))
            prev_has_help = "## Справка" in prev_text or "предназначен" in prev_text.lower()
            prefer_help = has_help and not prev_has_help and score >= prev_score - 0.05
            if score > prev_score + 0.02 or prefer_help:
                best[key] = hit
        ranked = sorted(best.values(), key=lambda h: hit_score(h), reverse=True)
        return ranked[:top_k]

    def query_rag(self, question: str, *, top_k: int = 5) -> dict[str, object]:
        hits = self.search(question, top_k=top_k)
        context_parts: list[str] = []
        for hit in hits:
            text = str(hit.get("text", ""))
            obj_type = hit.get("object_type", "")
            name = hit.get("name", "")
            config_name = hit.get("configuration_name", "")
            context_parts.append(f"[{config_name} / {obj_type}: {name}]\n{text}")

        context = "\n\n---\n\n".join(context_parts)
        prompt = (
            "Ответь на вопрос пользователя на основе справочной информации конфигурации 1С.\n"
            "Если данных недостаточно, так и скажи.\n\n"
            f"Контекст:\n{context}\n\n"
            f"Вопрос: {question}"
        )
        answer = self.llm.generate(prompt)
        return {"answer": answer, "sources": hits}

    def _result_to_dict(self, result: SearchResult) -> dict[str, object]:
        row = self.indexer.get_chunk_by_id(result.chunk_id)
        if row is None:
            return {"chunk_id": result.chunk_id, "score": result.score}
        return {
            "chunk_id": result.chunk_id,
            "score": result.score,
            "text": row.get("text", ""),
            "object_type": row.get("object_type", ""),
            "name": row.get("name", ""),
            "synonym": row.get("synonym", ""),
            "configuration_name": row.get("configuration_name", ""),
            "configuration_synonym": row.get("configuration_synonym", ""),
            "md_path": row.get("md_path", ""),
            "chunk_index": row.get("chunk_index", 0),
        }
