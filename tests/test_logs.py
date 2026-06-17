"""Tests for in-memory log buffer API."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from fastapi.testclient import TestClient

from onec_conf_doc.api.app import create_app
from onec_conf_doc.api.logging_buffer import setup_logging
from onec_conf_doc.config import AppConfig

FIXTURES = Path(__file__).parent / "fixtures" / "export_minimal"


def test_logs_endpoint(tmp_path) -> None:
    setup_logging()
    logger = logging.getLogger("onec_conf_doc.test")
    logger.info("test message one")

    cfg = AppConfig(source=FIXTURES, output=tmp_path / "output")
    app = create_app(cfg)
    client = TestClient(app)

    resp = client.get("/logs?tail=10")
    assert resp.status_code == 200
    body = resp.json()
    assert "records" in body
    assert body["last_id"] >= 1
    messages = [r["message"] for r in body["records"]]
    assert any("test message" in m for m in messages)

    last_id = body["last_id"]
    logger.info("test message two")
    since = client.get(f"/logs?since_id={last_id}")
    assert since.status_code == 200
    new_records = since.json()["records"]
    assert all(r["id"] > last_id for r in new_records)
    assert any("two" in r["message"] for r in new_records)


def test_job_logs(tmp_path) -> None:
    cfg = AppConfig(source=FIXTURES, output=tmp_path / "output")
    app = create_app(cfg)
    client = TestClient(app)

    resp = client.post(
        "/configurations/index",
        json={"source": str(FIXTURES), "skip_embeddings": True},
    )
    job_id = resp.json()["job_id"]

    deadline = time.monotonic() + 30
    job_body = None
    while time.monotonic() < deadline:
        job_resp = client.get(f"/configurations/jobs/{job_id}")
        job_body = job_resp.json()
        if job_body["status"] in ("completed", "failed"):
            break
        time.sleep(0.25)

    assert job_body is not None
    assert job_body["status"] == "completed"
    assert isinstance(job_body["logs"], list)
    assert len(job_body["logs"]) >= 1

    jobs_list = client.get("/configurations/jobs")
    assert jobs_list.status_code == 200
    assert any(j["id"] == job_id for j in jobs_list.json())
