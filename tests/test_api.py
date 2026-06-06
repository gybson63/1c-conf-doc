from pathlib import Path

from fastapi.testclient import TestClient

from onec_conf_doc.api.app import create_app
from onec_conf_doc.config import AppConfig

FIXTURES = Path(__file__).parent / "fixtures" / "export_minimal"


def test_api_health_and_objects(tmp_path) -> None:
    cfg = AppConfig(source=FIXTURES, output=tmp_path / "output")
    app = create_app(cfg)
    client = TestClient(app)

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    reindex = client.post("/reindex", json={"skip_embeddings": True})
    assert reindex.status_code == 200

    reindex_force = client.post("/reindex", json={"skip_embeddings": True, "force": True})
    assert reindex_force.status_code == 200
    assert reindex_force.json()["chunks_rebuilt"] == 3
    assert reindex.json()["configuration_name"] == "ТестоваяКонфигурация"
    assert reindex.json()["objects_total"] == 3

    objects = client.get(
        "/objects",
        params={"object_type": "Catalog", "configuration": "ТестоваяКонфигурация"},
    )
    assert objects.status_code == 200
    data = objects.json()
    assert len(data) == 1
    assert data[0]["name"] == "Номенклатура"

    detail = client.get(
        "/objects/Catalog/Номенклатура",
        params={"configuration": "ТестоваяКонфигурация"},
    )
    assert detail.status_code == 200
    body = detail.json()
    assert body["object"]["name"] == "Номенклатура"
    assert body["attributes_count"] >= 1
    assert len(body["chunks"]) >= 1

    chunk = client.get(
        "/objects/Catalog/Номенклатура/chunks/0",
        params={"configuration": "ТестоваяКонфигурация"},
    )
    assert chunk.status_code == 200
    assert "text" in chunk.json()
    assert chunk.json()["chunk_index"] == 0

    search = client.post(
        "/search",
        json={
            "query": "номенклатура",
            "configuration": "ТестоваяКонфигурация",
            "top_k": 3,
        },
    )
    assert search.status_code == 200
    assert len(search.json()) >= 1
