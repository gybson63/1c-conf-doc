# Инструкции для AI-агентов

## Проект

**1c-conf-doc** — CLI/API для документации и семантического поиска по XML-выгрузке конфигурации 1С.

## Доступ к данным

**По умолчанию — только удалённый HTTP API.** SQLite, FAISS и markdown лежат на сервере; не обращайся к `output/`, `metadata.db`, локальному `conf-doc` CLI, если пользователь явно не работает на хосте с индексом.

```bash
CONF_DOC_API_URL=https://conf-doc.example.com
```

## Skills (обязательно)

`skills/conf-doc-search/SKILL.md` — workflow поиска и углубления **через API**:

1. `POST /search` — обзор  
2. `GET /objects/{type}/{name}` — карточка и чанки  
3. `GET /objects/{type}/{name}/chunks/{N}` — полный текст фрагмента  

Примеры: `skills/conf-doc-search/examples.md`

## Разработка (локально)

- CLI: `.\.venv\Scripts\conf-doc.exe`
- API: `conf-doc serve`
- Правила: `.cursor/rules/development-workflow.mdc`
