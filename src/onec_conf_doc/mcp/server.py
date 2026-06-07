"""MCP stdio server exposing conf-doc HTTP API as tools."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from onec_conf_doc.mcp.client import ConfDocApiClient, ConfDocApiError

JsonText = str


def _dump(data: Any) -> JsonText:
    return json.dumps(data, ensure_ascii=False, indent=2)


def _error_message(exc: Exception) -> JsonText:
    if isinstance(exc, ConfDocApiError):
        payload: dict[str, Any] = {"error": str(exc)}
        if exc.status_code is not None:
            payload["status_code"] = exc.status_code
        return _dump(payload)
    return _dump({"error": str(exc)})


def create_mcp_server(client: ConfDocApiClient | None = None) -> Any:
    """Build FastMCP server with conf-doc tools."""
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP(
        "1c-conf-doc",
        instructions=(
            "Семантический поиск и детали метаданных конфигурации 1С через conf-doc API. "
            "Workflow: list_configurations → search → get_object → get_object_chunk. "
            "По умолчанию search обрезает text до 800 символов; "
            "используй full=true для полного текста. "
            "Top-1 результата search содержит odata_fields с реквизитами объекта."
        ),
    )

    @contextmanager
    def _client() -> Iterator[ConfDocApiClient]:
        owned = client is None
        api = client or ConfDocApiClient()
        try:
            yield api
        finally:
            if owned:
                api.close()

    @mcp.tool()
    def conf_doc_health() -> JsonText:
        """Проверить доступность conf-doc API."""
        try:
            with _client() as api:
                return _dump(api.health())
        except Exception as exc:  # noqa: BLE001 — return error text to the agent
            return _error_message(exc)

    @mcp.tool()
    def conf_doc_list_configurations() -> JsonText:
        """Список проиндексированных конфигураций 1С на сервере."""
        try:
            with _client() as api:
                return _dump(api.list_configurations())
        except Exception as exc:  # noqa: BLE001
            return _error_message(exc)

    @mcp.tool()
    def conf_doc_search(
        query: str,
        top_k: int = 5,
        full: bool = False,
        include_fields: bool = True,
        object_type: str | None = None,
        configuration: str | None = None,
    ) -> JsonText:
        """Семантический поиск по документации конфигурации 1С (FAISS + ранжирование).

        Args:
            query: Поисковый запрос на естественном языке.
            top_k: Число результатов (1–50).
            full: True — полный текст чанка; False — превью до 800 символов.
            include_fields: True — для top-1 добавить odata_fields (JSON реквизитов из SQLite).
            object_type: Фильтр типа метаданных (Document, Catalog, Enum, …).
            configuration: Имя конфигурации; если не задано — из
                CONF_DOC_CONFIGURATION или первая в БД.
        """
        try:
            with _client() as api:
                return _dump(
                    api.search(
                        query,
                        top_k=top_k,
                        full=full,
                        include_fields=include_fields,
                        object_type=object_type,
                        configuration=configuration,
                    )
                )
        except Exception as exc:  # noqa: BLE001
            return _error_message(exc)

    @mcp.tool()
    def conf_doc_list_objects(
        q: str | None = None,
        object_type: str | None = None,
        configuration: str | None = None,
        limit: int = 50,
    ) -> JsonText:
        """Поиск объектов метаданных по имени в SQLite (точное/подстрочное совпадение).

        Args:
            q: Подстрока имени или синонима объекта.
            object_type: Тип метаданных (Document, Catalog, …).
            configuration: Имя конфигурации.
            limit: Максимум записей (1–500).
        """
        try:
            with _client() as api:
                return _dump(
                    api.list_objects(
                        q=q,
                        object_type=object_type,
                        configuration=configuration,
                        limit=limit,
                    )
                )
        except Exception as exc:  # noqa: BLE001
            return _error_message(exc)

    @mcp.tool()
    def conf_doc_get_object(
        object_type: str,
        name: str,
        configuration: str | None = None,
    ) -> JsonText:
        """Карточка объекта метаданных: реквизиты, счётчики, список чанков, help_pages.

        Args:
            object_type: Тип метаданных (Document, Catalog, Enum, …).
            name: Имя объекта (например «Отпуск»).
            configuration: Имя конфигурации.
        """
        try:
            with _client() as api:
                return _dump(api.get_object(object_type, name, configuration=configuration))
        except Exception as exc:  # noqa: BLE001
            return _error_message(exc)

    @mcp.tool()
    def conf_doc_get_object_chunk(
        object_type: str,
        name: str,
        chunk_index: int,
        configuration: str | None = None,
    ) -> JsonText:
        """Полный текст фрагмента документации объекта (реквизиты, справка, формы).

        Args:
            object_type: Тип метаданных.
            name: Имя объекта.
            chunk_index: Индекс чанка из get_object (0 — overview/справка, далее реквизиты и ТЧ).
            configuration: Имя конфигурации.
        """
        try:
            with _client() as api:
                return _dump(
                    api.get_object_chunk(
                        object_type,
                        name,
                        chunk_index,
                        configuration=configuration,
                    )
                )
        except Exception as exc:  # noqa: BLE001
            return _error_message(exc)

    @mcp.tool()
    def conf_doc_query(
        question: str,
        top_k: int = 5,
        configuration: str | None = None,
    ) -> JsonText:
        """RAG-ответ LLM по документации конфигурации (требует llm.provider на сервере).

        Args:
            question: Вопрос на естественном языке.
            top_k: Число фрагментов контекста (1–20).
            configuration: Имя конфигурации.
        """
        try:
            with _client() as api:
                return _dump(api.query_rag(question, top_k=top_k, configuration=configuration))
        except Exception as exc:  # noqa: BLE001
            return _error_message(exc)

    return mcp


def run_stdio_server() -> None:
    """Run MCP server over stdio (for Cursor and other MCP clients)."""
    create_mcp_server().run(transport="stdio")
