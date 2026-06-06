from onec_conf_doc.config_names import (
    configuration_not_found_message,
    match_configuration_name,
    normalize_configuration_name,
)


def test_normalize_latin_homoglyphs_in_configuration_name() -> None:
    wrong = "ЗарплатаИУправлениеПерсон" + "al" + "омКОРП"
    right = "ЗарплатаИУправлениеПерсоналомКОРП"
    assert normalize_configuration_name(wrong) == right


def test_match_configuration_name_with_homoglyphs() -> None:
    candidates = ["ЗарплатаИУправлениеПерсоналомКОРП"]
    wrong = "ЗарплатаИУправлениеПерсон" + "al" + "омКОРП"
    assert match_configuration_name(wrong, candidates) == candidates[0]


def test_configuration_not_found_message_suggests_match() -> None:
    candidates = ["ЗарплатаИУправлениеПерсоналомКОРП"]
    wrong = "ЗарплатаИУправлениеПерсон" + "al" + "омКОРП"
    msg = configuration_not_found_message(wrong, candidates)
    assert "ЗарплатаИУправлениеПерсоналомКОРП" in msg
