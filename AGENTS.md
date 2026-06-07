# Инструкции для AI-агентов

## Проект

**1c-conf-doc** — MCP-сервер для семантического поиска по документации конфигурации 1С в Cursor.

Архитектура: индекс на сервере (Docker / `conf-doc serve`), MCP-клиент в Cursor (`conf-doc mcp`) → HTTP API.

## Доступ к данным

**Только через MCP tools или HTTP API.** SQLite, FAISS и markdown на сервере; не обращайся к `output/`, `metadata.db`, локальному CLI, если пользователь явно не на хосте с индексом.

Конфиг MCP: [`.cursor/mcp.json`](.cursor/mcp.json) (локальный Docker) или [mcp.json.example](mcp.json.example) (удалённый сервер).

## Skills (обязательно)

`skills/conf-doc-search/SKILL.md` — workflow поиска и углубления через MCP/API:

1. `conf_doc_search` / `POST /search` — обзор
2. `conf_doc_get_object` / `GET /objects/{type}/{name}` — карточка и чанки
3. `conf_doc_get_object_chunk` / `GET /objects/.../chunks/{N}` — полный текст

Примеры: `skills/conf-doc-search/examples.md`

RAG (`conf_doc_query`) опционален — см. [README — Поиск и RAG](README.md#поиск-и-rag-embeddings-vs-llm).

## Docker: обновление backend

После значимых изменений (`src/`, `Dockerfile`, chunker, парсер): [docs/DOCKER_UPDATE.md](docs/DOCKER_UPDATE.md) — пересборка образа, `index`, при необходимости обновление MCP на хосте.

## Разработка (локально)

- CLI: `.\.venv\Scripts\conf-doc.exe`
- API (backend MCP): `conf-doc serve`
- MCP smoke test (Docker): `set CONF_DOC_API_URL=http://localhost:8050` → `conf-doc mcp`
- Локальный API: `conf-doc serve` (порт 8000)
- Правила: `.cursor/rules/development-workflow.mdc`
