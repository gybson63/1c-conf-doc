"""Configuration name matching (homoglyphs, CLI typos)."""

from __future__ import annotations

import difflib

# Latin letters that look like Cyrillic in config names typed on wrong keyboard.
_LATIN_TO_CYRILLIC = str.maketrans(
    {
        "A": "А",
        "a": "а",
        "B": "В",
        "b": "б",
        "C": "С",
        "c": "с",
        "E": "Е",
        "e": "е",
        "H": "Н",
        "h": "н",
        "K": "К",
        "k": "к",
        "L": "Л",
        "l": "л",
        "M": "М",
        "m": "м",
        "O": "О",
        "o": "о",
        "P": "Р",
        "p": "р",
        "T": "Т",
        "t": "т",
        "X": "Х",
        "x": "х",
        "Y": "У",
        "y": "у",
    }
)


def normalize_configuration_name(name: str) -> str:
    return name.translate(_LATIN_TO_CYRILLIC)


def match_configuration_name(requested: str, candidates: list[str]) -> str | None:
    if not requested or not candidates:
        return None
    if requested in candidates:
        return requested

    normalized = normalize_configuration_name(requested)
    if normalized in candidates:
        return normalized

    for candidate in candidates:
        if candidate.casefold() == requested.casefold():
            return candidate
        if candidate.casefold() == normalized.casefold():
            return candidate

    close = difflib.get_close_matches(normalized, candidates, n=1, cutoff=0.92)
    return close[0] if close else None


def configuration_not_found_message(requested: str, candidates: list[str]) -> str:
    hint = ""
    matched = match_configuration_name(requested, candidates)
    if matched and matched != requested:
        hint = f" Возможно, имелось в виду: {matched}."
    elif candidates:
        available = ", ".join(candidates)
        hint = f" Доступно: {available}."
    return (
        f"Configuration '{requested}' not found in database.{hint} "
        "Скопируйте имя из conf-doc configurations или задайте configuration: в config.yaml."
    )
