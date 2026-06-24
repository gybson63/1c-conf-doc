# Документация из конфигурации 1С

**MCP-сервер для Cursor** — семантический поиск по документации конфигурации 1С прямо в AI-агенте.

XML-выгрузка конфигуратора индексируется один раз на сервере (SQLite + FAISS). В Cursor подключается тонкий MCP-клиент (`conf-doc mcp`), который отдаёт агенту инструменты поиска и чтения справки — без доступа к файлам выгрузки.

```
Cursor Agent  →  conf-doc mcp (stdio)  →  HTTP API  →  индекс (SQLite + FAISS)
```

## Быстрый старт

### 1. Сервер: индекс и API

Положите XML-выгрузку в `data/export/` (опциональный staging) и поднимите backend (Docker — рекомендуемый способ):

```bash
copy config.docker.example.yaml config.yaml
docker compose build
docker compose up -d
```

Индексация через **веб-UI** (`http://localhost:8050/` → «Конфигурации»):

1. **«+ Новая»** — импорт выгрузки в слот `output/exports/{Имя}/` (ZIP или привязка пути `/data/export`).
2. **«Обновить»** — парсинг XML и чанки (без эмбеддингов).
3. **«Переиндексировать»** — эмбеддинги и FAISS.

Подробно: [docs/CONFIGURATION_SLOTS.md](docs/CONFIGURATION_SLOTS.md).

Одна конфигурация из CLI (legacy):

```bash
docker compose run --rm conf-doc index
```

Проверка: `http://localhost:8050/health` (Docker). Локальная отладка: `conf-doc serve` на порту **8000**.

**Веб-интерфейс:** `http://localhost:8050/` (Docker) или `http://localhost:8000/` (локально) — статус сервера, конфигурации (слоты, мастер «+ Новая», кнопки **Обновить** / **Переиндексировать**), семантический поиск, логи. Не открывайте порт наружу без reverse proxy и аутентификации.

Локально без Docker: `pip install -e ".[embeddings]"`, `conf-doc index`, `conf-doc serve`.

### 2. Cursor: MCP-клиент

На машине разработчика (не в контейнере):

```bash
pip install -e ".[embeddings,mcp]"
```

В репозитории уже есть [`.cursor/mcp.json`](.cursor/mcp.json) — Docker backend на `http://localhost:8050`, launcher через `.venv`. После `pip install` и `docker compose up -d` **перезапустите Cursor** (MCP подхватывается при старте).

На Linux/macOS в `.cursor/mcp.json` замените `command` на `"${workspaceFolder}${/}scripts${/}mcp.sh"`.

Удалённый сервер: [mcp.json.example](mcp.json.example). Имя конфигурации (если в базе несколько): добавьте в `env` ключ `CONF_DOC_CONFIGURATION`.

После подключения агент получит tools `conf_doc_search`, `conf_doc_get_object`, `conf_doc_get_object_chunk` и др. Workflow: skill [conf-doc-search](skills/conf-doc-search/SKILL.md).

## Возможности

- **MCP** — инструменты поиска и чтения документации 1С для Cursor и других MCP-клиентов
- Парсинг выгрузки конфигуратора: справочники, документы, перечисления, регистры и др.
- Семантический поиск (эмбеддинги + FAISS), структурный поиск в SQLite
- HTTP API и CLI — для индексации, администрирования и разработки
- **Веб-UI** — health, конфигурации (слоты выгрузки, мастер «+ Новая», обновление и переиндексация), поиск, логи

## Docker

Backend для MCP: контейнер с API и локальными эмбеддингами (sentence-transformers).

**Обновление после изменений в коде:** пошаговая инструкция — [docs/DOCKER_UPDATE.md](docs/DOCKER_UPDATE.md).

