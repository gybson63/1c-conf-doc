"""Background indexing jobs with in-memory store."""

from __future__ import annotations

import logging
import re
import tempfile
import threading
import traceback
import uuid
import zipfile
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from onec_conf_doc.api.embeddings_settings import (
    EmbeddingsSettingsUpdate,
    apply_configuration_embeddings,
)
from onec_conf_doc.api.upload import UploadError, safe_extract_zip, validate_source_path
from onec_conf_doc.config import AppConfig
from onec_conf_doc.export_detect import detect_export_configuration, validate_expected_configuration
from onec_conf_doc.export_slot import (
    ensure_export_slot,
    import_path_to_slot,
    import_zip_to_slot,
    slot_export_root,
    slot_has_export,
    validate_slot_name,
)
from onec_conf_doc.rag.pipeline import DeleteConfigurationResult, IndexStats, Pipeline

logger = logging.getLogger("onec_conf_doc.jobs")

MAX_JOBS = 100
MAX_JOB_LOG_LINES = 500

_PROGRESS_OBJECTS = re.compile(r"Обработано\s+(\d+)/(\d+)\s+объект")
_PROGRESS_EMBEDDINGS = re.compile(r"Эмбеддинги:\s+(\d+)/(\d+)")


class JobStatus(StrEnum):
    PENDING = "pending"
    EXTRACTING = "extracting"
    INDEXING = "indexing"
    DELETING = "deleting"
    COMPLETED = "completed"
    FAILED = "failed"


class JobType(StrEnum):
    PATH = "path"
    ZIP = "zip"
    REINDEX = "reindex"
    INDEX = "index"
    EMBED = "embed"
    DELETE = "delete"
    IMPORT_ZIP = "import_zip"
    IMPORT_PATH = "import_path"


@dataclass
class Job:
    id: str
    type: JobType
    status: JobStatus
    source: str = ""
    created_at: str = ""
    configuration_name: str | None = None
    expected_configuration: str | None = None
    skip_embeddings: bool = False
    force: bool = False
    embeddings: EmbeddingsSettingsUpdate | None = None
    stats: dict[str, Any] | None = None
    error: str | None = None
    logs: list[str] = field(default_factory=list)

    def to_summary(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type.value,
            "status": self.status.value,
            "source": self.source,
            "created_at": self.created_at,
            "configuration_name": self.configuration_name,
        }

    def progress_snapshot(self) -> dict[str, Any] | None:
        """Structured progress parsed from the latest relevant log line."""
        for line in reversed(self.logs):
            match = _PROGRESS_OBJECTS.search(line)
            if match:
                current, total = int(match.group(1)), int(match.group(2))
                percent = round(100 * current / total) if total else None
                return {
                    "phase": "objects",
                    "current": current,
                    "total": total,
                    "percent": percent,
                    "message": line,
                }
            match = _PROGRESS_EMBEDDINGS.search(line)
            if match:
                current, total = int(match.group(1)), int(match.group(2))
                percent = round(100 * current / total) if total else None
                return {
                    "phase": "embeddings",
                    "current": current,
                    "total": total,
                    "percent": percent,
                    "message": line,
                }
        if self.logs:
            return {"phase": self.status.value, "message": self.logs[-1]}
        return None

    def to_detail(self, *, since_log: int = 0) -> dict[str, Any]:
        result = self.to_summary()
        offset = max(0, min(since_log, len(self.logs)))
        result["logs"] = list(self.logs[offset:])
        result["logs_offset"] = offset
        result["logs_total"] = len(self.logs)
        progress = self.progress_snapshot()
        if progress is not None:
            result["progress"] = progress
        if self.stats is not None:
            result["stats"] = self.stats
        if self.error is not None:
            result["error"] = self.error
        return result


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._order: deque[str] = deque(maxlen=MAX_JOBS)
        self._lock = threading.Lock()

    def create(
        self,
        job_type: JobType,
        *,
        source: str = "",
        configuration_name: str | None = None,
        skip_embeddings: bool = False,
        force: bool = False,
        expected_configuration: str | None = None,
        embeddings: EmbeddingsSettingsUpdate | None = None,
    ) -> Job:
        job_id = str(uuid.uuid4())
        job = Job(
            id=job_id,
            type=job_type,
            status=JobStatus.PENDING,
            source=source,
            created_at=datetime.now(tz=UTC).isoformat(),
            configuration_name=configuration_name,
            skip_embeddings=skip_embeddings,
            force=force,
            expected_configuration=expected_configuration,
            embeddings=embeddings,
        )
        with self._lock:
            self._jobs[job_id] = job
            self._order.appendleft(job_id)
            while len(self._order) > MAX_JOBS:
                old_id = self._order.pop()
                self._jobs.pop(old_id, None)
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list_jobs(self, limit: int = 50) -> list[Job]:
        with self._lock:
            ids = list(self._order)[:limit]
            return [self._jobs[jid] for jid in ids if jid in self._jobs]

    def _append_log(self, job: Job, message: str) -> None:
        ts = datetime.now(tz=UTC).strftime("%H:%M:%S")
        line = f"[{ts}] {message}"
        job.logs.append(line)
        if len(job.logs) > MAX_JOB_LOG_LINES:
            job.logs = job.logs[-MAX_JOB_LOG_LINES:]
        logger.info("[%s] %s", job.id[:8], message)


