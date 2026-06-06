# Changelog

Все значимые изменения проекта документируются в этом файле.

Формат основан на [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/),
версионирование — [Semantic Versioning](https://semver.org/lang/ru/).

Опубликованные версии — в [GitHub Releases](https://github.com/gybson63/1c-conf-doc/releases).

## [Unreleased]

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
