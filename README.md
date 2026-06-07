# Документация из конфигурации 1С

Python-приложение для извлечения справочной информации из XML-выгрузки конфигурации 1С (конфигуратор), генерации Markdown-документации, индексации в SQLite и семантического поиска (RAG) через FAISS.

## Возможности

- Парсинг выгрузки конфигуратора: справочники, документы, перечисления, регистры и др.
- Извлечение структуры метаданных и описаний (синонимы, комментарии, справка)
- Генерация `.md` файлов по иерархии метаданных
- SQLite-индекс для структурного поиска
- RAG: чанкинг, эмбеддинги (OpenAI / Ollama / sentence-transformers), FAISS
- HTTP API (FastAPI) и CLI

## Требования

- Python 3.11+
- Windows / Linux / macOS

## Установка

```bash
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -e ".[dev]"
```

Для локальных эмбеддингов без внешних API:

```bash
pip install -e ".[embeddings,dev]"
```

Для OpenAI:

```bash
pip install -e ".[openai,dev]"
```

## Конфигурация

Скопируйте пример и укажите путь к выгрузке:

```bash
copy config.example.yaml config.yaml
```

```yaml
source: ./data/export
output: ./output

embeddings:
  provider: sentence_transformers
  model: paraphrase-multilingual-MiniLM-L12-v2

llm:
  provider: none   # openai | ollama | none
```

Положите XML-выгрузку конфигурации в `data/export/` (или укажите другой путь в `config.yaml`).

## CLI

```bash
# Индексация: парсинг → markdown → SQLite → эмбеддинги → FAISS
conf-doc index

# Без эмбеддингов (только markdown + SQLite)
conf-doc index --skip-embeddings

# Полная пересборка чанков и эмбеддингов (игнорировать кэш)
conf-doc index --force

# Явные пути
conf-doc index --source ./data/export --output ./output

# Список конфигураций в БД
conf-doc configurations

# Семантический поиск
conf-doc search "реквизиты документа реализации"
conf-doc search "отпуск" --full

# Объект в БД
conf-doc show Отпуск --type Document
conf-doc show Отпуск --type Document --chunk 0   # справка

# Пересборка эмбеддингов (инкрементально из кэша; только cache miss → API)
conf-doc embed

# Игнорировать кэш, пересчитать все векторы
conf-doc embed --force

# HTTP API
conf-doc serve --port 8000
```

### Углубление после search

`search` показывает один чанк на объект (превью 800 символов). Для деталей:

1. `show <Имя> --type Document` — список чанков
2. `show ... --chunk N` — полный текст фрагмента
3. `--full` в search или файл `.md` из `output/docs/`

Подробный workflow для Cursor Agent (удалённый API): skill [conf-doc-search](skills/conf-doc-search/SKILL.md) и [AGENTS.md](AGENTS.md).

## MCP (подключение из других проектов)

MCP-сервер — тонкий клиент к HTTP API. Индекс и FAISS остаются на сервере `conf-doc serve`; в Cursor подключаете только MCP.

### Установка

```bash
pip install 1c-conf-doc[mcp]
# или из репозитория:
pip install -e ".[mcp]"
```

### Конфигурация Cursor

Скопируйте [mcp.json.example](mcp.json.example) в настройки MCP (глобально или в `.cursor/mcp.json` проекта):

```json
{
  "mcpServers": {
    "1c-conf-doc": {
      "command": "conf-doc",
      "args": ["mcp"],
      "env": {
        "CONF_DOC_API_URL": "https://conf-doc.example.com",
        "CONF_DOC_CONFIGURATION": "ЗарплатаИУправлениеПерсоналомКОРП"
      }
    }
  }
}
```

На Windows, если `conf-doc` не в PATH, укажите полный путь к exe в venv:

```json
"command": "C:\\path\\to\\project\\.venv\\Scripts\\conf-doc.exe"
```

### Переменные окружения

| Переменная | Описание |
|------------|----------|
| `CONF_DOC_API_URL` | Базовый URL API (обязательно), без `/` в конце |
| `CONF_DOC_CONFIGURATION` | Имя конфигурации по умолчанию (опционально) |
| `CONF_DOC_API_TIMEOUT` | Таймаут HTTP-запросов в секундах (по умолчанию 60) |

### Инструменты MCP

