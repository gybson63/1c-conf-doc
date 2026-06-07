# Обновление Docker-контейнера conf-doc

Инструкция для повторяемого обновления backend после значимых изменений в коде, зависимостях или логике индексации.

## Когда выполнять полное обновление

| Ситуация | Пересборка образа | Переиндексация |
|----------|-------------------|----------------|
| Изменился Python-код (`src/`) | Да | Да (см. ниже) |
| Изменился `Dockerfile` или `pyproject.toml` | Да (`--no-cache` при смене зависимостей) | Да |
| Изменилась логика чанкинга / парсинга (например `CHUNKER_VERSION`) | Да | `index` (чанки пересоберутся автоматически) |
| Обновилась только XML-выгрузка в `data/export/` | Нет | `index` |
| Изменился только `config.yaml` (chunking, embeddings) | Нет* | `index --force` или `embed --force` |
| Изменился только MCP-клиент на хосте (`mcp/`, скрипты) | Нет | Нет |

\* Контейнер подхватывает `config.yaml` при следующем `docker compose up` (файл смонтирован read-only). Перезапуск сервиса достаточен, если менялись только `api`/`llm`, без индекса.

## Что сохраняется между обновлениями

| Путь / том | Содержимое | Удаляется при `docker compose down`? |
|------------|------------|--------------------------------------|
| `./output/` | SQLite, markdown, FAISS | Нет (на диске хоста) |
| `./data/export/` | XML-выгрузка | Нет |
| `./config.yaml` | Настройки сервера | Нет |
| том `model-cache` | Кэш Hugging Face (sentence-transformers) | Нет (именованный том) |
| Образ `conf-doc` | Собранный код и pip-пакеты | Нет (пока не `docker image rm`) |

Полная «чистая» переиндексация с нуля: удалите `output/` вручную, затем выполните `index` (долго — заново считаются эмбеддинги).

---

## Стандартная процедура (после `git pull` или локальных правок)

Выполняйте из корня репозитория.

### 1. Остановить API

```powershell
docker compose down
```

### 2. Пересобрать образ

Обычная пересборка после изменений кода:

```powershell
docker compose build
```

Если менялись зависимости в `pyproject.toml` или слой в `Dockerfile`:

```powershell
docker compose build --no-cache
```

Сборка с OpenAI-эмбеддингами вместо локальных:

```powershell
docker compose build --build-arg EXTRAS="embeddings,openai"
```

### 3. Запустить API

```powershell
docker compose up -d
```

Проверка:

```powershell
curl http://localhost:8050/health
```

Ожидается HTTP 200. Порт на хосте — `8050` по умолчанию (`CONF_DOC_PORT` в `.env` или окружении).

### 4. Переиндексировать выгрузку

**После изменений парсера, chunker, markdown** (новые типы чанков, Report+СКД и т.п.):

```powershell
docker compose run --rm conf-doc index
```

Инкрементально: обновятся только изменившиеся объекты; при смене `CHUNKER_VERSION` чанки пересоберутся для всех объектов.

Принудительная полная пересборка чанков и эмбеддингов:

```powershell
docker compose run --rm conf-doc index --force
```

Только markdown + SQLite, без эмбеддингов (быстрая проверка парсинга):

```powershell
docker compose run --rm conf-doc index --skip-embeddings
```

Затем отдельно эмбеддинги:

```powershell
docker compose run --rm conf-doc embed
```

Через HTTP API (контейнер уже запущен):

```powershell
curl -X POST http://localhost:8050/reindex -H "Content-Type: application/json" -d "{}"
```

С принудительной пересборкой:

```powershell
curl -X POST http://localhost:8050/reindex -H "Content-Type: application/json" -d "{\"force\": true}"
```

### 5. Обновить MCP-клиент на хосте (если менялся код `mcp/` или API-клиент)

Контейнер обслуживает только HTTP API. Cursor запускает `conf-doc mcp` **на хосте** из `.venv`:

```powershell
.\.venv\Scripts\activate
pip install -e ".[embeddings,mcp]"
```

Перезапустите Cursor (MCP подхватывается при старте IDE).

### 6. Проверка поиска

```powershell
docker compose run --rm conf-doc search "отчёт номенклатура" --top-k 3
```

Или smoke test MCP (из активированного `.venv`):

```powershell
$env:CONF_DOC_API_URL = "http://localhost:8050"
conf-doc mcp
```

---

## Краткий чеклист

Скопируйте и отмечайте при каждом значимом релизе:

```
[ ] git pull / локальные изменения закоммичены
[ ] docker compose down
[ ] docker compose build          (или build --no-cache)
[ ] docker compose up -d
[ ] curl http://localhost:8050/health
[ ] docker compose run --rm conf-doc index
[ ] (при смене mcp/) pip install -e ".[embeddings,mcp]" + перезапуск Cursor
[ ] docker compose run --rm conf-doc search "тестовый запрос"
[ ] docker compose logs -f conf-doc   — нет ошибок при старте
```

---

## Сценарии по типу изменения

### Новая функция индексации (Report, СКД, chunker v3)

1. `docker compose build`
2. `docker compose up -d`
3. `docker compose run --rm conf-doc index` — пересоберутся чанки и эмбеддинги для затронутых объектов
4. Убедитесь, что в `GET /objects/Report/{имя}` появились чанки «Запрос СКД» / «Модуль объекта»

### Только новая выгрузка 1С

1. Скопируйте XML в `data/export/`
2. `docker compose run --rm conf-doc index` — образ пересобирать не нужно

### Смена модели эмбеддингов в `config.yaml`

1. Отредактируйте `config.yaml` на хосте
2. `docker compose restart conf-doc`
3. `docker compose run --rm conf-doc index --force` или `docker compose run --rm conf-doc embed --force`

### Смена `chunking.max_tokens` / `overlap_tokens`

1. Обновите `config.yaml`
2. `docker compose run --rm conf-doc index --force`

---

## Диагностика

| Симптом | Действие |
|---------|----------|
| `Connection refused` на `:8050` | `docker compose ps`, `docker compose logs conf-doc` |
| Поиск пустой, hint про embed | `docker compose run --rm conf-doc embed` |
| Старые чанки после обновления кода | `docker compose run --rm conf-doc index --force` |
| Образ не обновился | `docker compose build --no-cache` и снова `up -d` |
| MCP не видит новые tools | `pip install -e ".[mcp]"` на хосте, перезапуск Cursor |

Логи в реальном времени:

```powershell
docker compose logs -f conf-doc
```

---

## Справка: тома и порты

См. [`docker-compose.yml`](../docker-compose.yml):

- `data/export` → `/data/export` (read-only)
- `output` → `/data/output`
- `config.yaml` → `/config/config.yaml`
- `model-cache` — кэш моделей sentence-transformers

Пример конфигурации: [`config.docker.example.yaml`](../config.docker.example.yaml).

Первичная установка: раздел **Docker** в [`README.md`](../README.md).
