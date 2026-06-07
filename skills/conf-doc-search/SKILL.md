---
name: conf-doc-search
description: >-
  Semantic search and drill-down in 1C configuration docs via conf-doc HTTP API
  or MCP (1c-conf-doc). Use when finding metadata objects (documents, catalogs,
  registers), reading attributes/tabular sections, or preparing OData queries.
  Prefer short keyword queries; use odata_fields on top-1 then verify fields
  against live OData $metadata when building data requests.
---

# conf-doc: поиск и углубление (API / MCP)

Инструмент: **conf-doc HTTP API** (`onec_conf_doc`). Индекс SQLite + FAISS + markdown **на сервере** — у удалённого агента нет доступа к `output/`, `metadata.db`, CLI.

## Базовый URL и MCP

| Среда | URL / подключение |
|-------|-------------------|
| Docker (типично) | `http://localhost:8050` |
| Локальный `conf-doc serve` | `http://localhost:8000` |
| Cursor MCP | stdio: `python -m onec_conf_doc.mcp`, env `CONF_DOC_API_URL`, `CONF_DOC_CONFIGURATION` |

```bash
CONF_DOC_API_URL=http://localhost:8050   # без завершающего /
CONF_DOC_CONFIGURATION=ЗарплатаИУправлениеПерсоналомКОРП
```

**Не используй** пути `md_path`, `output/`, SQLite на диске клиента — только API/MCP.

### MCP-инструменты (зеркало HTTP)

| MCP | HTTP | Назначение |
|-----|------|------------|
| `conf_doc_health` | GET `/health` | Доступность |
| `conf_doc_list_configurations` | GET `/configurations` | Имена проиндексированных конфигураций |
| `conf_doc_search` | POST `/search` | Семантический поиск (+ `odata_fields` для top-1) |
| `conf_doc_list_objects` | GET `/objects` | Поиск по имени в SQLite |
| `conf_doc_get_object` | GET `/objects/{type}/{name}` | Карточка: счётчики, чанки, help |
| `conf_doc_get_object_chunk` | GET `.../chunks/{N}` | Полный текст фрагмента |
| `conf_doc_query` | POST `/query` | RAG (только если LLM включён на сервере) |

OpenAPI: `{CONF_DOC_API_URL}/docs`

## Двухшаговая модель

1. **Обзор** — `POST /search` (или `conf_doc_search`): топ объектов, один лучший чанк на объект.
2. **Детали** — `GET /objects/{type}/{name}` → `chunks/{N}` или уточнённый `/search`.

По умолчанию `/search` обрезает `text` до **800 символов**. Передай `"full": true` для полного текста.  
Поле **`odata_fields` не обрезается** — для **top-1** возвращается JSON реквизитов из индекса конфигурации.

## Как формулировать query (критично для качества)

Семантический поиск **плохо работает на длинных вопросах пользователя**. Не передавай в `/search` целиком: *«Покажи 10 штатных сотрудников: ФИО, должность и подразделение»* — в топ попадут Role/Report про «персонал».

### Правила

| Делай | Не делай |
|-------|----------|
| Короткие ключевые слова: `отпуск`, `увольнение`, `Сотрудники` | Полный текст вопроса с глаголами и числами |
| Точное имя объекта: `КадроваяИсторияСотрудников` | Размытые фразы: `Catalog Сотрудники` (может не найти справочник) |
| Несколько узких запросов + выбор лучшего | Один длинный запрос «на всё» |
| Фильтр `object_type`: `Document`, `Catalog`, `InformationRegister` | Ожидать, что Report/Role подскажут OData-entity |

### Доменные доп. запросы (ЗУП)

| Тема пользователя | Дополнительные query |
|-------------------|----------------------|
| Сотрудники, ФИО, должность, штат | `Сотрудники`, `КадроваяИсторияСотрудников` |
| Отпуск, остаток отпуска | `отпуск`, `Document` + `object_type` |
| Начисление зарплаты | `НачислениеЗарплаты`, `начисление зарплаты` |
| Увольнение | `увольнение`, `Увольнение` |

### Приоритет типов для OData-задач

Предпочитай результаты: **Catalog, Document, InformationRegister, AccumulationRegister, CalculationRegister**.  
Игнорируй для выбора entity: **Role, Report, CommonForm, Constant, Subsystem** — unless нет ничего лучше.

## Endpoints

