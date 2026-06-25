"""FastAPI routes."""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any, cast

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from onec_conf_doc import __version__
from onec_conf_doc.api.embeddings_settings import (
    EmbeddingsSettingsUpdate,
    apply_configuration_embeddings,
    merge_embeddings_settings,
)
from onec_conf_doc.api.jobs import (
    JobStatus,
    JobStore,
    import_path_to_configuration_slot,
    import_zip_to_configuration_slot,
    register_export_slot,
    start_delete_job,
    start_path_index,
    start_reindex_job,
    start_slot_embed,
    start_slot_import_path,
    start_slot_import_zip,
    start_slot_index,
    start_zip_index,
)
from onec_conf_doc.api.logging_buffer import get_log_handler
from onec_conf_doc.api.upload import UploadError, validate_source_path
from onec_conf_doc.config import (
    AppConfig,
    EmbeddingsConfig,
    embeddings_settings_public,
    save_config,
)
from onec_conf_doc.export_detect import (
    configuration_matches_expected,
    detect_export_configuration,
    validate_expected_configuration,
)
from onec_conf_doc.export_slot import (
    ExportSlotError,
    ensure_export_slot,
    export_dir_for,
    is_reserved_slot_name,
    slot_export_linked,
    slot_export_root,
    slot_has_export,
    validate_slot_name,
)
from onec_conf_doc.metadata.odata import build_odata_fields_payload
from onec_conf_doc.rag.embeddings import create_embedding_provider
from onec_conf_doc.rag.faiss_index import FaissIndex
from onec_conf_doc.rag.pipeline import Pipeline

logger = logging.getLogger("onec_conf_doc")


class ReindexRequest(BaseModel):
    source: str | None = None
    expected_configuration: str | None = None
    skip_embeddings: bool = False
    force: bool = False
    async_job: bool = False
    embeddings: EmbeddingsSettingsUpdate | None = None


class IndexRequest(BaseModel):
    source: str = Field(..., min_length=1)
    expected_configuration: str | None = None
    skip_embeddings: bool = False
    force: bool = False
    embeddings: EmbeddingsSettingsUpdate | None = None


class DetectExportRequest(BaseModel):
    source: str = Field(..., min_length=1)
    expected_configuration: str | None = None


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


class RegisterConfigurationRequest(BaseModel):
    name: str = Field(..., min_length=1)


class ImportPathRequest(BaseModel):
    source: str = Field(..., min_length=1)
    mirror: bool = False


class SlotIndexRequest(BaseModel):
    skip_embeddings: bool = False
    force: bool = False
    embeddings: EmbeddingsSettingsUpdate | None = None


class SlotEmbedRequest(BaseModel):
    force: bool = False
    embeddings: EmbeddingsSettingsUpdate | None = None


def _configuration_slot_path(config: AppConfig, name: str) -> str:
    return str(export_dir_for(config, name).resolve())


def _slot_status(config: AppConfig, name: str) -> str:
    slot = export_dir_for(config, name)
    if not slot.is_dir():
        return "missing"
    try:
        if not any(slot.iterdir()):
            return "missing"
    except OSError:
        return "missing"
    if slot_has_export(config, name):
        return "ready"
    return "invalid"


def _configuration_summary(
    config: AppConfig,
    pipeline: Pipeline,
    *,
    name: str,
    synonym: str = "",
    version: str = "",
    export_path: str = "",
    indexed_at: str = "",
    objects_count: int = 0,
    in_database: bool = False,
) -> dict[str, Any]:
    slot_path = _configuration_slot_path(config, name)
    has_export = slot_has_export(config, name)
    slot_status = _slot_status(config, name)
    export_linked = slot_export_linked(config, name)
    embedding_status = _embedding_index_status(config, name) if in_database else "missing"
    return {
        "name": name,
        "synonym": synonym,
        "version": version,
        "export_path": export_path or slot_path,
        "export_slot_path": slot_path,
        "has_export": has_export,
        "export_linked": export_linked,
        "slot_status": slot_status,
        "in_database": in_database,
        "indexed_at": indexed_at or None,
        "objects_count": objects_count,
        "embedding_model": _indexed_embedding_model(config, name) if in_database else None,
        "embedding_status": embedding_status
        if in_database
        else ("missing" if not has_export else "ready"),
        "embeddings_provider": config.embeddings_for(name).provider,
        "embeddings_model": config.embeddings_for(name).model,
        "embeddings_custom": name in config.configuration_embeddings,
    }