def _stats_to_dict(stats: IndexStats) -> dict[str, Any]:
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


def _delete_result_to_dict(result: DeleteConfigurationResult) -> dict[str, Any]:
    return {
        "name": result.name,
        "objects_count": result.objects_count,
        "docs_removed": result.docs_removed,
        "vectors_removed": result.vectors_removed,
        "export_removed": result.export_removed,
    }


def run_index_job(
    store: JobStore,
    job: Job,
    pipeline: Pipeline,
    export_root: Path,
) -> None:
    def progress_callback(message: str) -> None:
        store._append_log(job, message)

    try:
        job.status = JobStatus.INDEXING
        store._append_log(job, f"Индексация: {export_root}")
        stats = pipeline.index_export(
            source=export_root,
            expected_configuration=job.expected_configuration,
            skip_embeddings=job.skip_embeddings,
            force=job.force,
            show_progress=False,
            progress_callback=progress_callback,
        )
        job.configuration_name = stats.configuration_name
        job.stats = _stats_to_dict(stats)
        job.status = JobStatus.COMPLETED
        store._append_log(
            job,
            f"Готово: {stats.configuration_name}, объектов {stats.objects_total}, "
            f"чанков {stats.chunks_total}",
        )
    except Exception as exc:
        job.status = JobStatus.FAILED
        job.error = str(exc)
        store._append_log(job, f"Ошибка: {exc}")
        logger.exception("Job %s failed", job.id)


def run_embed_job(
    store: JobStore,
    job: Job,
    pipeline: Pipeline,
    configuration_name: str,
) -> None:
    def progress_callback(message: str) -> None:
        store._append_log(job, message)

    try:
        job.status = JobStatus.INDEXING
        store._append_log(job, f"Только эмбеддинги: «{configuration_name}»")
        row = pipeline.indexer.get_configuration(configuration_name)
        if row is None:
            msg = f"Конфигурация «{configuration_name}» не найдена в базе"
            raise ValueError(msg)
        chunks = pipeline.indexer.count_chunks_for_config(row.id)
        if chunks == 0:
            msg = "Нет чанков в базе — сначала выполните полную индексацию"
            raise ValueError(msg)
        pipeline._active_config = row
        pipeline.config.configuration = configuration_name
        stats = IndexStats(
            configuration_name=configuration_name,
            configuration_synonym=row.synonym,
        )
        count = pipeline.build_embeddings(
            row.id,
            configuration_name,
            show_progress=False,
            force=job.force,
            stats=stats,
            progress_callback=progress_callback,
        )
        job.configuration_name = configuration_name
        job.stats = _stats_to_dict(stats)
        job.status = JobStatus.COMPLETED
        store._append_log(
            job,
            f"Готово: {count} векторов, API {stats.embeddings_computed}, "
            f"кэш {stats.embeddings_cached}",
        )
    except Exception as exc:
        job.status = JobStatus.FAILED
        job.error = str(exc)
        store._append_log(job, f"Ошибка: {exc}")
        logger.exception("Embed job %s failed", job.id)