| Шаг | Метод | Путь | Назначение |
|-----|-------|------|------------|
| Health | GET | `/health` | Проверка доступности |
| Конфигурации | GET | `/configurations` | Список проиндексированных конфигураций |
| Обзор | POST | `/search` | Семантический поиск |
| Список объектов | GET | `/objects` | Поиск по имени в SQLite (`q`, `object_type`, `configuration`) |
| Карточка объекта | GET | `/objects/{object_type}/{name}` | Реквизиты, ТЧ (счётчики), список чанков, help_pages |
| Текст чанка | GET | `/objects/{object_type}/{name}/chunks/{chunk_index}` | Полный фрагмент |
| RAG | POST | `/query` | Ответ LLM по контексту (если включён на сервере) |

### POST /search

```json
{
  "query": "отпуск",
  "top_k": 10,
  "full": false,
  "include_fields": true,
  "object_type": "Document",
  "configuration": "ЗарплатаИУправлениеПерсоналомКОРП"
}
```

Ответ: массив `{ object_type, name, synonym, score, text, chunk_index, configuration_name }`.

**Top-1** дополнительно содержит `odata_fields` (если `include_fields: true`, по умолчанию **включено**):

```json
{
  "entity_type": "Document_Отпуск",
  "fields": [
    {
      "name": "Организация",
      "type": "CatalogRef.Организации",
      "title": "Организация",
      "comment": "",
      "required": true,
      "kind": "attribute"
    },
    {
      "name": "ПодразделениеОрганизации",
      "type": "CatalogRef.ПодразделенияОрганизаций",
      "title": "Подразделение",
      "required": false,
      "kind": "attribute"
    }
  ],
  "tabular_sections": [
    {
      "name": "Начисления",
      "title": "Начисления",
      "comment": "",
      "fields": []
    }
  ]
}
```

`include_fields: false` — только массив search-хитов без JSON полей.

### GET /objects/{object_type}/{name}

Query: `?configuration=ЗарплатаИУправлениеПерсоналомКОРП`

Ответ:

```json
{
  "object": { "name", "synonym", "uuid", "object_type", "..." },
  "attributes_count": 94,
  "tabular_sections_count": 25,
  "chunks": [{ "chunk_index", "token_count", "text_len", "..." }],
  "help_pages": []
}
```

### GET /objects/{object_type}/{name}/chunks/{chunk_index}

**Типичные чанки:** `0` — overview (справка + формы); `1` — реквизиты шапки; далее — ТЧ. Таблица реквизитов может быть разбита на несколько чанков с повторяющимся заголовком.

**Report:** дополнительные чанки — `## Модуль объекта` (BSL) и по одному чанку на каждый `## Запрос СКД: {имя набора}` с полным текстом запроса из основной схемы компоновки данных. Для анализа источников данных отчёта читай чанки с «Запрос СКД», не только overview.

## conf-doc + OData: два слоя правды

| Слой | Источник | Что даёт |
|------|----------|----------|
| Объект и смысл полей | conf-doc (`search`, `odata_fields`, chunks) | `Document.Отпуск`, реквизиты конфигурации, справка |
| Имена полей в **запросе к базе** | OData `$metadata` / `get_entity_fields` | Фактические `Property` и `NavigationProperty` **публикации** |

**Важно:** `odata_fields` строится из **XML конфигурации**, не из OData-публикации ИБ. Имена могут расходиться:

| Конфигурация (conf-doc) | OData публикация (может быть) |
|-------------------------|-------------------------------|
| `ПодразделениеОрганизации` | `Подразделение` |
| `ПодразделениеОрганизации_Key` | `Подразделение_Key` |

Перед `$select` / `$expand` / `$filter` **всегда сверяй** имена с OData метаданными целевой базы. conf-doc подсказывает объект и бизнес-смысл; OData — точные сегменты URL.

## Workflow для агента

### Только структура конфигурации (блок «что за объект»)

```
Прогресс:
- [ ] GET /health (или conf_doc_health)
- [ ] GET /configurations — поле name для configuration
- [ ] POST /search — короткий query (+ odata_fields на top-1)
- [ ] GET .../chunks/{N} — полная таблица реквизитов / справка
```

### Перед OData-запросом к данным

```
Прогресс:
- [ ] conf_doc_search — короткие keyword-запросы (см. выше)
- [ ] Выбрать Catalog/Document/Register из top-k (не Role/Report)
- [ ] Прочитать odata_fields top-1 или chunk с реквизитами
- [ ] Смаппить тип → OData entity (Document_Имя, Catalog_Имя, …)
- [ ] OData $metadata / get_entity_fields — финальные имена полей
- [ ] fetch / OData — запрос данных
```

