# Примеры: conf-doc search (API)

`API=https://conf-doc.example.com` — замените на ваш `CONF_DOC_API_URL`.

## Обзор: Document «Отпуск»

```bash
curl -s -X POST "$API/search" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "отпуск",
    "top_k": 5,
    "object_type": "Document",
    "configuration": "ЗарплатаИУправлениеПерсоналомКОРП"
  }'
```

## Карточка объекта (аналог `show`)

```bash
curl -s "$API/objects/Document/Отпуск?configuration=ЗарплатаИУправлениеПерсоналомКОРП"
```

Ответ: `attributes_count`, `tabular_sections_count`, массив `chunks` с `chunk_index`.

## Реквизиты — текст чанка

```bash
# chunk 0 — справка и формы
curl -s "$API/objects/Document/Отпуск/chunks/0?configuration=ЗарплатаИУправлениеПерсоналомКОРП"

# chunk 1+ — реквизиты шапки (разбиты по размеру)
curl -s "$API/objects/Document/Отпуск/chunks/1?configuration=ЗарплатаИУправлениеПерсоналомКОРП"
```

## Полный текст в search

```bash
curl -s -X POST "$API/search" \
  -H "Content-Type: application/json" \
  -d '{"query":"отпуск","top_k":3,"full":true,"configuration":"ЗарплатаИУправлениеПерсоналомКОРП"}'
```

## Список конфигураций

```bash
curl -s "$API/configurations"
```

## Поиск объекта по имени (SQLite)

```bash
curl -s "$API/objects?q=Отпуск&object_type=Document&configuration=ЗарплатаИУправлениеПерсоналомКОРП"
```

## RAG-ответ (если LLM включён на сервере)

```bash
curl -s -X POST "$API/query" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "Какие обязательные реквизиты у документа Отпуск?",
    "top_k": 5,
    "configuration": "ЗарплатаИУправлениеПерсоналомКОРП"
  }'
```

## PowerShell (Invoke-RestMethod)

```powershell
$api = $env:CONF_DOC_API_URL
$body = @{
  query = "отпуск"
  top_k = 5
  configuration = "ЗарплатаИУправлениеПерсоналомКОРП"
} | ConvertTo-Json
Invoke-RestMethod -Uri "$api/search" -Method Post -Body $body -ContentType "application/json; charset=utf-8"
```
