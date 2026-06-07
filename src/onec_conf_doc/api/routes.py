"""FastAPI routes."""

from __future__ import annotations

from typing import Any, cast

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from onec_conf_doc.metadata.odata import build_odata_fields_payload
from onec_conf_doc.rag.pipeline import Pipeline


class ReindexRequest(BaseModel):
    skip_embeddings: bool = False
    force: bool = False


class SearchRequest(BaseModel):
    query: str
    top_k: int = Field(default=5, ge=1, le=50)
    full: bool = False
    include_fields: bool = True
    object_type: str | None = None
    configuration: str | None = None


class QueryRequest(BaseModel):
    question: str
    top_k: int = Field(default=5, ge=1, le=20)
    configuration: str | None = None


def create_router() -> APIRouter:
    router = APIRouter()

    def get_pipeline(request: Request) -> Pipeline:
        return cast(Pipeline, request.app.state.pipeline)

    def resolve_pipeline(request: Request, configuration: str | None) -> Pipeline:
        pipeline = get_pipeline(request)
        if configuration:
            pipeline.config.configuration = configuration
            pipeline._active_config = None
        return pipeline

    @router.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @router.get("/configurations")
    def list_configurations(request: Request) -> list[dict[str, Any]]:
        pipeline = get_pipeline(request)
        return [
            {
                "name": c.name,
                "synonym": c.synonym,
                "version": c.version,
                "export_path": c.export_path,
                "indexed_at": c.indexed_at,
                "objects_count": c.objects_count,
            }
            for c in pipeline.indexer.list_configurations()
        ]

    @router.post("/reindex")
    def reindex(body: ReindexRequest, request: Request) -> dict[str, Any]:
        pipeline = get_pipeline(request)
        stats = pipeline.index_export(skip_embeddings=body.skip_embeddings, force=body.force)
        return {
            "configuration_name": stats.configuration_name,
            "configuration_synonym": stats.configuration_synonym,
            "objects_total": stats.objects_total,
            "objects_updated": stats.objects_updated,
            "objects_skipped": stats.objects_skipped,
            "objects_deleted": stats.objects_deleted,
            "chunks_total": stats.chunks_total,
            "chunks_rebuilt": stats.chunks_rebuilt,
            "embeddings_cached": stats.embeddings_cached,
            "embeddings_computed": stats.embeddings_computed,
        }

    @router.get("/objects")
    def list_objects(
        request: Request,
        object_type: str | None = Query(default=None),
        q: str | None = Query(default=None),
        configuration: str | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        pipeline = resolve_pipeline(request, configuration)
        cfg = pipeline.active_configuration
        objects = pipeline.indexer.list_objects(
            config_id=cfg.id,
            object_type=object_type,
            query=q,
            limit=limit,
        )
        return [
            {
                "id": obj.id,
                "configuration_name": cfg.name,
                "object_type": obj.object_type,
                "name": obj.name,
                "synonym": obj.synonym,
                "comment": obj.comment,
                "md_path": obj.md_path,
            }
            for obj in objects
        ]

    @router.post("/search")
    def search(body: SearchRequest, request: Request) -> list[dict[str, Any]]:
        pipeline = resolve_pipeline(request, body.configuration)
        cfg = pipeline.active_configuration
        results = pipeline.search(body.query, top_k=body.top_k)
        if body.object_type:
            results = [r for r in results if r.get("object_type") == body.object_type]
        if not body.full:
            for hit in results:
                text = str(hit.get("text", ""))
                if len(text) > 800:
                    hit["text"] = text[:800] + "..."
        if body.include_fields and results:
            top = results[0]
            object_type = str(top.get("object_type", ""))
            obj_name = str(top.get("name", ""))
            if object_type and obj_name:
                fields_data = pipeline.indexer.get_object_fields(
                    object_type,
                    obj_name,
                    config_id=cfg.id,
                )
                if fields_data is not None:
                    top["odata_fields"] = build_odata_fields_payload(
                        object_type,
                        obj_name,
                        fields_data["attributes"],  # type: ignore[arg-type]
                        fields_data["tabular_sections"],  # type: ignore[arg-type]
                    )
        return results

    @router.get("/objects/{object_type}/{name}")
    def get_object(
        object_type: str,
        name: str,
        request: Request,
        configuration: str | None = Query(default=None),
    ) -> dict[str, Any]:
        pipeline = resolve_pipeline(request, configuration)
        cfg = pipeline.active_configuration
        detail = pipeline.indexer.get_object_detail(
            object_type,
            name,
            config_id=cfg.id,
        )
        if detail is None:
            raise HTTPException(
                status_code=404,
                detail=f"Object not found: {cfg.name} / {object_type}.{name}",
            )
        return detail

    @router.get("/objects/{object_type}/{name}/chunks/{chunk_index}")
    def get_object_chunk(
        object_type: str,
        name: str,
        chunk_index: int,
        request: Request,
        configuration: str | None = Query(default=None),
    ) -> dict[str, Any]:
        pipeline = resolve_pipeline(request, configuration)
        cfg = pipeline.active_configuration
        text = pipeline.indexer.get_chunk_text(
            object_type,
            name,
            chunk_index,
            config_id=cfg.id,
        )
        if text is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"Chunk not found: {cfg.name} / {object_type}.{name} chunk_index={chunk_index}"
                ),
            )
        return {
            "configuration_name": cfg.name,
            "object_type": object_type,
            "name": name,
            "chunk_index": chunk_index,
            "text": text,
        }

    @router.post("/query")
    def query_rag(body: QueryRequest, request: Request) -> dict[str, Any]:
        pipeline = resolve_pipeline(request, body.configuration)
        if pipeline.config.llm.provider == "none":
            raise HTTPException(
                status_code=503,
                detail="LLM provider is disabled. Set llm.provider in config.yaml.",
            )
        return pipeline.query_rag(body.question, top_k=body.top_k)

    return router
