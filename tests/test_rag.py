from onec_conf_doc.rag.chunker import chunk_markdown, estimate_tokens


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