| Команда | Назначение |
|---------|------------|
| `docker compose up -d` | Запустить API (backend для MCP) |
| `docker compose run --rm conf-doc index` | Индексация из `source` в config (одна конфигурация) |
| `docker compose run --rm conf-doc index --configuration Имя` | Индексация из слота `output/exports/Имя/` |
| `docker compose run --rm conf-doc configurations migrate-exports` | Перенос legacy `export_path` в слоты |
| `docker compose run --rm conf-doc embed --configuration Имя` | Только эмбеддинги (без повторного парсинга XML) |
| `docker compose run --rm conf-doc index --skip-embeddings` | Только markdown + SQLite (аналог «Обновить» в веб-UI) |
| `docker compose logs -f conf-doc` | Логи |
| `docker compose down` | Остановить |

Тома: `data/export` (read-only staging), `output` (слоты `exports/`, markdown, FAISS, SQLite), `config.yaml`, кэш моделей (`model-cache`). OpenAPI: `http://localhost:8050/docs`.

Порт на хосте задаётся через `CONF_DOC_PORT` (по умолчанию **8050**), внутри контейнера API слушает 8000 — не пересекается с локальным `conf-doc serve --port 8000`.

Сборка по умолчанию включает пакет `openai` (`EXTRAS=embeddings,openai`), но дефолтный провайдер эмбеддингов — локальный `sentence_transformers`; OpenAI включается в `config.yaml` или в мастере индексации. Только локальные модели в образе: `docker compose build --build-arg EXTRAS=embeddings`.

## Установка (разработка)

Python 3.11+, Windows / Linux / macOS.

```bash
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -e ".[embeddings,dev]"
```

## Конфигурация сервера

Скопируйте пример и укажите каталоги:

```bash
copy config.example.yaml config.yaml
```

```yaml
source: ./data/export   # fallback для CLI; в веб-UI выгрузка хранится в output/exports/{Имя}/
output: ./output

embeddings:
  provider: sentence_transformers
  model: paraphrase-multilingual-MiniLM-L12-v2

llm:
  provider: none
```

Структура `output/`:

| Путь | Назначение |
|------|------------|
| `output/exports/{Имя}/` | XML-выгрузка конфигурации (канонический слот) |
| `output/docs/{Имя}/` | Markdown |
| `output/vectors/{Имя}/` | FAISS |
| `output/db/metadata.db` | SQLite |

`data/export/` — опциональный read-only staging (Docker): **привязать** к слоту через веб-мастер или `POST /configurations/{name}/import-path` (по умолчанию без копирования; `mirror: true` — полное копирование).

**Слоты, мастер, кнопки веб-UI, несколько конфигураций:** [docs/CONFIGURATION_SLOTS.md](docs/CONFIGURATION_SLOTS.md).

## CLI

```bash
# Без эмбеддингов (только markdown + SQLite) — как «Обновить» в веб-UI
conf-doc index --configuration БухгалтерияПредприятия --skip-embeddings

# Только эмбеддинги — как «Переиндексировать»
conf-doc embed --configuration БухгалтерияПредприятия

# Полный цикл (метаданные + эмбеддинги)
conf-doc index --configuration БухгалтерияПредприятия

# Индексация из source в config.yaml (одна конфигурация, legacy)
conf-doc index

# Полная пересборка чанков и эмбеддингов (игнорировать кэш)
conf-doc index --force

# Явные пути (legacy)
conf-doc index --source ./data/export --output ./output

# Перенос legacy export_path в слоты
conf-doc configurations migrate-exports

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

## MCP (подробнее)

MCP-клиент (`conf-doc mcp`) — основной способ использования: тонкий stdio-мост к HTTP API. Индекс остаётся на сервере; в Cursor нужен только `[mcp]` и `mcp.json`.

Примеры конфигурации:

| Файл | Когда использовать |
|------|-------------------|
| [`.cursor/mcp.json`](.cursor/mcp.json) | Docker backend на `localhost:8050` |
| [mcp.json.docker.example](mcp.json.docker.example) | То же, если настраиваете MCP вручную |
| [mcp.json.example](mcp.json.example) | Удалённый или корпоративный сервер |

### Переменные окружения MCP

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

Backend для MCP и CLI. После `conf-doc serve` (или `docker compose up`) доступны:

| Endpoint | Описание |
|----------|----------|
| `GET /health` | Проверка состояния |
| `GET /configurations` | Список конфигураций (слот, индексация, эмбеддинги) |
| `POST /configurations` | Создать слот `{"name":"…"}` |
| `POST /configurations/{name}/import` | Импорт ZIP в слот |
| `POST /configurations/{name}/import-path` | Привязка или копирование пути `{"source":"…","mirror":false}` |
| `POST /configurations/{name}/detect` | Проверка слота |
| `POST /configurations/{name}/index` | Индексация `{"skip_embeddings":true}` — только метаданные |
| `POST /configurations/{name}/embed` | Только эмбеддинги |
| `GET /configurations/jobs`, `GET /configurations/jobs/{id}` | Фоновые задачи |
| `DELETE /configurations/{name}` | Удаление конфигурации |
| `POST /reindex` | *(устарел)* переиндексация |
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

## Выбор провайдера эмбеддингов

Для **семантического поиска** (`/search`) используется блок `embeddings` в `config.yaml` — это **не** LLM из раздела `llm` (см. выше). При индексации вызывается embedding-модель; chat-модель для `/query` не нужна и по умолчанию отключена.

### Почему Docker по умолчанию — локальная модель

[`config.docker.example.yaml`](config.docker.example.yaml) задаёт:

```yaml
embeddings:
  provider: sentence_transformers
  model: paraphrase-multilingual-MiniLM-L12-v2
