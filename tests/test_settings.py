from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from onec_conf_doc.api.app import create_app
from onec_conf_doc.config import AppConfig, load_config, save_config

FIXTURES = Path(__file__).parent / "fixtures" / "export_minimal"


def test_save_and_load_config_roundtrip(tmp_path) -> None:
    config_path = tmp_path / "config.yaml"
    cfg = AppConfig(
        source=tmp_path / "export",
        output=tmp_path / "output",
        embeddings={
            "provider": "openai",
            "model": "text-embedding-3-small",
            "base_url": "https://api.example.com/v1",
            "openai_api_key": "secret",
        },
    )
    save_config(cfg, config_path)
    loaded = load_config(config_path)
    assert loaded.embeddings.provider == "openai"
    assert loaded.embeddings.model == "text-embedding-3-small"
    assert loaded.embeddings.base_url == "https://api.example.com/v1"
    assert loaded.embeddings.openai_api_key == "secret"
    with config_path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    assert "openai_api_key" in raw["embeddings"]


def test_embeddings_settings_api(tmp_path) -> None:
    config_path = tmp_path / "config.yaml"
    cfg = AppConfig(source=FIXTURES, output=tmp_path / "output")
    save_config(cfg, config_path)
    app = create_app(cfg, config_path=config_path)
    client = TestClient(app)

    current = client.get("/settings/embeddings")
    assert current.status_code == 200
    body = current.json()
    assert body["provider"] == "sentence_transformers"
    assert body["has_openai_api_key"] is False
    assert "openai_api_key" not in body

    updated = client.put(
        "/settings/embeddings",
        json={
            "provider": "openai",
            "model": "text-embedding-3-small",
            "base_url": "https://api.openai.com/v1",
            "openai_api_key": "test-key",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["provider"] == "openai"
    assert updated.json()["has_openai_api_key"] is True

    reloaded = load_config(config_path)
    assert reloaded.embeddings.provider == "openai"
    assert reloaded.embeddings.openai_api_key == "test-key"

    keep_key = client.put(
        "/settings/embeddings",
        json={
            "provider": "openai",
            "model": "text-embedding-3-large",
            "base_url": "https://api.openai.com/v1",
        },
    )
    assert keep_key.status_code == 200
    assert load_config(config_path).embeddings.openai_api_key == "test-key"


def test_health_includes_embeddings(tmp_path) -> None:
    cfg = AppConfig(source=FIXTURES, output=tmp_path / "output")
    client = TestClient(create_app(cfg))
    health = client.get("/health").json()
    assert health["embeddings"]["provider"] == "sentence_transformers"
    assert "model" in health["embeddings"]


def test_configurations_embedding_status(tmp_path) -> None:
    cfg = AppConfig(source=FIXTURES, output=tmp_path / "output")
    client = TestClient(create_app(cfg))
    client.post("/reindex", json={"skip_embeddings": True})

    configs = client.get("/configurations").json()
    assert len(configs) == 1
    assert configs[0]["embedding_status"] == "missing"
    assert configs[0]["embedding_model"] is None


def test_embeddings_connection_test_success(tmp_path, monkeypatch) -> None:
    class FakeProvider:
        dimension = 1536

        def embed_query(self, text: str) -> list[float]:
            assert text == "connection test"
            return [0.1] * self.dimension

    def fake_factory(_config):
        return FakeProvider()

    monkeypatch.setattr(
        "onec_conf_doc.api.routes.create_embedding_provider",
        fake_factory,
    )
    cfg = AppConfig(source=FIXTURES, output=tmp_path / "output")
    client = TestClient(create_app(cfg))

    response = client.post(
        "/settings/embeddings/test",
        json={
            "provider": "openai",
            "model": "text-embedding-3-small",
            "base_url": "https://api.openai.com/v1",
            "openai_api_key": "test-key",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["provider"] == "openai"
    assert body["model"] == "text-embedding-3-small"
    assert body["dimension"] == 1536


def test_embeddings_connection_test_failure(tmp_path, monkeypatch) -> None:
    def fake_factory(_config):
        msg = "Invalid API key"
        raise ValueError(msg)

    monkeypatch.setattr(
        "onec_conf_doc.api.routes.create_embedding_provider",
        fake_factory,
    )
    cfg = AppConfig(source=FIXTURES, output=tmp_path / "output")
    client = TestClient(create_app(cfg))

    response = client.post(
        "/settings/embeddings/test",
        json={
            "provider": "openai",
            "model": "text-embedding-3-small",
            "openai_api_key": "bad",
        },
    )
    assert response.status_code == 400
    assert "Invalid API key" in response.json()["detail"]


def test_embeddings_settings_per_configuration(tmp_path, monkeypatch) -> None:
    class FakeProvider:
        dimension = 384

        def embed_query(self, text: str) -> list[float]:
            return [0.0] * self.dimension

    monkeypatch.setattr(
        "onec_conf_doc.api.routes.create_embedding_provider",
        lambda _config: FakeProvider(),
    )
    config_path = tmp_path / "config.yaml"
    cfg = AppConfig(source=FIXTURES, output=tmp_path / "output")
    save_config(cfg, config_path)
    client = TestClient(create_app(cfg, config_path=config_path))

    updated = client.put(
        "/settings/embeddings?configuration=ТестоваяКонфигурация",
        json={
            "provider": "openai",
            "model": "text-embedding-3-small",
            "openai_api_key": "key",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["uses_default"] is False

    reloaded = load_config(config_path)
    assert "ТестоваяКонфигурация" in reloaded.configuration_embeddings
    assert reloaded.embeddings_for("ТестоваяКонфигурация").provider == "openai"
    assert reloaded.embeddings.provider == "sentence_transformers"


def test_embeddings_connection_test_uses_saved_api_key(tmp_path, monkeypatch) -> None:
    seen_keys: list[str | None] = []

    class FakeProvider:
        dimension = 384

        def embed_query(self, text: str) -> list[float]:
            return [0.0] * self.dimension

    def fake_factory(config):
        seen_keys.append(config.openai_api_key)
        return FakeProvider()

    monkeypatch.setattr(
        "onec_conf_doc.api.routes.create_embedding_provider",
        fake_factory,
    )
    config_path = tmp_path / "config.yaml"
    cfg = AppConfig(
        source=FIXTURES,
        output=tmp_path / "output",
        embeddings={
            "provider": "openai",
            "model": "text-embedding-3-small",
            "openai_api_key": "saved-key",
        },
    )
    save_config(cfg, config_path)
    client = TestClient(create_app(cfg, config_path=config_path))

    response = client.post(
        "/settings/embeddings/test",
        json={
            "provider": "openai",
            "model": "text-embedding-3-small",
        },
    )
    assert response.status_code == 200
    assert seen_keys == ["saved-key"]
