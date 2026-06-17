from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from tests.test_incremental_embed import MockEmbeddingProvider

from onec_conf_doc.api.app import create_app
from onec_conf_doc.config import AppConfig
from onec_conf_doc.rag.pipeline import Pipeline
from onec_conf_doc.rag.role_search import (
    parse_rights_hits_from_text,
    search_roles_by_object,
)

FIXTURES = Path(__file__).parent / "fixtures" / "export_minimal"
ROLE_MD_SNIPPET = """\
## Права: Catalog

| Объект | Права | RLS |
|--------|-------|-----|
| Номенклатура | Read, View |  |

## Права: Document

| Объект | Права | RLS |
|--------|-------|-----|
| РеализацияТоваров | Read | Где Сотрудник = &ТекущийСотрудник |
"""


def test_parse_rights_hits_from_text() -> None:
    hits = parse_rights_hits_from_text(
        ROLE_MD_SNIPPET,
        role="ТестоваяРоль",
        synonym="Тест",
        md_path="roles/ТестоваяРоль.md",
        object_query="Catalog.Номенклатура",
        required_rights=frozenset({"Read"}),
        metadata_type_filter=None,
    )
    assert len(hits) == 1
    assert hits[0].role == "ТестоваяРоль"
    assert hits[0].metadata_type == "Catalog"
    assert hits[0].rights == ("Read", "View")

    with_rights_filter = parse_rights_hits_from_text(
        ROLE_MD_SNIPPET,
        role="ТестоваяРоль",
        synonym="Тест",
        md_path="roles/ТестоваяРоль.md",
        object_query="Номенклатура",
        required_rights=frozenset({"Read", "Insert"}),
        metadata_type_filter=None,
    )
    assert with_rights_filter == []

    doc_hits = parse_rights_hits_from_text(
        ROLE_MD_SNIPPET,
        role="ТестоваяРоль",
        synonym="Тест",
        md_path="roles/ТестоваяРоль.md",
        object_query="Document.РеализацияТоваров",
        required_rights=None,
        metadata_type_filter="Document",
    )
    assert len(doc_hits) == 1
    assert "ТекущийСотрудник" in doc_hits[0].rls


def test_search_roles_by_object_unit() -> None:
    rows = [
        {
            "role": "ТестоваяРоль",
            "synonym": "Тест",
            "md_path": "roles/ТестоваяРоль.md",
            "text": ROLE_MD_SNIPPET,
        }
    ]
    results = search_roles_by_object(rows, object_name="Номенклатура", rights="Read")
    assert len(results) == 1
    assert results[0]["role"] == "ТестоваяРоль"
    assert results[0]["metadata_type"] == "Catalog"
    assert "Read" in results[0]["rights"]


def test_role_chunks_not_embedded(tmp_path: Path) -> None:
    cfg = AppConfig(source=FIXTURES, output=tmp_path / "output")
    pipeline = Pipeline(cfg)
    pipeline._embedding_provider = MockEmbeddingProvider()
    pipeline.index_export(skip_embeddings=False)

    config_id = pipeline.active_configuration.id
    embeddable = pipeline.indexer.get_chunks_for_embedding(config_id)
    role_chunks = pipeline.indexer.get_role_chunks_for_search(config_id)
    assert role_chunks
    assert len(embeddable) < pipeline.indexer.count_chunks_for_config(config_id)

    with pipeline.indexer.connect() as conn:
        role_vector_ids = conn.execute(
            """
            SELECT c.vector_id
            FROM chunks c
            JOIN metadata_objects o ON o.id = c.object_id
            WHERE o.config_id = ? AND o.object_type = 'Role'
            """,
            (config_id,),
        ).fetchall()
    assert all(row[0] is None for row in role_vector_ids)


def test_api_roles_by_object(tmp_path: Path) -> None:
    cfg = AppConfig(source=FIXTURES, output=tmp_path / "output")
    client = TestClient(create_app(cfg))
    client.post("/reindex", json={"skip_embeddings": True})

    response = client.get(
        "/roles/by-object",
        params={
            "object": "Catalog.Номенклатура",
            "rights": "Read",
            "configuration": "ТестоваяКонфигурация",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["role"] == "ТестоваяРоль"
    assert data[0]["metadata_type"] == "Catalog"
    assert "Read" in data[0]["rights"]

    empty = client.get(
        "/roles/by-object",
        params={
            "object": "Номенклатура",
            "rights": "Insert",
            "configuration": "ТестоваяКонфигурация",
        },
    )
    assert empty.status_code == 200
    assert empty.json() == []
