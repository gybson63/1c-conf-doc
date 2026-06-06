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

Переменная для клиентов и агентов: `CONF_DOC_API_URL` (базовый URL без `/` в конце).

OpenAPI: `{CONF_DOC_API_URL}/docs`

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