def start_slot_embed(
    store: JobStore,
    pipeline: Pipeline,
    config: AppConfig,
    configuration_name: str,
    *,
    force: bool = False,
    embeddings: EmbeddingsSettingsUpdate | None = None,
    config_path: Path | None = None,
) -> Job:
    name = validate_slot_name(configuration_name)
    row = pipeline.indexer.get_configuration(name)
    if row is None:
        msg = f"Конфигурация «{name}» не найдена в базе"
        raise ValueError(msg)
    if pipeline.indexer.count_chunks_for_config(row.id) == 0:
        msg = "Нет чанков в базе — сначала выполните полную индексацию"
        raise ValueError(msg)

    job = store.create(
        JobType.EMBED,
        source=name,
        configuration_name=name,
        force=force,
        embeddings=embeddings,
    )

    def worker() -> None:
        try:
            if embeddings is not None:
                apply_configuration_embeddings(
                    config,
                    pipeline,
                    name,
                    embeddings,
                    config_path=config_path,
                )
                store._append_log(job, f"Настройки эмбеддингов сохранены для «{name}»")
            run_embed_job(store, job, pipeline, name)
        except Exception as exc:
            if job.status not in (JobStatus.COMPLETED, JobStatus.FAILED):
                job.status = JobStatus.FAILED
                job.error = str(exc)
                store._append_log(job, f"Ошибка: {exc}")
                logger.exception("Slot embed job %s failed", job.id)

    threading.Thread(target=worker, daemon=True).start()
    return job


def start_slot_index(
    store: JobStore,
    pipeline: Pipeline,
    config: AppConfig,
    configuration_name: str,
    *,
    skip_embeddings: bool = False,
    force: bool = False,
    embeddings: EmbeddingsSettingsUpdate | None = None,
    config_path: Path | None = None,
) -> Job:
    name = validate_slot_name(configuration_name)
    if not slot_has_export(config, name):
        msg = f"В слоте «{name}» нет выгрузки (Configuration.xml)"
        raise UploadError(msg)
    export_root = slot_export_root(config, name)
    detected = detect_export_configuration(export_root)
    validate_expected_configuration(detected, name)
    canonical_source = str(export_root.resolve())
    job = store.create(
        JobType.INDEX,
        source=canonical_source,
        configuration_name=name,
        skip_embeddings=skip_embeddings,
        force=force,
        expected_configuration=name,
        embeddings=embeddings,
    )
    store._append_log(
        job,
        f"Индексация «{name}»: {export_root}"
        + (f" ({detected.synonym})" if detected.synonym else ""),
    )

    def worker() -> None:
        try:
            if job.embeddings is not None and not job.skip_embeddings:
                apply_configuration_embeddings(
                    config,
                    pipeline,
                    name,
                    job.embeddings,
                    config_path=config_path,
                )
                store._append_log(job, f"Настройки эмбеддингов сохранены для «{name}»")
            run_index_job(store, job, pipeline, export_root)
        except Exception as exc:
            if job.status not in (JobStatus.COMPLETED, JobStatus.FAILED):
                job.status = JobStatus.FAILED
                job.error = str(exc)
                store._append_log(job, f"Ошибка: {exc}")
                logger.exception("Slot index job %s failed", job.id)

    threading.Thread(target=worker, daemon=True).start()
    return job


def import_zip_to_configuration_slot(
    config: AppConfig,
    configuration_name: str,
    zip_path: Path,
) -> Path:
    return import_zip_to_slot(config, configuration_name, zip_path)


def import_path_to_configuration_slot(
    config: AppConfig,
    configuration_name: str,
    source_path: Path,
    *,
    mirror: bool = False,
) -> Path:
    return import_path_to_slot(
        config,
        configuration_name,
        source_path,
        allowed_roots=config.resolved_import_roots(),
        mirror=mirror,
    )


def register_export_slot(config: AppConfig, configuration_name: str) -> Path:
    return ensure_export_slot(config, configuration_name)