def _indexed_embedding_model(config, configuration_name: str) -> str | None:
    return FaissIndex.read_stored_model(config.vectors_dir_for(configuration_name))


def _embedding_index_status(config, configuration_name: str) -> str:
    indexed_model = _indexed_embedding_model(config, configuration_name)
    expected_model = config.embeddings_for(configuration_name).model
    if indexed_model is None:
        return "missing"
    if indexed_model != expected_model:
        return "stale"
    return "ok"


def _effective_embeddings_config(config: AppConfig, configuration: str | None) -> EmbeddingsConfig:
    if configuration:
        return config.embeddings_for(configuration)
    return config.embeddings


def _maybe_save_index_embeddings(
    config: AppConfig,
    pipeline: Pipeline,
    configuration_name: str,
    embeddings: EmbeddingsSettingsUpdate | None,
    *,
    skip_embeddings: bool,
    config_path: Path | None,
) -> None:
    if skip_embeddings or embeddings is None:
        return
    apply_configuration_embeddings(
        config,
        pipeline,
        configuration_name,
        embeddings,
        config_path=config_path,
    )


def create_router() -> APIRouter:
    router = APIRouter()

    def get_pipeline(request: Request) -> Pipeline:
        return cast(Pipeline, request.app.state.pipeline)

    def get_jobs(request: Request) -> JobStore:
        return cast(JobStore, request.app.state.jobs)

    def get_config(request: Request):
        return request.app.state.config

    def get_config_path(request: Request) -> Path | None:
        return getattr(request.app.state, "config_path", None)

    def resolve_pipeline(request: Request, configuration: str | None) -> Pipeline:
        pipeline = get_pipeline(request)
        if configuration:
            pipeline.config.configuration = configuration
            pipeline._active_config = None
        return pipeline

    @router.get("/health")
    def health(request: Request) -> dict[str, Any]:
        pipeline = get_pipeline(request)
        config = get_config(request)
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
            "embeddings": embeddings_settings_public(config.embeddings),
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
        config = get_config(request)
        seen: set[str] = set()
        items: list[dict[str, Any]] = []
        for c in pipeline.indexer.list_configurations():
            seen.add(c.name)
            items.append(
                _configuration_summary(
                    config,
                    pipeline,
                    name=c.name,
                    synonym=c.synonym,
                    version=c.version,
                    export_path=c.export_path,
                    indexed_at=c.indexed_at,
                    objects_count=c.objects_count,
                    in_database=True,
                )
            )
        exports_root = config.exports_dir()
        if exports_root.is_dir():
            for child in sorted(exports_root.iterdir()):
                if not child.is_dir() or child.name.startswith("_"):
                    continue
                if child.name in seen or is_reserved_slot_name(child.name):
                    continue
                try:
                    if not any(child.iterdir()):
                        continue
                except OSError:
                    continue
                try:
                    validate_slot_name(child.name)
                except ExportSlotError:
                    continue
                items.append(
                    _configuration_summary(
                        config,
                        pipeline,
                        name=child.name,
                        in_database=False,
                    )
                )
        return items

    @router.post("/configurations", status_code=201)
    def register_configuration(
        body: RegisterConfigurationRequest,
        request: Request,
    ) -> dict[str, Any]:
        config = get_config(request)
        try:
            name = validate_slot_name(body.name)
            slot = register_export_slot(config, name)
        except ExportSlotError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"name": name, "export_slot_path": str(slot)}

    @router.get("/configurations/jobs")
    def list_jobs(
        request: Request,
        limit: int = Query(default=50, ge=1, le=100),
    ) -> list[dict[str, Any]]:
        jobs = get_jobs(request)
        return [job.to_summary() for job in jobs.list_jobs(limit=limit)]

    @router.get("/configurations/jobs/{job_id}")
    def get_job(
        job_id: str,
        request: Request,
        since_log: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        jobs = get_jobs(request)
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
        return job.to_detail(since_log=since_log)

    @router.get("/configurations/{name}")
    def get_configuration(name: str, request: Request) -> dict[str, Any]:
        config = get_config(request)
        pipeline = get_pipeline(request)
        if is_reserved_slot_name(name):
            raise HTTPException(status_code=404, detail=f"Configuration not found: {name}")
        try:
            validate_slot_name(name)
        except ExportSlotError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        row = pipeline.indexer.resolve_configuration(name)
        if row is not None:
            return _configuration_summary(
                config,
                pipeline,
                name=row.name,
                synonym=row.synonym,
                version=row.version,
                export_path=row.export_path,
                indexed_at=row.indexed_at,
                objects_count=row.objects_count,
                in_database=True,
            )
        slot = export_dir_for(config, name)
        if not slot.is_dir():
            raise HTTPException(status_code=404, detail=f"Configuration not found: {name}")
        return _configuration_summary(config, pipeline, name=name, in_database=False)

    @router.delete("/configurations/{name}")
    def delete_configuration(
        name: str,
        request: Request,
        remove_files: bool = Query(default=True),
        async_job: bool = Query(default=False),
    ) -> dict[str, Any]:
        pipeline = get_pipeline(request)
        jobs = get_jobs(request)
        logger.info(
            "DELETE /configurations/%s (remove_files=%s, async_job=%s)",
            name,
            remove_files,
            async_job,
        )
        if async_job:
            job = start_delete_job(jobs, pipeline, name, remove_files=remove_files)
            return {"job_id": job.id, "status": JobStatus.PENDING.value}
        try:
            result = pipeline.delete_configuration(name, remove_files=remove_files)
        except ValueError as exc:
            logger.warning("Конфигурация не найдена: %s", name)
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {
            "name": result.name,
            "objects_count": result.objects_count,
            "docs_removed": result.docs_removed,
            "vectors_removed": result.vectors_removed,
            "export_removed": result.export_removed,
        }

    @router.post("/configurations/{name}/import")
    async def import_configuration_export(
        name: str,
        request: Request,
        file: UploadFile | None = File(None),  # noqa: B008
        source: str | None = Form(None),
        async_job: bool = Query(default=False),
    ) -> dict[str, Any]:
        config = get_config(request)
        jobs = get_jobs(request)
        try:
            slot_name = validate_slot_name(name)
            ensure_export_slot(config, slot_name)
        except ExportSlotError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        has_file = file is not None and file.filename
        has_source = bool(source and source.strip())
        if has_file == has_source:
            raise HTTPException(
                status_code=400,
                detail="Provide exactly one of: ZIP file or source path",
            )

        if async_job:
            if not has_file:
                raise HTTPException(
                    status_code=400,
                    detail="async_job поддерживается только для ZIP-файла",
                )
            upload = file
            assert upload is not None
            if not upload.filename or not upload.filename.lower().endswith(".zip"):
                raise HTTPException(status_code=400, detail="Only .zip files are supported")
            with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
                tmp_path = Path(tmp.name)
                tmp.write(await upload.read())
            job = start_slot_import_zip(jobs, config, slot_name, tmp_path)
            return {"job_id": job.id, "status": JobStatus.PENDING.value, "name": slot_name}

        try:
            if has_file:
                upload = file
                assert upload is not None
                if not upload.filename or not upload.filename.lower().endswith(".zip"):
                    raise HTTPException(status_code=400, detail="Only .zip files are supported")
                with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
                    tmp_path = Path(tmp.name)
                    tmp.write(await upload.read())
                try:
                    export_root = import_zip_to_configuration_slot(config, slot_name, tmp_path)
                finally:
                    tmp_path.unlink(missing_ok=True)
            else:
                export_root = import_path_to_configuration_slot(
                    config,
                    slot_name,
                    Path(source.strip()),  # type: ignore[union-attr]
                )
        except UploadError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        try:
            detected = detect_export_configuration(export_root)
            validate_expected_configuration(detected, slot_name)
        except (UploadError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "name": slot_name,
            "export_slot_path": str(export_root.resolve()),
            "detected_name": detected.name,
            "synonym": detected.synonym,
            "version": detected.version,
        }

    @router.post("/configurations/{name}/import-path")
    def import_configuration_from_path(
        name: str,
        body: ImportPathRequest,
        request: Request,
        async_job: bool = Query(default=False),
    ) -> dict[str, Any]:
        config = get_config(request)
        jobs = get_jobs(request)
        try:
            slot_name = validate_slot_name(name)
            ensure_export_slot(config, slot_name)
        except ExportSlotError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        if async_job:
            job = start_slot_import_path(
                jobs,
                config,
                slot_name,
                Path(body.source),
                mirror=body.mirror,
            )
            return {"job_id": job.id, "status": JobStatus.PENDING.value, "name": slot_name}

        try:
            export_root = import_path_to_configuration_slot(
                config,
                slot_name,
                Path(body.source),
                mirror=body.mirror,
            )
        except (ExportSlotError, UploadError, ValueError, OSError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            detected = detect_export_configuration(export_root)
            validate_expected_configuration(detected, slot_name)
        except (UploadError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "name": slot_name,
            "export_slot_path": str(export_root.resolve()),
            "detected_name": detected.name,
            "synonym": detected.synonym,
            "version": detected.version,
        }

    @router.post("/configurations/{name}/detect")
    def detect_configuration_slot(name: str, request: Request) -> dict[str, Any]:
        config = get_config(request)
        try:
            slot_name = validate_slot_name(name)
            if not slot_has_export(config, slot_name):
                raise HTTPException(
                    status_code=400,
                    detail=f"В слоте «{slot_name}» нет выгрузки. Импортируйте ZIP или путь.",
                )
            export_root = slot_export_root(config, slot_name)
            detected = detect_export_configuration(export_root)
        except (ExportSlotError, UploadError, ValueError, OSError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        matches = configuration_matches_expected(detected.name, slot_name)
        result: dict[str, Any] = {
            "name": detected.name,
            "synonym": detected.synonym,
            "version": detected.version,
            "export_path": str(export_root.resolve()),
            "export_slot_path": _configuration_slot_path(config, slot_name),
            "matches_expected": matches,
            "slot_name": slot_name,
        }
        if not matches:
            result["message"] = (
                f"В слоте «{slot_name}» выгрузка «{detected.name}», имена не совпадают"
            )
        emb = embeddings_settings_public(config.embeddings_for(slot_name))
        emb["configuration"] = slot_name
        emb["uses_default"] = slot_name not in config.configuration_embeddings
        result["embeddings"] = emb
        return result

    @router.post("/configurations/{name}/index", status_code=202)
    def index_configuration_slot(
        name: str,
        body: SlotIndexRequest,
        request: Request,
    ) -> dict[str, str]:
        config = get_config(request)
        pipeline = get_pipeline(request)
        jobs = get_jobs(request)
        try:
            job = start_slot_index(
                jobs,
                pipeline,
                config,
                name,
                skip_embeddings=body.skip_embeddings,
                force=body.force,
                embeddings=body.embeddings,
                config_path=get_config_path(request),
            )
        except (ExportSlotError, UploadError, ValueError, OSError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"job_id": job.id}

    @router.post("/configurations/{name}/embed", status_code=202)
    def embed_configuration_slot(
        name: str,
        body: SlotEmbedRequest,
        request: Request,
    ) -> dict[str, str]:
        config = get_config(request)
        pipeline = get_pipeline(request)
        jobs = get_jobs(request)
        try:
            job = start_slot_embed(
                jobs,
                pipeline,
                config,
                name,
                force=body.force,
                embeddings=body.embeddings,
                config_path=get_config_path(request),
            )
        except (ExportSlotError, UploadError, ValueError, OSError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"job_id": job.id}

    @router.post("/configurations/detect")
    def detect_configuration(body: DetectExportRequest, request: Request) -> dict[str, Any]:
        config = get_config(request)
        try:
            source_path = Path(body.source)
            validate_source_path(source_path, config.resolved_import_roots())
            detected = detect_export_configuration(source_path)
        except (UploadError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        matches = configuration_matches_expected(detected.name, body.expected_configuration)
        result: dict[str, Any] = {
            "name": detected.name,
            "synonym": detected.synonym,
            "version": detected.version,
            "export_path": detected.export_path,
            "matches_expected": matches,
        }
        if body.expected_configuration and not matches:
            result["expected_configuration"] = body.expected_configuration
            result["message"] = (
                f"В папке «{detected.name}», ожидалась «{body.expected_configuration}»"
            )
        emb = embeddings_settings_public(config.embeddings_for(detected.name))
        emb["configuration"] = detected.name
        emb["uses_default"] = detected.name not in config.configuration_embeddings
        result["embeddings"] = emb
        return result

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
        try:
            detected = detect_export_configuration(source_path)
            validate_expected_configuration(detected, body.expected_configuration)
        except (UploadError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        _maybe_save_index_embeddings(
            config,
            pipeline,
            detected.name,
            body.embeddings,
            skip_embeddings=body.skip_embeddings,
            config_path=get_config_path(request),
        )

        job = start_path_index(
            jobs,
            pipeline,
            config,
            source_path,
            skip_embeddings=body.skip_embeddings,
            force=body.force,
            expected_configuration=body.expected_configuration,
        )
        return {"job_id": job.id}

    @router.post("/configurations/upload", status_code=202)
    async def upload_configuration(
        request: Request,
        file: UploadFile = File(...),  # noqa: B008
        skip_embeddings: bool = False,
        force: bool = False,
        expected_configuration: str | None = None,
        embeddings: str | None = Form(None),
    ) -> dict[str, str]:
        if not file.filename or not file.filename.lower().endswith(".zip"):
            raise HTTPException(status_code=400, detail="Only .zip files are supported")

        embeddings_update: EmbeddingsSettingsUpdate | None = None
        if embeddings:
            try:
                embeddings_update = EmbeddingsSettingsUpdate.model_validate_json(embeddings)
            except Exception as exc:
                raise HTTPException(status_code=400, detail=f"Invalid embeddings: {exc}") from exc

        config = get_config(request)
        pipeline = get_pipeline(request)
        jobs = get_jobs(request)
        config_path = get_config_path(request)

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
            expected_configuration=expected_configuration,
            embeddings=embeddings_update,
            config_path=config_path,
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
                expected_configuration=body.expected_configuration,
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
                expected_configuration=body.expected_configuration,
                skip_embeddings=body.skip_embeddings,
                force=body.force,
                show_progress=False,
            )
        else:
            stats = pipeline.index_export(
                expected_configuration=body.expected_configuration,
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

    @router.get("/settings/embeddings")
    def get_embeddings_settings(
        request: Request,
        configuration: str | None = Query(default=None),
    ) -> dict[str, Any]:
        config = get_config(request)
        current = _effective_embeddings_config(config, configuration)
        payload = embeddings_settings_public(current)
        payload["configuration"] = configuration
        payload["uses_default"] = (
            configuration is not None and configuration not in config.configuration_embeddings
        )
        return payload

    @router.put("/settings/embeddings")
    def update_embeddings_settings(
        body: EmbeddingsSettingsUpdate,
        request: Request,
        configuration: str | None = Query(default=None),
    ) -> dict[str, Any]:
        config = get_config(request)
        pipeline = get_pipeline(request)
        current = _effective_embeddings_config(config, configuration)
        updated = merge_embeddings_settings(current, body)
        if configuration:
            config.configuration_embeddings[configuration] = updated
            pipeline.reset_embedding_provider(configuration)
        else:
            config.embeddings = updated
            pipeline.reset_embedding_provider()
        pipeline.config.embeddings = config.embeddings
        pipeline.config.configuration_embeddings = config.configuration_embeddings

        config_path = get_config_path(request)
        if config_path is not None:
            save_config(config, config_path)

        logger.info(
            "Embeddings settings updated: configuration=%s provider=%s model=%s",
            configuration or "(default)",
            updated.provider,
            updated.model,
        )
        payload = embeddings_settings_public(updated)
        payload["configuration"] = configuration
        payload["uses_default"] = False
        return payload

    @router.post("/settings/embeddings/test")
    def test_embeddings_settings(
        body: EmbeddingsSettingsUpdate,
        request: Request,
        configuration: str | None = Query(default=None),
    ) -> dict[str, Any]:
        config = get_config(request)
        current = _effective_embeddings_config(config, configuration)
        candidate = merge_embeddings_settings(current, body)
        try:
            provider = create_embedding_provider(candidate)
            vector = provider.embed_query("connection test")
        except Exception as exc:
            logger.warning("Embeddings connection test failed: %s", exc)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "ok": True,
            "configuration": configuration,
            "provider": candidate.provider,
            "model": candidate.model,
            "dimension": len(vector),
        }

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

    @router.get("/configuration/{name:path}", include_in_schema=False)
    def configuration_page(name: str) -> FileResponse:
        return FileResponse(static_dir / "index.html")

    return router
