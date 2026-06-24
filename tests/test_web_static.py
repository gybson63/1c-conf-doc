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
    assert "loadConfigurationPage" in js.text
    assert "parseConfigurationRoute" in js.text
    assert "navigateToConfiguration" in js.text
    assert "startConfigurationUpdate" in js.text
    assert "startConfigurationReindex" in js.text
    assert "resumeActiveJobs" in js.text
    assert "wizardDetectFromSourcePath" in js.text
    assert "setButtonLoading" in js.text
    assert "withButtonLoading" in js.text
    assert "panel-configuration" in index.text
    assert "btn-config-manage" in js.text
    assert "btn-new-configuration" in index.text
    assert "configs-filter" in index.text
    assert "configs-help" in index.text
    assert "Обновить из файлов" in index.text
    assert "Пропустить семантический поиск" in index.text
    assert "Полное обновление семантического поиска (force)" in index.text
    assert "для всех файлов, а не только изменённых" in index.text
    assert "updateSkipEmbeddingsHint" in js.text
    assert "только текстовая информация" in js.text
    assert "panel-add" not in index.text
    assert "wizard-overlay" not in index.text

    css = client.get("/static/styles.css")
    assert css.status_code == 200
    assert "configuration-status-grid" in css.text
    assert "btn-spin" in css.text
    assert ".btn.is-loading" in css.text
    assert "option-hint" in css.text


def test_object_page_route(tmp_path) -> None:
    cfg = AppConfig(source=FIXTURES, output=tmp_path / "output")
    app = create_app(cfg)
    client = TestClient(app)

    page = client.get("/object/Report/Test")
    assert page.status_code == 200
    assert "text/html" in page.headers.get("content-type", "")
    assert "1c-conf-doc" in page.text


def test_configuration_page_route(tmp_path) -> None:
    cfg = AppConfig(source=FIXTURES, output=tmp_path / "output")
    app = create_app(cfg)
    client = TestClient(app)

    page = client.get("/configuration/ТестоваяКонфигурация")
    assert page.status_code == 200
    assert "text/html" in page.headers.get("content-type", "")
    assert "1c-conf-doc" in page.text
    assert "panel-configuration" in page.text

    new_page = client.get("/configuration/new")
    assert new_page.status_code == 200
    assert "panel-configuration" in new_page.text