def start_path_index(
    store: JobStore,
    pipeline: Pipeline,
    config: AppConfig,
    source: Path,
    *,
    skip_embeddings: bool = False,
    force: bool = False,
    expected_configuration: str | None = None,
) -> Job:
    roots = config.resolved_import_roots()
    export_root = validate_source_path(source, roots)
    detected = detect_export_configuration(export_root)
    validate_expected_configuration(detected, expected_configuration)
    job = store.create(
        JobType.PATH,
        source=str(source),
        configuration_name=expected_configuration or detected.name,
        skip_embeddings=skip_embeddings,
        force=force,
        expected_configuration=expected_configuration,
    )
    store._append_log(
        job,
        f"Путь принят: {export_root} → {detected.name}"
        + (f" ({detected.synonym})" if detected.synonym else ""),
    )

    def worker() -> None:
        run_index_job(store, job, pipeline, export_root)

    threading.Thread(target=worker, daemon=True).start()
    return job


def start_zip_index(
    store: JobStore,
    pipeline: Pipeline,
    config: AppConfig,
    zip_path: Path,
    *,
    skip_embeddings: bool = False,
    force: bool = False,
    expected_configuration: str | None = None,
    embeddings: EmbeddingsSettingsUpdate | None = None,
    config_path: Path | None = None,
) -> Job:
    job = store.create(
        JobType.ZIP,
        source=zip_path.name,
        skip_embeddings=skip_embeddings,
        force=force,
        expected_configuration=expected_configuration,
        embeddings=embeddings,
    )

    def worker() -> None:
        try:
            job.status = JobStatus.EXTRACTING
            store._append_log(job, "Распаковка ZIP...")
            with tempfile.TemporaryDirectory(prefix="conf_doc_zip_") as tmp:
                export_root = safe_extract_zip(zip_path, Path(tmp))
                detected = detect_export_configuration(export_root)
                validate_expected_configuration(detected, job.expected_configuration)
                name = job.expected_configuration or detected.name
                job.configuration_name = name
                store._append_log(
                    job,
                    f"Конфигурация в архиве: {detected.name}"
                    + (f" ({detected.synonym})" if detected.synonym else ""),
                )
                slot_root = import_zip_to_slot(config, name, zip_path)
                store._append_log(job, f"Импортировано в слот: {slot_root}")
            if job.embeddings is not None and not job.skip_embeddings:
                apply_configuration_embeddings(
                    config,
                    pipeline,
                    name,
                    job.embeddings,
                    config_path=config_path,
                )
                store._append_log(job, f"Настройки эмбеддингов сохранены для «{name}»")
            run_index_job(store, job, pipeline, slot_root)
        except (UploadError, OSError, zipfile.BadZipFile, ValueError) as exc:
            job.status = JobStatus.FAILED
            job.error = str(exc)
            store._append_log(job, f"Ошибка: {exc}")
            logger.exception("ZIP job %s failed", job.id)
        except Exception as exc:
            job.status = JobStatus.FAILED
            job.error = str(exc)
            store._append_log(job, f"Ошибка: {exc}\n{traceback.format_exc()}")
            logger.exception("ZIP job %s failed", job.id)
        finally:
            zip_path.unlink(missing_ok=True)

    threading.Thread(target=worker, daemon=True).start()
    return job


def start_reindex_job(
    store: JobStore,
    pipeline: Pipeline,
    export_root: Path,
    *,
    skip_embeddings: bool = False,
    force: bool = False,
    expected_configuration: str | None = None,
) -> Job:
    detected = detect_export_configuration(export_root)
    validate_expected_configuration(detected, expected_configuration)
    job = store.create(
        JobType.REINDEX,
        source=str(export_root),
        configuration_name=expected_configuration or detected.name,
        skip_embeddings=skip_embeddings,
        force=force,
        expected_configuration=expected_configuration,
    )
    store._append_log(
        job,
        f"Переиндексация: {export_root} → {detected.name}"
        + (f" ({detected.synonym})" if detected.synonym else ""),
    )

    def worker() -> None:
        run_index_job(store, job, pipeline, export_root)

    threading.Thread(target=worker, daemon=True).start()
    return job


