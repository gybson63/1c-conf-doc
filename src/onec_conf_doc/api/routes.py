"""FastAPI routes."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, cast

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from onec_conf_doc import __version__
from onec_conf_doc.api.jobs import (
    JobStatus,
    JobStore,
    start_path_index,
    start_reindex_job,
    start_zip_index,
)
from onec_conf_doc.api.logging_buffer import get_log_handler
from onec_conf_doc.api.upload import UploadError, validate_source_path
from onec_conf_doc.metadata.odata import build_odata_fields_payload
from onec_conf_doc.rag.pipeline import Pipeline


class ReindexRequest(BaseModel):
    source: str | None = None
    skip_embeddings: bool = False
    force: bool = False
    async_job: bool = False


class IndexRequest(BaseModel):
    source: str = Field(..., min_length=1)
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

    def get_jobs(request: Request) -> JobStore:
        return cast(JobStore, request.app.state.jobs)

    def get_config(request: Request):
        return request.app.state.config

    def resolve_pipeline(request: Request, configuration: str | None) -> Pipeline:
        pipeline = get_pipeline(request)
        if configuration:
            pipeline.config.configuration = configuration
            pipeline._active_config = None
        return pipeline

    @router.get("/health")
    def health(request: Request) -> dict[str, Any]:
        pipeline = get_pipeline(request)
        db_status = "ok"
        status = "ok"
        configurations_count = 0
        try:
            configurations_count = len(pipeline.indexer.list_configurations())
        except Exception:
            db_status = "error"
            status = "degraded"
        return {
            "status": status,
            "version": __version__,
            "database": db_status,
            "configurations_count": configurations_count,
        }

    @router.get("/logs")
    def get_logs(
        tail: int = Query(default=200, ge=1, le=1000),
        since_id: int | None = Query(default=None, ge=0),
    ) -> dict[str, Any]:
        handler = get_log_handler()
        records = handler.since(since_id) if since_id is not None else handler.tail(tail)
        return {
            "records": [r.to_dict() for r in records],
            "last_id": handler.last_id,
        }

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

    @router.delete("/configurations/{name}")
    def delete_configuration(
        name: str,
        request: Request,
        remove_files: bool = Query(default=True),
    ) -> dict[str, Any]:
        pipeline = get_pipeline(request)
        try:
            result = pipeline.delete_configuration(name, remove_files=remove_files)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {
            "name": result.name,
            "docs_removed": result.docs_removed,
            "vectors_removed": result.vectors_removed,
        }

    @router.get("/configurations/jobs")
    def list_jobs(
        request: Request,
        limit: int = Query(default=50, ge=1, le=100),
    ) -> list[dict[str, Any]]:
        jobs = get_jobs(request)
        return [job.to_summary() for job in jobs.list_jobs(limit=limit)]

    @router.get("/configurations/jobs/{job_id}")
    def get_job(job_id: str, request: Request) -> dict[str, Any]:
        jobs = get_jobs(request)
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
        return job.to_detail()

    @router.post("/configurations/index", status_code=202)
    def index_from_path(body: IndexRequest, request: Request) -> dict[str, str]:
        config = get_config(request)
        pipeline = get_pipeline(request)
        jobs = get_jobs(request)
        try:
            source_path = Path(body.source)
            validate_source_path(source_path, config.resolved_import_roots())
        except UploadError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        job = start_path_index(
            jobs,
            pipeline,
            config,
            source_path,
            skip_embeddings=body.skip_embeddings,
            force=body.force,
        )
        return {"job_id": job.id}

    @router.post("/configurations/upload", status_code=202)
    async def upload_configuration(
        request: Request,
        file: UploadFile = File(...),  # noqa: B008
        skip_embeddings: bool = False,
        force: bool = False,
    ) -> dict[str, str]:
        if not file.filename or not file.filename.lower().endswith(".zip"):
            raise HTTPException(status_code=400, detail="Only .zip files are supported")

        config = get_config(request)
        pipeline = get_pipeline(request)
        jobs = get_jobs(request)

        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
            tmp_path = Path(tmp.name)
            content = await file.read()
            tmp.write(content)

        job = start_zip_index(
            jobs,
            pipeline,
            config,
            tmp_path,
            skip_embeddings=skip_embeddings,
            force=force,
        )
        return {"job_id": job.id}

    @router.post("/reindex")
    def reindex(body: ReindexRequest, request: Request) -> dict[str, Any]:
        config = get_config(request)
        pipeline = get_pipeline(request)
        jobs = get_jobs(request)

        if body.async_job:
            if body.source:
                try:
                    export_root = validate_source_path(
                        Path(body.source),
                        config.resolved_import_roots(),
                    )
                except UploadError as exc:
                    raise HTTPException(status_code=400, detail=str(exc)) from exc
            else:
                export_root = config.source
            job = start_reindex_job(
                jobs,
                pipeline,
                export_root,
                skip_embeddings=body.skip_embeddings,
                force=body.force,
            )
            return {"job_id": job.id, "status": JobStatus.PENDING.value}

        if body.source:
            source_path = Path(body.source)
            try:
                export_root = validate_source_path(source_path, config.resolved_import_roots())
            except UploadError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            stats = pipeline.index_export(
                source=export_root,
                skip_embeddings=body.skip_embeddings,
                force=body.force,
                show_progress=False,
            )
        else:
            stats = pipeline.index_export(
                skip_embeddings=body.skip_embeddings,
                force=body.force,
                show_progress=False,
            )
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

    @router.get("/roles/by-object")
    def search_roles_by_object_route(
        request: Request,
        object_name: str = Query(
            ...,
            min_length=1,
            alias="object",
            description="Имя объекта метаданных",
        ),
        rights: str | None = Query(
            default=None,
            description="Фильтр прав через запятую (роль должна выдавать все перечисленные)",
        ),
        metadata_type: str | None = Query(
            default=None,
            description="Тип метаданных секции прав (Catalog, Document, …)",
        ),
        configuration: str | None = Query(default=None),
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        pipeline = resolve_pipeline(request, configuration)
        return pipeline.search_roles_by_object(
            object_name,
            rights=rights,
            metadata_type=metadata_type,
            limit=limit,
        )

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
                        dimensions=fields_data.get("dimensions"),  # type: ignore[arg-type]
                        resources=fields_data.get("resources"),  # type: ignore[arg-type]
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


def create_ui_router(static_dir: Path) -> APIRouter:
    router = APIRouter()

    @router.get("/", include_in_schema=False)
    def index_page() -> FileResponse:
        return FileResponse(static_dir / "index.html")

    @router.get("/object/{object_type}/{name}", include_in_schema=False)
    def object_page(
        object_type: str,
        name: str,
    ) -> FileResponse:
        return FileResponse(static_dir / "index.html")

    return router
