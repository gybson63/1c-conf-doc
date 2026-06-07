---
name: conf-doc-search
description: >-
  Semantic search and drill-down in 1C configuration docs via conf-doc HTTP API.
  Use when searching metadata remotely (documents, catalogs, registers), refining
  search results, reading help chunks, or answering questions about ЗУП/1C config
  documentation. Assumes API-only access unless user explicitly has local CLI.
---

# conf-doc: поиск и углубление (API)

Инструмент: **conf-doc HTTP API** (`onec_conf_doc`). База SQLite, FAISS и markdown **на сервере** — у агента и пользователя прямого доступа к файлам нет.

## Базовый URL

Задаётся переменной окружения или явно пользователем:

```bash
CONF_DOC_API_URL=https://conf-doc.example.com   # без завершающего /
```

Локальная разработка: `http://localhost:8000`

**Не используй** `conf-doc` CLI, `output/`, `metadata.db`, пути `md_path` на диске — они недоступны удалённо. Поле `md_path` в ответах API только информационное.

## Двухшаговая модель

1. **Обзор** — `POST /search`: топ объектов (один лучший чанк на объект).
2. **Детали** — `GET /objects/{type}/{name}` → список чанков → `GET .../chunks/{N}` или уточнённый `/search`.

По умолчанию `/search` обрезает `text` до **800 символов**. Передай `"full": true` для полного текста чанка.

## Endpoints

| Шаг | Метод | Путь | Назначение |
|-----|-------|------|------------|
| Health | GET | `/health` | Проверка доступности |
| Конфигурации | GET | `/configurations` | Список проиндексированных конфигураций |
| Обзор | POST | `/search` | Семантический поиск |
| Список объектов | GET | `/objects` | Поиск по имени в SQLite (`q`, `object_type`, `configuration`) |
| Карточка объекта | GET | `/objects/{object_type}/{name}` | Реквизиты, ТЧ (счётчики), список чанков, help_pages |
| Текст чанка | GET | `/objects/{object_type}/{name}/chunks/{chunk_index}` | Полный фрагмент (реквизиты, справка, …) |
| RAG | POST | `/query` | Ответ LLM по контексту (если включён на сервере) |

OpenAPI на сервере: `{CONF_DOC_API_URL}/docs`

### POST /search

```json
{
  "query": "отпуск",
  "top_k": 10,
  "full": false,
  "object_type": "Document",
  "configuration": "ЗарплатаИУправлениеПерсоналомКОРП"
}
```

Ответ: массив `{ object_type, name, synonym, score, text, chunk_index, configuration_name }`.

### GET /objects/{object_type}/{name}

Query: `?configuration=ЗарплатаИУправлениеПерсоналомКОРП`

Ответ:

```json
{
  "object": { "name", "synonym", "uuid", "object_type", ... },
  "attributes_count": 94,
  "tabular_sections_count": 25,
  "chunks": [{ "chunk_index", "token_count", "text_len", ... }],
  "help_pages": [...]
}
```

### GET /objects/{object_type}/{name}/chunks/{chunk_index}

Query: `?configuration=...`

Ответ: `{ "text", "chunk_index", "object_type", "name", "configuration_name" }`.

**Типичные чанки:** `0` — overview (справка + формы); далее — реквизиты, ТЧ, разделы формы.

## Workflow для агента (только API)

```
Прогресс:
- [ ] GET /health
- [ ] GET /configurations — имя configuration для запросов
- [ ] POST /search — обзор по запросу
- [ ] GET /objects/{type}/{name} — карточка, список chunk_index
- [ ] GET /objects/{type}/{name}/chunks/{N} — полный текст нужного фрагмента
- [ ] При необходимости — POST /search с уточнённым query или "full": true
```

**Пример (реквизиты Document.Отпуск):**

1. `POST /search` `{"query":"отпуск","object_type":"Document"}` → `Document / Отпуск`
2. `GET /objects/Document/Отпуск?configuration=...` → `attributes_count`, `chunks`
3. `GET /objects/Document/Отпуск/chunks/1?configuration=...` → таблица реквизитов в markdown-тексте

## Уточнение запроса

Смысловые запросы — через `/search`:

```json
{"query": "документ отпуск расчет среднего заработка", "top_k": 10, "full": true}
{"query": "отпуск компенсация неиспользованного", "configuration": "..."}
```

## Ранжирование

- Основа — семантика (FAISS).
- Точное совпадение query с именем/синонимом объекта поднимает его в топ (любой тип метаданных).

## RAG и LLM (`POST /query`)

`/query` и MCP-инструмент `conf_doc_query` — **опциональны**. Для обычного workflow через API достаточно `/search` + `/objects/.../chunks/...`.

### Embeddings vs LLM

| | Embeddings | LLM |
|---|------------|-----|
| Зачем | Семантический поиск (FAISS) | Связный ответ по найденным чанкам |
| Config | `embeddings.provider` | `llm.provider` |
| Endpoints | `/search` | `/query` |
| По умолчанию | Настраивается при index | `llm.provider: none` (выключен) |

### Алгоритм RAG

1. `search(question)` → top-k чанков;
2. промпт с контекстом → `LLMProvider` на **сервере**;
3. ответ: `{"answer": "...", "sources": [...]}`.

LLM настраивается в `config.yaml` **на сервере** `conf-doc serve` (`ollama` / `openai` / `none`). MCP-клиент LLM не требует.

### Когда использовать `/query` vs search + chunks

- **search + chunks** — основной путь для агента в Cursor: агент сам читает фрагменты и отвечает.
- **`/query`** — один HTTP-вызов «вопрос → ответ», если на сервере включён LLM.

## Ограничения удалённого доступа

- Нет прямого чтения `.md` файлов и SQLite — только API.
- `/query` (RAG) работает только если на сервере настроен `llm.provider`.
- `/reindex` и `/embed` — админ-операции на сервере, не для обычного поиска.
- Имена объектов с кириллицей в URL — percent-encode при необходимости (`Отпуск` → UTF-8 path).

## Ошибки

| HTTP / симптом | Действие |
|----------------|----------|
| 404 object/chunk | Проверить `object_type`, `name`, `configuration` через `/configurations` |
| 503 на `/query` | LLM отключён на сервере — использовать `/search` + `/chunks` |
| Пустой `/search` | Уточнить query; проверить `configuration` |
| Connection refused | Проверить `CONF_DOC_API_URL` |

## CLI (только локальная разработка)

Если пользователь **явно** работает на машине с индексом:

```powershell
.\.venv\Scripts\conf-doc.exe search "отпуск"
.\.venv\Scripts\conf-doc.exe show Отпуск --type Document --chunk 0
```

В остальных случаях — **только HTTP API**.

## Дополнительно

Примеры curl: [examples.md](examples.md)
