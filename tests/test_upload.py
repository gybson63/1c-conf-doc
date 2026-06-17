"""Tests for configuration upload and path indexing API."""

from __future__ import annotations

import io
import time
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from onec_conf_doc.api.app import create_app
from onec_conf_doc.api.upload import UploadError, safe_extract_zip, validate_source_path
from onec_conf_doc.config import AppConfig

FIXTURES = Path(__file__).parent / "fixtures" / "export_minimal"


def _wait_job(client: TestClient, job_id: str, timeout: float = 30.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        resp = client.get(f"/configurations/jobs/{job_id}")
        assert resp.status_code == 200
        body = resp.json()
        if body["status"] in ("completed", "failed"):
            return body
        time.sleep(0.25)
    msg = f"Job {job_id} did not finish in {timeout}s"
    raise TimeoutError(msg)


def _make_zip_from_dir(src: Path) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in src.rglob("*"):
            if path.is_file():
                zf.write(path, path.relative_to(src).as_posix())
    return buf.getvalue()


def test_validate_source_path_and_zip_slip(tmp_path: Path) -> None:
    roots = [FIXTURES.parent.resolve()]
    export_root = validate_source_path(FIXTURES, roots)
    assert (export_root / "Configuration.xml").is_file()

    with pytest.raises(UploadError, match="outside"):
        validate_source_path(Path("/nonexistent/outside"), roots)

    zip_path = tmp_path / "evil.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("../escape.txt", "bad")
    dest = tmp_path / "dest"
    with pytest.raises(UploadError, match="Unsafe"):
        safe_extract_zip(zip_path, dest)


def test_index_from_path_job(tmp_path: Path) -> None:
    cfg = AppConfig(source=FIXTURES, output=tmp_path / "output")
    app = create_app(cfg)
    client = TestClient(app)

    resp = client.post(
        "/configurations/index",
        json={"source": str(FIXTURES), "skip_embeddings": True},
    )
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]

    job = _wait_job(client, job_id)
    assert job["status"] == "completed"
    assert job["configuration_name"] == "ТестоваяКонфигурация"
    assert job["logs"]
    assert job["stats"]["objects_total"] == 6

    configs = client.get("/configurations").json()
    assert any(c["name"] == "ТестоваяКонфигурация" for c in configs)


def test_index_path_outside_roots(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    cfg = AppConfig(source=FIXTURES, output=tmp_path / "output", import_roots=[allowed])
    app = create_app(cfg)
    client = TestClient(app)

    resp = client.post(
        "/configurations/index",
        json={"source": str(FIXTURES), "skip_embeddings": True},
    )
    assert resp.status_code == 400


def test_upload_zip_job(tmp_path: Path) -> None:
    cfg = AppConfig(source=FIXTURES, output=tmp_path / "output")
    app = create_app(cfg)
    client = TestClient(app)

    zip_bytes = _make_zip_from_dir(FIXTURES)
    resp = client.post(
        "/configurations/upload",
        params={"skip_embeddings": "true"},
        files={"file": ("export.zip", zip_bytes, "application/zip")},
    )
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]

    job = _wait_job(client, job_id, timeout=60)
    assert job["status"] == "completed"
    assert job["configuration_name"] == "ТестоваяКонфигурация"
