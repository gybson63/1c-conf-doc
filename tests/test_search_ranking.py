from onec_conf_doc.rag.search_ranking import (
    apply_name_match_boost,
    query_match_strength,
)


def test_query_match_strength_exact_name() -> None:
    assert query_match_strength("отпуск", "Отпуск", "Отпуск") == 0.25


def test_query_match_strength_no_match() -> None:
    assert query_match_strength("отпуск", "ЗаработанныеПраваНаОтпуска", "Права") == 0.0


def test_apply_name_match_boost_puts_exact_match_on_top() -> None:
    vector_hits = [
        {
            "object_type": "InformationRegister",
            "name": "ЗаработанныеПраваНаОтпуска",
            "score": 0.79,
            "chunk_index": 0,
        }
    ]
    lexical_hits = [
        {
            "object_type": "Document",
            "name": "Отпуск",
            "score": 0.0,
            "chunk_index": 0,
            "_match_strength": 0.25,
        }
    ]
    merged = apply_name_match_boost(vector_hits, "отпуск", lexical_hits)
    top = max(merged, key=lambda h: float(h["score"]))
    assert top["object_type"] == "Document"
    assert top["name"] == "Отпуск"
    assert float(top["score"]) > 0.9
