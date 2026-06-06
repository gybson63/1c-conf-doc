# Changelog

Все значимые изменения проекта документируются в этом файле.

Формат основан на [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/),
версионирование — [Semantic Versioning](https://semver.org/lang/ru/).

## [Unreleased]

### Added

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

- Базовая ветка разработки: `main` (отслеживает `origin/main`).
