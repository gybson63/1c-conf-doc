# Changelog

Все значимые изменения проекта документируются в этом файле.

Формат основан на [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/),
версионирование — [Semantic Versioning](https://semver.org/lang/ru/).

Опубликованные версии — в [GitHub Releases](https://github.com/gybson63/1c-conf-doc/releases).

## [Unreleased]

### Added

- Удаление конфигурации из базы: `DELETE /configurations/{name}`, `conf-doc configurations delete`, кнопка в веб-UI; MCP `conf_doc_delete_configuration`. По умолчанию удаляются также markdown и FAISS на диске.

### Changed

### Fixed

### Removed

## [0.3.0] - 2026-06-17

### Added

- Веб-интерфейс на `/` — статус сервера, список конфигураций, добавление (путь на сервере или ZIP), семантический поиск, просмотр логов.
- Страница `/object/{type}/{name}` в веб-UI — просмотр всех чанков объекта; ссылка «Все чанки объекта» в результатах поиска.
- `POST /configurations/index` — фоновая индексация по пути к выгрузке на сервере; `POST /configurations/upload` — загрузка ZIP (зависимость `python-multipart`).
- `GET /configurations/jobs`, `GET /configurations/jobs/{id}` — статус и логи задач индексации; `GET /logs` — буфер логов сервера.
- `import_roots` в config.yaml — разрешённые каталоги для индексации по пути.
- Расширенный `GET /health`: версия, состояние БД, число конфигураций.
- `POST /reindex` — опциональные `source` и `async_job` для переиндексации и фонового запуска.
- `GET /roles/by-object` — точный поиск ролей по имени объекта метаданных и правам (без векторов); MCP-инструмент `conf_doc_search_roles_by_object`.
- Парсинг `Roles/{Имя}/Ext/Rights.xml`: права ролей попадают в markdown (секции `## Права` и `## Права: {тип}`) и чанки.
- Pre-commit hook `check-changelog`: при изменениях кода в `src/onec_conf_doc/` требует обновление `CHANGELOG.md`.
- Документация [docs/DOCKER_UPDATE.md](docs/DOCKER_UPDATE.md) — процедура обновления Docker-контейнера после значимых изменений.
- Docker: `Dockerfile`, `docker-compose.yml`, `config.docker.example.yaml` — backend для MCP.
- Готовый [`.cursor/mcp.json`](.cursor/mcp.json) и launcher'ы `scripts/mcp.cmd` / `scripts/mcp.sh`.
- MCP-сервер (`conf-doc mcp`): подключение к удалённому conf-doc API из Cursor и других MCP-клиентов через stdio.
- Опциональная зависимость `[mcp]` и пример конфигурации `mcp.json.example`.

### Changed

- Роли (`Role`) исключены из векторной индексации: чанки остаются для точного поиска, FAISS их не содержит.
- Документация и позиционирование: MCP — основной сценарий; Docker — backend для MCP; `mcp.json.docker.example`.
- Docker по умолчанию на хосте слушает порт **8050** (`CONF_DOC_PORT`), локальная отладка — **8000**.
- Документация: раздел «Поиск и RAG» (README, ARCHITECTURE, skill) — embeddings vs LLM, настройка `llm.provider`, когда нужен `/query`.
- Документация: раздел «Выбор провайдера эмбеддингов» — дефолт Docker (`sentence_transformers`), сравнение с API (`text-embedding-3-small`), переключение и `--force`.

### Fixed

- Парсер XML: измерения и ресурсы регистров (`Dimension`, `Resource`) попадают в индекс, markdown и `odata_fields` (раньше карточка IR была пустой).

### Removed

## [0.2.0] - 2026-06-07

### Added

- Инкрементальная пересборка чанков: только для изменённых или удалённых объектов; повторный `index` без изменений сохраняет `chunks.id`.
- Кэш эмбеддингов в SQLite (`embedding_cache`): ключ `(config_id, content_hash, model)`; API вызывается только для cache miss.
- Инкрементальный `build_embeddings`: сбор FAISS из кэша + новых векторов; счётчики `embeddings_cached` / `embeddings_computed`.
- Флаги `--force` для `conf-doc index` и `conf-doc embed`; параметр `"force"` в `POST /reindex`.
- Метаданные модели в `chunk_map.json` (`model`, `built_at`); auto-detect смены модели и параметров chunking.
- Документ [ARCHITECTURE.md](ARCHITECTURE.md) — описание архитектуры проекта (включая подробный раздел про FAISS).
- API: `GET /objects/{type}/{name}` и `GET /objects/{type}/{name}/chunks/{index}` — карточка объекта и текст чанка для удалённого доступа.
- Параметр `full` в `POST /search` (полный текст чанка, аналог CLI `--full`).
- Cursor skill `conf-doc-search` в каталоге `skills/conf-doc-search/` — workflow через HTTP API.
- `AGENTS.md` и правило `.cursor/rules/conf-doc-search.mdc` для AI-агентов.
- Правила разработки в `.cursor/rules/development-workflow.mdc`.
- Конфигурация `pyproject.toml` для ruff и mypy.
- Pre-commit hooks: ruff, ruff-format, mypy, conventional commits.
- Пакет `src/onec_conf_doc` — начальная структура проекта.

### Changed

- Поток индексации: удаление объектов, исчезнувших из XML-выгрузки; расширенный `embedding_status()`.
- Базовая ветка разработки: `main` (отслеживает `origin/main`).

### Added

- Процесс версионированных релизов: `scripts/release.py`, GitHub Actions `release.yml`.
- Единый источник версии через `pyproject.toml` и `onec_conf_doc._version`.