def run_delete_job(
    store: JobStore,
    job: Job,
    pipeline: Pipeline,
    name: str,
    *,
    remove_files: bool = True,
) -> None:
    def progress_callback(message: str) -> None:
        store._append_log(job, message)

    try:
        job.status = JobStatus.DELETING
        job.configuration_name = name
        result = pipeline.delete_configuration(
            name,
            remove_files=remove_files,
            progress_callback=progress_callback,
        )
        job.stats = _delete_result_to_dict(result)
        job.status = JobStatus.COMPLETED
        if result.objects_count:
            store._append_log(
                job,
                f"Готово: «{result.name}» удалена ({result.objects_count} объектов)",
            )
        else:
            store._append_log(job, f"Готово: слот «{result.name}» удалён")
    except Exception as exc:
        job.status = JobStatus.FAILED
        job.error = str(exc)
        store._append_log(job, f"Ошибка: {exc}")
        logger.exception("Delete job %s failed", job.id)


def start_slot_import_zip(
    store: JobStore,
    config: AppConfig,
    configuration_name: str,
    zip_path: Path,
) -> Job:
    name = validate_slot_name(configuration_name)
    ensure_export_slot(config, name)
    job = store.create(
        JobType.IMPORT_ZIP,
        source=zip_path.name,
        configuration_name=name,
    )
    store._append_log(job, f"Импорт ZIP в слот «{name}»…")

    def worker() -> None:
        try:
            job.status = JobStatus.EXTRACTING
            store._append_log(job, "Распаковка архива…")
            export_root = import_zip_to_configuration_slot(config, name, zip_path)
            detected = detect_export_configuration(export_root)
            validate_expected_configuration(detected, name)
            job.configuration_name = name
            job.status = JobStatus.COMPLETED
            store._append_log(
                job,
                f"Готово: «{name}» импортирован"
                + (f" ({detected.synonym})" if detected.synonym else ""),
            )
        except (UploadError, OSError, zipfile.BadZipFile, ValueError) as exc:
            job.status = JobStatus.FAILED
            job.error = str(exc)
            store._append_log(job, f"Ошибка: {exc}")
            logger.exception("Import ZIP job %s failed", job.id)
        except Exception as exc:
            job.status = JobStatus.FAILED
            job.error = str(exc)
            store._append_log(job, f"Ошибка: {exc}\n{traceback.format_exc()}")
            logger.exception("Import ZIP job %s failed", job.id)
        finally:
            zip_path.unlink(missing_ok=True)

    threading.Thread(target=worker, daemon=True).start()
    return job


def start_slot_import_path(
    store: JobStore,
    config: AppConfig,
    configuration_name: str,
    source_path: Path,
    *,
    mirror: bool = False,
) -> Job:
    name = validate_slot_name(configuration_name)
    ensure_export_slot(config, name)
    job = store.create(
        JobType.IMPORT_PATH,
        source=str(source_path),
        configuration_name=name,
    )
    mode = "копирование в слот" if mirror else "привязка пути"
    store._append_log(job, f"Импорт «{name}»: {mode}…")

    def worker() -> None:
        try:
            job.status = JobStatus.EXTRACTING
            if mirror:
                store._append_log(job, "Копирование файлов — может занять много времени…")
            export_root = import_path_to_configuration_slot(
                config,
                name,
                source_path,
                mirror=mirror,
            )
            detected = detect_export_configuration(export_root)
            validate_expected_configuration(detected, name)
            job.configuration_name = name
            job.status = JobStatus.COMPLETED
            store._append_log(
                job,
                f"Готово: «{name}» — {mode}"
                + (f" ({detected.synonym})" if detected.synonym else ""),
            )
        except (UploadError, OSError, ValueError) as exc:
            job.status = JobStatus.FAILED
            job.error = str(exc)
            store._append_log(job, f"Ошибка: {exc}")
            logger.exception("Import path job %s failed", job.id)
        except Exception as exc:
            job.status = JobStatus.FAILED
            job.error = str(exc)
            store._append_log(job, f"Ошибка: {exc}")
            logger.exception("Import path job %s failed", job.id)

    threading.Thread(target=worker, daemon=True).start()
    return job


def start_delete_job(
    store: JobStore,
    pipeline: Pipeline,
    name: str,
    *,
    remove_files: bool = True,
) -> Job:
    job = store.create(JobType.DELETE, source=name, configuration_name=name)
    store._append_log(job, f"Запуск удаления: {name}")

    def worker() -> None:
        run_delete_job(store, job, pipeline, name, remove_files=remove_files)

    threading.Thread(target=worker, daemon=True).start()
    return job