| Tool | API | Назначение |
|------|-----|------------|
| `conf_doc_health` | `GET /health` | Проверка доступности |
| `conf_doc_list_configurations` | `GET /configurations` | Список конфигураций |
| `conf_doc_search` | `POST /search` | Семантический поиск |
| `conf_doc_list_objects` | `GET /objects` | Поиск по имени в SQLite |
| `conf_doc_get_object` | `GET /objects/{type}/{name}` | Карточка объекта |
| `conf_doc_get_object_chunk` | `GET /objects/.../chunks/{N}` | Полный текст чанка |
| `conf_doc_query` | `POST /query` | RAG-ответ (опционально; см. [Поиск и RAG](#поиск-и-rag-embeddings-vs-llm)) |

Локальная проверка:

```bash
set CONF_DOC_API_URL=http://localhost:8000
conf-doc mcp
```

## HTTP API

После `conf-doc serve` доступны:

| Endpoint | Описание |
|----------|----------|
| `GET /health` | Проверка состояния |
| `POST /reindex` | Переиндексация (`{"skip_embeddings": false, "force": false}`) |
| `GET /configurations` | Список проиндексированных конфигураций |
| `GET /objects?type=Catalog&configuration=...` | Поиск объектов в SQLite |
| `GET /objects/{type}/{name}?configuration=...` | Карточка объекта, список чанков |
| `GET /objects/{type}/{name}/chunks/{index}?configuration=...` | Полный текст чанка |
| `POST /search` | Семантический поиск: `{"query": "...", "full": false, "configuration": "..."}` |
| `POST /query` | RAG-ответ (нужен `llm.provider` в config на сервере) |

OpenAPI: `{CONF_DOC_API_URL}/docs`

Подробнее про различие поиска и RAG: [Поиск и RAG](#поиск-и-rag-embeddings-vs-llm).

## Поиск и RAG: embeddings vs LLM

В conf-doc участвуют **два независимых компонента**. Их легко перепутать, потому что оба связаны с «умным» поиском по документации.

| Компонент | Назначение | Настройка в `config.yaml` | Нужен для |
|-----------|------------|---------------------------|-----------|
| **Embeddings** | Семантический поиск по FAISS | `embeddings.provider`, `embeddings.model` | `POST /search`, `conf_doc_search` |
| **LLM** | Генерация связного ответа по найденным фрагментам | `llm.provider`, `llm.model` | `POST /query`, `conf_doc_query` |

**Поиск работает без LLM.** Эмбеддинги строятся при `conf-doc index` и используются endpoint'ом `/search`.  
**RAG-ответ** (`/query`) — опциональная надстройка: сервер сам находит чанки и отправляет их в языковую модель.

### Как работает `POST /query` (RAG)

RAG = **Retrieval** (поиск) + **Generation** (генерация):

1. По вопросу выполняется тот же семантический поиск, что и в `/search` (top-k чанков).
2. Тексты чанков собираются в промпт.
3. **LLM на сервере** `conf-doc serve` формулирует ответ на русском.

Ответ API: `{"answer": "...", "sources": [...]}` — готовый текст и список источников.

По умолчанию LLM **отключён** (`llm.provider: none`). В этом случае `/query` возвращает **HTTP 503** с сообщением, что нужно включить `llm.provider` в `config.yaml` на сервере.

### Настройка LLM на сервере

LLM настраивается **только на машине, где запущен** `conf-doc serve`. Клиенты (MCP, curl, Cursor) ничего про LLM не знают — они лишь вызывают HTTP API.

```yaml
llm:
  provider: ollama   # openai | ollama | none
  model: llama3.2
  # ollama_base_url: http://localhost:11434
  # openai_api_key: ...   # для provider: openai
```

| `llm.provider` | Куда уходит запрос |
|----------------|-------------------|
| `none` | RAG отключён, `/query` → 503 |
| `ollama` | Локальная модель через Ollama API |
| `openai` | OpenAI Chat Completions (нужен API-ключ) |

Пример запроса:

```bash
curl -s -X POST "$CONF_DOC_API_URL/query" \
  -H "Content-Type: application/json" \
  -d '{"question": "Какие реквизиты у документа Отпуск?", "top_k": 5}'
```

### MCP и Cursor: нужен ли RAG?

Для работы через MCP **RAG не обязателен**. Достаточно инструментов поиска и чтения чанков — «мозг» у агента в Cursor.

| Подход | Кто формулирует ответ | Инструменты |
|--------|----------------------|-------------|
| Поиск + углубление | Агент Cursor | `conf_doc_search` → `conf_doc_get_object` → `conf_doc_get_object_chunk` |
| RAG | LLM **на сервере** conf-doc | `conf_doc_query` (`POST /query`) |

`conf_doc_query` имеет смысл, если:

- на сервере уже поднята Ollama или настроен OpenAI;
- нужен один вызов «вопрос → готовый ответ» без цепочки tool calls;
- conf-doc используют не только из Cursor (скрипты, другие HTTP-клиенты).

Если `/query` или `conf_doc_query` возвращают 503 — это ожидаемо при `llm.provider: none`. Используйте `/search` и `/objects/.../chunks/...`.

## Структура output/

```
output/
  docs/
    {ConfigurationName}/     # имя из Configuration.xml
      catalogs/
      documents/
      ...
  db/
    metadata.db              # все конфигурации в одной БД
  vectors/
    {ConfigurationName}/
      index.faiss
      chunk_map.json
```

Имя конфигурации берётся из `Configuration.xml` → `Properties/Name` (например `ЗарплатаИУправлениеПерсоналомКОРП`).  
В `config.yaml` укажите `configuration:` для поиска, если в базе несколько конфигураций.

```yaml
configuration: ЗарплатаИУправлениеПерсоналомКОРП
```

После обновления выполните `conf-doc index` — при неизменённой выгрузке чанки и эмбеддинги не пересчитываются (используется кэш). Для принудительной пересборки: `--force`.

## Структура репозитория

```
skills/                    # Agent Skills (версионируются с проектом)
  conf-doc-search/
    SKILL.md
src/onec_conf_doc/       # исходный код
tests/
config.example.yaml
AGENTS.md                  # инструкции для AI-агентов
ARCHITECTURE.md            # архитектура проекта
```

## Cursor Agent

| Файл | Назначение |
|------|------------|
| [skills/](skills/) | Skills проекта (основное расположение) |
| [AGENTS.md](AGENTS.md) | Инструкции для AI-агентов |
| [.cursor/rules/conf-doc-search.mdc](.cursor/rules/conf-doc-search.mdc) | Правило: когда применять skill |

Skill `conf-doc-search` — поиск и углубление в документации 1С. Клонируйте репозиторий — skill доступен в `skills/`.

Подробное описание компонентов, потоков данных и API: [ARCHITECTURE.md](ARCHITECTURE.md).

## Разработка

```bash
pytest
ruff check src tests
mypy src
```

## Формат входных данных

Ожидается стандартная выгрузка конфигуратора «в файлы»:

```
export/
  Configuration.xml
  Catalogs/*.xml
  Documents/*.xml
  Enums/*.xml
  ...
```

## Лицензия

См. [LICENSE](LICENSE).