```

Так можно индексировать **без API-ключа, без сети и без оплаты**: модель скачивается в Docker-том `model-cache`. Образ собирается с `EXTRAS=embeddings` (без пакета `openai`).

Для продакшена с максимальным качеством поиска переключитесь на API-эмбеддинги — см. ниже.

### Сравнение вариантов

| | `sentence_transformers` (дефолт Docker) | `openai` (`text-embedding-3-small` и др.) |
|---|--------------------------------------|-------------------------------------------|
| Где считается | CPU/GPU на сервере | OpenAI-compatible API (OpenAI, Polza, …) |
| Размерность | 384 (MiniLM) | 1536 (`embedding-3-small`) |
| Качество retrieval | достаточно для простых запросов | обычно заметно лучше на перефразах и косвенных формулировках |
| Стоимость | 0 | оплата за токены API |
| Зависимости | `pip install ...[embeddings]` | `...[embeddings,openai]` + ключ |

`text-embedding-3-small` — **embedding**-модель (векторизация текста), не chat LLM. В conf-doc она настраивается через `embeddings.provider: openai`, а не через `llm`.

### Переключение на API-эмбеддинги

1. Пересоберите образ с OpenAI extra:

   ```bash
   docker compose build --build-arg EXTRAS="embeddings,openai"
   ```

2. В `config.yaml`:

   ```yaml
   embeddings:
     provider: openai
     base_url: https://polza.ai/api/v1   # или https://api.openai.com/v1
     model: text-embedding-3-small
     openai_api_key: your-key-here
   ```

3. **Полная пересборка векторов** — размерность меняется, старый FAISS несовместим:

   ```bash
   docker compose run --rm conf-doc index --force
   ```

Модель, использованная при индексации, записывается в `output/vectors/{ConfigurationName}/chunk_map.json` (поле `model`).

### Кэш и повторная индексация

При повторном `index` без изменений чанков векторы берутся из SQLite-кэша (`embedding_cache`) — в статистике будет `embeddings_cached > 0`, `embeddings_computed = 0`, вызовов API не будет. Это нормально: FAISS пересобирается из кэша.

Роли (`Role`) **не попадают в FAISS** — для них точный поиск по правам: `GET /roles/by-object`, MCP `conf_doc_search_roles_by_object`.

## Структура output/

```
output/
  exports/
    {ConfigurationName}/   # слот XML (или .import_source → staging)
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
docs/
  CONFIGURATION_SLOTS.md   # слоты, веб-UI, несколько конфигураций
  DOCKER_UPDATE.md
src/onec_conf_doc/
tests/
config.example.yaml
config.docker.example.yaml
.cursor/
  mcp.json                 # MCP → localhost Docker (готовый конфиг)
mcp.json.example
AGENTS.md
ARCHITECTURE.md
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
