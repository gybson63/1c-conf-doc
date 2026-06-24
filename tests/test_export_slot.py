"""Tests for per-configuration export slots and slot-based API."""

from __future__ import annotations

import io
import shutil
import time
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from onec_conf_doc.api.app import create_app
from onec_conf_doc.config import AppConfig
from onec_conf_doc.export_migrate import migrate_configuration_exports
from onec_conf_doc.export_slot import (
    ExportSlotError,
    ensure_export_slot,
    import_path_to_slot,
    migrate_export_to_slot,
    needs_export_migration,
    slot_export_linked,
    slot_export_root,
    slot_has_export,
    validate_slot_name,
)
from onec_conf_doc.rag.pipeline import Pipeline

FIXTURES = Path(__file__).parent / "fixtures" / "export_minimal"
CONFIG_NAME = "ТестоваяКонфигурация"


def _make_zip_from_dir(src: Path) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in src.rglob("*"):
            if path.is_file():
                zf.write(path, path.relative_to(src).as_posix())
    return buf.getvalue()


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


def test_validate_slot_name() -> None:
    assert validate_slot_name("Бухгалтерия") == "Бухгалтерия"
    with pytest.raises(ExportSlotError):
        validate_slot_name("")
    with pytest.raises(ExportSlotError):
        validate_slot_name("bad/name")


def test_import_path_link_mode(tmp_path: Path) -> None:
    cfg = AppConfig(source=FIXTURES, output=tmp_path / "output")
    roots = [FIXTURES.parent.resolve()]
    import_path_to_slot(cfg, CONFIG_NAME, FIXTURES, allowed_roots=roots)
    slot = ensure_export_slot(cfg, CONFIG_NAME)
    assert slot_has_export(cfg, CONFIG_NAME)
    assert slot_export_linked(cfg, CONFIG_NAME)
    assert (slot / ".import_source").is_file()
    assert slot_export_root(cfg, CONFIG_NAME).resolve() == FIXTURES.resolve()
    # повторная привязка
    import_path_to_slot(cfg, CONFIG_NAME, FIXTURES, allowed_roots=roots)
    assert slot_has_export(cfg, CONFIG_NAME)


def test_import_path_mirror_mode(tmp_path: Path) -> None:
    cfg = AppConfig(source=FIXTURES, output=tmp_path / "output")
    roots = [FIXTURES.parent.resolve()]
    import_path_to_slot(cfg, CONFIG_NAME, FIXTURES, allowed_roots=roots, mirror=True)
    slot = ensure_export_slot(cfg, CONFIG_NAME)
    assert slot_has_export(cfg, CONFIG_NAME)
    assert not slot_export_linked(cfg, CONFIG_NAME)
    assert (slot / "Configuration.xml").is_file() or any(
        (p / "Configuration.xml").is_file() for p in slot.iterdir() if p.is_dir()
    )


def test_import_mismatch_returns_400(tmp_path: Path) -> None:
    cfg = AppConfig(source=FIXTURES, output=tmp_path / "output", import_roots=[FIXTURES.parent])
    app = create_app(cfg)
    client = TestClient(app)

    client.post("/configurations", json={"name": "WrongName"})
    resp = client.post(
        "/configurations/WrongName/import-path",
        json={"source": str(FIXTURES)},
    )
    assert resp.status_code == 400


def test_slot_index_flow(tmp_path: Path) -> None:
    cfg = AppConfig(source=FIXTURES, output=tmp_path / "output", import_roots=[FIXTURES.parent])
    app = create_app(cfg)
    client = TestClient(app)

    reg = client.post("/configurations", json={"name": CONFIG_NAME})
    assert reg.status_code == 201

    imp = client.post(
        f"/configurations/{CONFIG_NAME}/import-path",
        json={"source": str(FIXTURES)},
    )
    assert imp.status_code == 200
    assert imp.json()["detected_name"] == CONFIG_NAME

    det = client.post(f"/configurations/{CONFIG_NAME}/detect")
    assert det.status_code == 200
    assert det.json()["matches_expected"] is True

    idx = client.post(
        f"/configurations/{CONFIG_NAME}/index",
        json={"skip_embeddings": True},
    )
    assert idx.status_code == 202
    job = _wait_job(client, idx.json()["job_id"])
    assert job["status"] == "completed"
    assert job["configuration_name"] == CONFIG_NAME
    assert job["source"] == str(FIXTURES.resolve())

    card = client.get(f"/configurations/{CONFIG_NAME}").json()
    assert card["has_export"] is True
    assert card["export_linked"] is True
    assert card["in_database"] is True