**Пример (реквизиты Document.Отпуск):**

1. `POST /search` `{"query":"отпуск","object_type":"Document"}` → `Document / Отпуск` + `odata_fields.fields`
2. При необходимости полной таблицы: `GET /objects/Document/Отпуск/chunks/1?configuration=...`
3. OData: `Document_Отпуск` — поля из `$metadata`, не только из conf-doc

**Пример (сотрудники с должностью — ЗУП):**

1. `POST /search` `{"query":"Сотрудники","top_k":5}` → `Catalog.Сотрудники`
2. `POST /search` `{"query":"КадроваяИсторияСотрудников"}` → `InformationRegister.КадроваяИсторияСотрудников`
3. OData: кадровые данные часто из `InformationRegister_КадроваяИсторияСотрудников_RecordType` (не из справочника); поля подразделения — по `$metadata`

## Маппинг типов → OData-префиксы

| Тип conf-doc | Префикс OData | Пример |
|--------------|---------------|--------|
| Catalog | `Catalog_` | `Catalog_Сотрудники` |
| Document | `Document_` | `Document_Отпуск` |
| InformationRegister | `InformationRegister_` | `InformationRegister_КадроваяИсторияСотрудников` |
| AccumulationRegister | `AccumulationRegister_` | `AccumulationRegister_...` |
| CalculationRegister | `CalculationRegister_` | `CalculationRegister_...` |
| DocumentJournal | `DocumentJournal_` | `DocumentJournal_...` |
| Enum | `Enum_` | `Enum_...` |

Имя `configuration` в запросах — поле **`name`** из `/configurations` (для ЗУП 3.1: `ЗарплатаИУправлениеПерсоналомКОРП`), не синоним и не «ЗУП».

## Уточнение запроса

```json
{"query": "документ отпуск", "top_k": 10, "object_type": "Document"}
{"query": "КадроваяИсторияСотрудников", "top_k": 5, "include_fields": true}
{"query": "начисление зарплаты", "top_k": 5, "object_type": "Document", "full": true}
```

## Ранжирование

- Основа — семантика (FAISS).
- Точное совпадение query с именем/синонимом объекта поднимает его в топ.
- Длинные «разговорные» запросы размывают score — дроби на keywords.

## RAG и LLM (`POST /query`)

`/query` и `conf_doc_query` — **опциональны**. По умолчанию `llm.provider: none` → **503**.

| | Embeddings | LLM |
|---|------------|-----|
| Зачем | `/search` (FAISS) | `/query` (связный ответ) |
| Для агента | **основной путь** | если явно включён на сервере |

**Рекомендация:** `search` + `odata_fields` + `chunks` — агент сам собирает ответ; надёжнее RAG для точных имён полей.

## Ограничения

- Нет прямого чтения `.md` / SQLite с клиента.
- `odata_fields` ≠ гарантия имён в OData публикации.
- `/reindex`, `/embed` — админ на сервере.
- Кириллица в URL path — percent-encode при необходимости.
- Виртуальные таблицы OData (`/SliceLast()`, `/Balance()`) в conf-doc не описаны — смотри OData skill / `$metadata`.

## Ошибки

| HTTP / симптом | Действие |
|----------------|----------|
| 404 object/chunk | Проверить `object_type`, `name`, `configuration` через `/configurations` |
| 503 на `/query` | LLM отключён — `search` + `chunks` |
| Пустой `/search` | Укоротить query; точное имя объекта; проверить `configuration` |
| 500 на `/search` | Часто несовпадение размерности FAISS — переиндекс на сервере |
| Connection refused | `CONF_DOC_API_URL`, `docker compose ps` |
| OData 400 code 6 | Сегмент поля не найден — сверить с OData `$metadata`, не только conf-doc |

## CLI (только локальная машина с индексом)

```powershell
cd C:\ПервыйБИТ\ИИ\1c-conf-doc
.\.venv\Scripts\conf-doc.exe search "отпуск"
.\.venv\Scripts\conf-doc.exe show Отпуск --type Document --chunk 1
```

В Cursor / удалённом агенте — **только HTTP API или MCP**.

## Дополнительно

Примеры curl: [examples.md](examples.md)
