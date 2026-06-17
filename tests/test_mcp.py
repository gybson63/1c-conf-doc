"""Tests for conf-doc MCP HTTP client."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient

from onec_conf_doc.api.app import create_app
from onec_conf_doc.config import AppConfig
from onec_conf_doc.mcp.client import ConfDocApiClient, ConfDocApiError

FIXTURES = Path(__file__).parent / "fixtures" / "export_minimal"


def _testclient_to_httpx(test_client: TestClient, request: httpx.Request) -> httpx.Response:
    parsed = urlparse(str(request.url))
    path = parsed.path
    if parsed.query:
        path = f"{path}?{parsed.query}"

    content = request.content
    json_body: Any | None = None
    if content:
        json_body = httpx.Response(200, content=content).json()

    response = test_client.request(
        request.method,
        path,
        json=json_body,
    )
    return httpx.Response(
        status_code=response.status_code,
        headers=response.headers,
        content=response.content,
        request=request,
    )


@pytest.fixture
def api_client(tmp_path: Path) -> ConfDocApiClient:
    cfg = AppConfig(source=FIXTURES, output=tmp_path / "output")
    test_client = TestClient(create_app(cfg))
    test_client.post("/reindex", json={"skip_embeddings": True})

    transport = httpx.MockTransport(lambda req: _testclient_to_httpx(test_client, req))
    http = httpx.Client(transport=transport, base_url="http://testserver")
    client = ConfDocApiClient("http://testserver", default_configuration="ТестоваяКонфигурация")
    client._client = http
    yield client
    http.close()


def test_client_requires_base_url() -> None:
    with pytest.raises(ValueError, match="CONF_DOC_API_URL"):
        ConfDocApiClient("")


def test_client_health_and_search(api_client: ConfDocApiClient) -> None:
    health = api_client.health()
    assert health["status"] == "ok"
    assert health["database"] == "ok"
    assert "version" in health

    results = api_client.search("номенклатура", top_k=3)
    assert len(results) >= 1
    assert results[0]["name"] == "Номенклатура"


def test_client_get_object_and_chunk(api_client: ConfDocApiClient) -> None:
    detail = api_client.get_object("Catalog", "Номенклатура")
    assert detail["object"]["name"] == "Номенклатура"
    assert detail["attributes_count"] >= 1

    chunk = api_client.get_object_chunk("Catalog", "Номенклатура", 0)
    assert chunk["chunk_index"] == 0
    assert "text" in chunk


def test_client_search_roles_by_object(api_client: ConfDocApiClient) -> None:
    results = api_client.search_roles_by_object("Catalog.Номенклатура", rights="Read")
    assert len(results) == 1
    assert results[0]["role"] == "ТестоваяРоль"


def test_client_not_found(api_client: ConfDocApiClient) -> None:
    with pytest.raises(ConfDocApiError) as exc_info:
        api_client.get_object("Catalog", "НетТакого")
    assert exc_info.value.status_code == 404


def test_client_passes_configuration_query() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        parsed = urlparse(str(request.url))
        captured.update(parse_qs(parsed.query))
        return httpx.Response(200, json={"object": {"name": "X"}}, request=request)

    http = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://testserver")
    client = ConfDocApiClient("http://testserver", default_configuration="DefaultCfg")
    client._client = http
    client.get_object("Catalog", "Test")
    http.close()

    assert captured["configuration"] == ["DefaultCfg"]


def test_mcp_tools_registered() -> None:
    pytest.importorskip("mcp")
    from onec_conf_doc.mcp.server import create_mcp_server

    server = create_mcp_server(client=ConfDocApiClient("http://example.test"))
    tool_names = {tool.name for tool in server._tool_manager.list_tools()}  # noqa: SLF001
    expected = {
        "conf_doc_health",
        "conf_doc_list_configurations",
        "conf_doc_search",
        "conf_doc_search_roles_by_object",
        "conf_doc_list_objects",
        "conf_doc_get_object",
        "conf_doc_get_object_chunk",
        "conf_doc_query",
    }
    assert expected <= tool_names