def test_embed_only_after_index(tmp_path: Path) -> None:
    cfg = AppConfig(source=FIXTURES, output=tmp_path / "output", import_roots=[FIXTURES.parent])
    app = create_app(cfg)
    client = TestClient(app)

    client.post("/configurations", json={"name": CONFIG_NAME})
    client.post(
        f"/configurations/{CONFIG_NAME}/import-path",
        json={"source": str(FIXTURES)},
    )
    idx = client.post(
        f"/configurations/{CONFIG_NAME}/index",
        json={"skip_embeddings": True},
    )
    _wait_job(client, idx.json()["job_id"])

    emb = client.post(
        f"/configurations/{CONFIG_NAME}/embed",
        json={"force": False},
    )
    assert emb.status_code == 202
    job = _wait_job(client, emb.json()["job_id"], timeout=180.0)
    assert job["status"] == "completed"
    assert job["type"] == "embed"
    assert (cfg.vectors_dir_for(CONFIG_NAME) / "index.faiss").is_file()


def test_delete_removes_export_slot(tmp_path: Path) -> None:
    cfg = AppConfig(source=FIXTURES, output=tmp_path / "output", import_roots=[FIXTURES.parent])
    pipeline = Pipeline(cfg)
    app = create_app(cfg)
    client = TestClient(app)

    import_path_to_slot(cfg, CONFIG_NAME, FIXTURES, allowed_roots=[FIXTURES.parent])
    idx = client.post(
        f"/configurations/{CONFIG_NAME}/index",
        json={"skip_embeddings": True},
    )
    _wait_job(client, idx.json()["job_id"])

    export_dir = cfg.export_dir_for(CONFIG_NAME)
    assert export_dir.is_dir()

    result = pipeline.delete_configuration(CONFIG_NAME, remove_files=True)
    assert result.export_removed is True
    assert not export_dir.exists()


def test_migrate_upload_path_to_slot(tmp_path: Path) -> None:
    cfg = AppConfig(
        source=FIXTURES,
        output=tmp_path / "output",
        import_roots=[FIXTURES.parent, tmp_path],
    )
    pipeline = Pipeline(cfg)
    app = create_app(cfg)
    client = TestClient(app)

    legacy = tmp_path / "output" / "exports" / "_upload_abc123"
    shutil.copytree(FIXTURES, legacy)

    idx = client.post(
        "/configurations/index",
        json={"source": str(legacy), "skip_embeddings": True},
    )
    _wait_job(client, idx.json()["job_id"])

    row = pipeline.indexer.resolve_configuration(CONFIG_NAME)
    assert row is not None
    canonical = cfg.export_dir_for(CONFIG_NAME)
    assert needs_export_migration(row.export_path, canonical)

    results = migrate_configuration_exports(cfg, pipeline)
    migrated = [r for r in results if r.name == CONFIG_NAME]
    assert migrated
    assert migrated[0].migrated is True
    assert slot_has_export(cfg, CONFIG_NAME)

    row2 = pipeline.indexer.resolve_configuration(CONFIG_NAME)
    assert row2 is not None
    assert Path(row2.export_path).resolve() == canonical.resolve()


def test_migrate_export_to_slot_copies_legacy(tmp_path: Path) -> None:
    cfg = AppConfig(source=FIXTURES, output=tmp_path / "output")
    legacy = tmp_path / "legacy_export"
    shutil.copytree(FIXTURES, legacy)
    new_path = migrate_export_to_slot(cfg, CONFIG_NAME, str(legacy))
    assert new_path is not None
    assert slot_has_export(cfg, CONFIG_NAME)


def test_delete_export_slot_only(tmp_path: Path) -> None:
    cfg = AppConfig(source=FIXTURES, output=tmp_path / "output")
    pipeline = Pipeline(cfg)
    client = TestClient(create_app(cfg))

    slot = cfg.export_dir_for("BrokenSlot")
    slot.mkdir(parents=True)
    (slot / "orphan.txt").write_text("x", encoding="utf-8")

    result = pipeline.delete_configuration("BrokenSlot", remove_files=True)
    assert result.objects_count == 0
    assert result.export_removed is True
    assert not slot.exists()

    left = cfg.export_dir_for("LeftoverSlot")
    left.mkdir(parents=True)
    (left / "a.txt").write_text("1", encoding="utf-8")
    sync = client.delete("/configurations/LeftoverSlot")
    assert sync.status_code == 200
    assert not left.exists()
