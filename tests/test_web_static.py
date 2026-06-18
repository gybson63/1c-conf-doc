"""Tests for web UI static file serving."""

from pathlib import Path

from fastapi.testclient import TestClient

from onec_conf_doc.api.app import create_app
from onec_conf_doc.config import AppConfig

FIXTURES = Path(__file__).parent / "fixtures" / "export_minimal"


def test_static_and_index_page(tmp_path) -> None:
    cfg = AppConfig(source=FIXTURES, output=tmp_path / "output")
    app = create_app(cfg)
    client = TestClient(app)

    index = client.get("/")
    assert index.status_code == 200
    assert "text/html" in index.headers.get("content-type", "")
    assert "1c-conf-doc" in index.text

    js = client.get("/static/app.js")
    assert js.status_code == 200
    assert "loadHealth" in js.text
    assert "refreshPendingConfigOps" in js.text

    css = client.get("/static/styles.css")
    assert css.status_code == 200


def test_object_page_route(tmp_path) -> None:
    cfg = AppConfig(source=FIXTURES, output=tmp_path / "output")
    app = create_app(cfg)
    client = TestClient(app)

    page = client.get("/object/Report/Test")
    assert page.status_code == 200
    assert "text/html" in page.headers.get("content-type", "")
    assert "1c-conf-doc" in page.text
