from pathlib import Path

from onec_conf_doc.markdown.generator import generate_markdown
from onec_conf_doc.parser.xml_parser import parse_metadata_file
from onec_conf_doc.rag.chunker import chunk_markdown, estimate_tokens

FIXTURES = Path(__file__).parent / "fixtures" / "export_minimal"


def test_estimate_tokens() -> None:
    assert estimate_tokens("abcd") >= 1


def test_chunk_markdown_overview_includes_help() -> None:
    text = """# Документ: Отпуск

**Синоним:** Отпуск
**Тип:** Document

## Реквизиты

| Имя | Тип |
|-----|-----|
| Организация | ref |

## Формы

- ФормаДокумента

## Справка

Документ предназначен для регистрации отпусков.
"""
    chunks = chunk_markdown(text, max_tokens=1500)
    assert len(chunks) >= 2
    overview = chunks[0][1]
    assert "Отпуск" in overview
    assert "предназначен" in overview
    assert "## Реквизиты" not in overview


def test_chunk_markdown_no_header_only() -> None:
    header = "# Документ: X\n\n**Синоним:** X\n"
    requisites = "## Реквизиты\n\n" + "| Имя | Тип |\n|-----|-----|\n" + "| a | b |\n" * 800
    text = f"{header}\n{requisites}\n\n## Справка\n\nОписание документа."
    chunks = chunk_markdown(text, max_tokens=200)
    for _idx, chunk_text, _tokens, _hash in chunks:
        assert chunk_text != header.strip()
        assert len(chunk_text) > len(header) + 20


def test_chunk_markdown_splits_sections() -> None:
    text = "# Title\n\nIntro.\n\n## Section A\n\n" + ("word " * 800) + "\n\n## Section B\n\nTail."
    chunks = chunk_markdown(text, max_tokens=200)
    assert len(chunks) >= 2


def test_chunk_markdown_requisites_at_index_one() -> None:
    text = """# Справочник: Номенклатура

**Синоним:** Номенклатура
**Тип:** Catalog

## Реквизиты

| Имя | Тип | Синоним | Комментарий | Обязательный |
|-----|-----|---------|-------------|--------------|
| Артикул | xs:string | Артикул | Код | Да |

## Формы

- ФормаЭлемента

## Справка

Описание справочника.
"""
    chunks = chunk_markdown(text, max_tokens=1500)
    assert len(chunks) >= 2
    assert "## Реквизиты" in chunks[1][1]
    assert "Артикул" in chunks[1][1]


def test_chunk_markdown_splits_requisites_table_by_rows() -> None:
    header = "# Справочник: Big\n\n**Тип:** Catalog\n"
    rows = "\n".join(f"| attr{i} | xs:string | | | |" for i in range(120))
    text = (
        f"{header}\n## Реквизиты\n\n"
        "| Имя | Тип | Синоним | Комментарий | Обязательный |\n"
        "|-----|-----|---------|-------------|--------------|\n"
        f"{rows}\n\n## Справка\n\nОписание."
    )
    chunks = chunk_markdown(text, max_tokens=200)
    requisites_chunks = [c for c in chunks if "## Реквизиты" in c[1]]
    assert len(requisites_chunks) >= 2
    for _idx, chunk_text, _tokens, _hash in requisites_chunks:
        assert "| Имя | Тип |" in chunk_text
        assert "|-----|-----|" in chunk_text
        assert "attr0" in requisites_chunks[0][1]


def test_chunk_markdown_role_rights_sections() -> None:
    path = FIXTURES / "Roles" / "ТестоваяРоль.xml"
    obj = parse_metadata_file(path, "Role", source_root=FIXTURES)
    text = generate_markdown(obj)
    chunks = chunk_markdown(text, max_tokens=1500)

    overview = chunks[0][1]
    assert "Тестовая роль" in overview
    assert "## Права: Catalog" not in overview

    catalog_chunks = [c for c in chunks if "## Права: Catalog" in c[1]]
    assert len(catalog_chunks) == 1
    assert "Номенклатура" in catalog_chunks[0][1]
    assert "Read, View" in catalog_chunks[0][1]

    document_chunks = [c for c in chunks if "## Права: Document" in c[1]]
    assert len(document_chunks) == 1
    assert "ТекущийСотрудник" in document_chunks[0][1]


def test_chunk_markdown_splits_role_rights_table_by_rows() -> None:
    header = "# Роль: BigRole\n\n**Тип:** Role\n"
    rows = "\n".join(f"| Object{i} | Read, View | |" for i in range(120))
    text = (
        f"{header}\n## Права\n\n**Объектов с правами:** 120  \n\n"
        f"## Права: Catalog\n\n"
        "| Объект | Права | RLS |\n"
        "|--------|-------|-----|\n"
        f"{rows}\n"
    )
    chunks = chunk_markdown(text, max_tokens=200)
    rights_chunks = [c for c in chunks if "## Права: Catalog" in c[1]]
    assert len(rights_chunks) >= 2
    for _idx, chunk_text, _tokens, _hash in rights_chunks:
        assert "| Объект | Права |" in chunk_text


def test_chunk_markdown_report_dcs_query_separate_from_overview() -> None:
    path = FIXTURES / "Reports" / "ТестовыйОтчет.xml"
    obj = parse_metadata_file(path, "Report", source_root=FIXTURES)
    text = generate_markdown(obj)
    chunks = chunk_markdown(text, max_tokens=1500)

    overview = chunks[0][1]
    assert "Описание тестового отчёта" in overview or "Тестовый отчёт" in overview
    assert "Справочник.Номенклатура" not in overview
    assert "ПриКомпоновкеРезультата" not in overview

    dcs_chunks = [c for c in chunks if "Запрос СКД:" in c[1]]
    assert len(dcs_chunks) == 2
    assert any("Справочник.Номенклатура" in c[1] for c in dcs_chunks)
    assert any("Справочник.Контрагенты" in c[1] for c in dcs_chunks)

    module_chunks = [c for c in chunks if "## Модуль объекта" in c[1]]
    assert len(module_chunks) == 1
    assert "ПриКомпоновкеРезультата" in module_chunks[0][1]
