from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from onec_conf_doc.api.app import create_app
from onec_conf_doc.config import AppConfig, load_config, save_config
from onec_conf_doc.export_detect import (
    configuration_matches_expected,
    detect_export_configuration,
    validate_expected_configuration,
)

FIXTURES = Path(__file__).parent / "fixtures" / "export_minimal"


def test_detect_export_configuration(tmp_path) -> None:
    info = detect_export_configuration(FIXTURES)
    assert info.name == "ТестоваяКонфигурация"
    assert info.export_path == str(FIXTURES.resolve())


def test_validate_expected_configuration_match() -> None:
    from onec_conf_doc.models.metadata import ConfigurationInfo

    info = ConfigurationInfo(name="ТестоваяКонфигурация", synonym="Тест")
    validate_expected_configuration(info, "ТестоваяКонфигурация")
    assert configuration_matches_expected(info.name, "ТестоваяКонфигурация")


def test_validate_expected_configuration_mismatch() -> None:
    from onec_conf_doc.models.metadata import ConfigurationInfo

    info = ConfigurationInfo(name="Бухгалтерия", synonym="")
    with pytest.raises(ValueError, match="ожидалась"):
        validate_expected_configuration(info, "Зарплата")


def test_detect_api_endpoint(tmp_path) -> None:
    cfg = AppConfig(source=FIXTURES, output=tmp_path / "output")
    client = TestClient(create_app(cfg))

    ok = client.post(
        "/configurations/detect",
        json={"source": str(FIXTURES), "expected_configuration": "ТестоваяКонфигурация"},
    )
    assert ok.status_code == 200
    body = ok.json()
    assert body["matches_expected"] is True
    assert body["name"] == "ТестоваяКонфигурация"

    auto = client.post("/configurations/detect", json={"source": str(FIXTURES)})
    assert auto.status_code == 200
    assert auto.json()["name"] == "ТестоваяКонфигурация"

    bad = client.post(
        "/configurations/detect",
        json={"source": str(FIXTURES), "expected_configuration": "ДругаяКонфигурация"},
    )
    assert bad.status_code == 200
    assert bad.json()["matches_expected"] is False
    assert "embeddings" in ok.json()


def test_index_saves_embeddings_for_configuration(tmp_path) -> None:
    config_path = tmp_path / "config.yaml"
    cfg = AppConfig(source=FIXTURES, output=tmp_path / "output", import_roots=[FIXTURES.parent])
    save_config(cfg, config_path)
    client = TestClient(create_app(cfg, config_path=config_path))

    with patch("onec_conf_doc.api.jobs.threading.Thread") as thread_mock:
        thread_mock.return_value.start = lambda: None
        response = client.post(
            "/configurations/index",
            json={
                "source": str(FIXTURES),
                "expected_configuration": "ТестоваяКонфигурация",
                "skip_embeddings": False,
                "embeddings": {
                    "provider": "openai",
                    "model": "text-embedding-3-small",
                    "openai_api_key": "key",
                },
            },
        )
    assert response.status_code == 202
    reloaded = load_config(config_path)
    assert reloaded.configuration_embeddings["ТестоваяКонфигурация"].provider == "openai"


def test_index_rejects_configuration_mismatch(tmp_path) -> None:
    cfg = AppConfig(source=FIXTURES, output=tmp_path / "output", import_roots=[FIXTURES.parent])
    client = TestClient(create_app(cfg))

    response = client.post(
        "/configurations/index",
        json={"source": str(FIXTURES), "expected_configuration": "ДругаяКонфигурация"},
    )
    assert response.status_code == 400
    assert "ожидалась" in response.json()["detail"]
