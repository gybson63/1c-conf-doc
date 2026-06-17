"""Background indexing jobs with in-memory store."""

from __future__ import annotations

import logging
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

from onec_conf_doc.api.upload import UploadError, safe_extract_zip, validate_source_path
from onec_conf_doc.config import AppConfig
from onec_conf_doc.rag.pipeline import IndexStats, Pipeline

logger = logging.getLogger("onec_conf_doc.jobs")

MAX_JOBS = 100


class JobStatus(StrEnum):
    PENDING = "pending"
    EXTRACTING = "extracting"
    INDEXING = "indexing"
    COMPLETED = "completed"
    FAILED = "failed"


class JobType(StrEnum):
    PATH = "path"
    ZIP = "zip"
    REINDEX = "reindex"


@dataclass
class Job:
    id: str
    type: JobType
    status: JobStatus
    source: str = ""
    created_at: str = ""
    configuration_name: str | None = None
    skip_embeddings: bool = False
    force: bool = False
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

    def to_detail(self) -> dict[str, Any]:
        result = self.to_summary()
        result["logs"] = list(self.logs)
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
        skip_embeddings: bool = False,
        force: bool = False,
    ) -> Job:
        job_id = str(uuid.uuid4())
        job = Job(
            id=job_id,
            type=job_type,
            status=JobStatus.PENDING,
            source=source,
            created_at=datetime.now(tz=UTC).isoformat(),
            skip_embeddings=skip_embeddings,
            force=force,
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


def start_path_index(
    store: JobStore,
    pipeline: Pipeline,
    config: AppConfig,
    source: Path,
    *,
    skip_embeddings: bool = False,
    force: bool = False,
) -> Job:
    roots = config.resolved_import_roots()
    export_root = validate_source_path(source, roots)
    job = store.create(
        JobType.PATH,
        source=str(source),
        skip_embeddings=skip_embeddings,
        force=force,
    )
    store._append_log(job, f"Путь принят: {export_root}")

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
) -> Job:
    job = store.create(
        JobType.ZIP,
        source=zip_path.name,
        skip_embeddings=skip_embeddings,
        force=force,
    )

    def worker() -> None:
        try:
            job.status = JobStatus.EXTRACTING
            store._append_log(job, "Распаковка ZIP...")
            exports_dir = config.output / "exports"
            exports_dir.mkdir(parents=True, exist_ok=True)
            temp_dest = exports_dir / f"_upload_{job.id}"
            export_root = safe_extract_zip(zip_path, temp_dest)
            store._append_log(job, f"Распаковано в {export_root}")
            run_index_job(store, job, pipeline, export_root)
        except (UploadError, OSError, zipfile.BadZipFile) as exc:
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
) -> Job:
    job = store.create(
        JobType.REINDEX,
        source=str(export_root),
        skip_embeddings=skip_embeddings,
        force=force,
    )
    store._append_log(job, f"Переиндексация: {export_root}")

    def worker() -> None:
        run_index_job(store, job, pipeline, export_root)

    threading.Thread(target=worker, daemon=True).start()
    return job
