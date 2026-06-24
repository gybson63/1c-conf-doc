"""Tests for background job store and progress API."""

from __future__ import annotations

from onec_conf_doc.api.jobs import Job, JobStatus, JobStore, JobType


def test_job_progress_snapshot_objects() -> None:
    job = Job(id="test-id", type=JobType.INDEX, status=JobStatus.INDEXING)
    job.logs = ["[12:00:00] Обработано 50/100 объектов"]
    progress = job.progress_snapshot()
    assert progress is not None
    assert progress["phase"] == "objects"
    assert progress["current"] == 50
    assert progress["total"] == 100
    assert progress["percent"] == 50


def test_job_progress_snapshot_embeddings() -> None:
    job = Job(id="test-id", type=JobType.EMBED, status=JobStatus.INDEXING)
    job.logs = ["[12:01:00] Эмбеддинги: 10/40 чанков (батч 1)"]
    progress = job.progress_snapshot()
    assert progress is not None
    assert progress["phase"] == "embeddings"
    assert progress["current"] == 10
    assert progress["total"] == 40
    assert progress["percent"] == 25


def test_job_to_detail_since_log() -> None:
    job = Job(id="test-id", type=JobType.INDEX, status=JobStatus.COMPLETED)
    job.logs = ["line-1", "line-2", "line-3"]
    detail = job.to_detail(since_log=2)
    assert detail["logs"] == ["line-3"]
    assert detail["logs_offset"] == 2
    assert detail["logs_total"] == 3


def test_job_log_cap() -> None:
    store = JobStore()
    job = store.create(JobType.INDEX, source="test")
    for i in range(600):
        store._append_log(job, f"msg-{i}")
    assert len(job.logs) == 500
    assert job.logs[0].endswith("msg-100")
    assert job.logs[-1].endswith("msg-599")
