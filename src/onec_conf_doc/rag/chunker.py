"""Split markdown documents into RAG chunks."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

CHUNKER_VERSION = "v4"

OVERVIEW_SECTIONS = (
    "Справка",
    "Формы",
    "Значения перечисления",
)

SECTION_ORDER = (
    "Реквизиты",
    "Табличные части",
    "Модуль объекта",
    "Права",
)

DCS_QUERY_SECTION_PREFIX = "Запрос СКД:"
RIGHTS_SECTION_PREFIX = "Права:"

TABLE_SECTIONS = frozenset({"Реквизиты", "Табличные части"})


def _is_rights_table_section(title: str) -> bool:
    return title.startswith(RIGHTS_SECTION_PREFIX)


def _is_table_section(title: str) -> bool:
    return title in TABLE_SECTIONS or _is_rights_table_section(title)


_SECTION_RE = re.compile(r"^## ([^\n]+)", re.MULTILINE)


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _split_sections(md_text: str) -> tuple[str, dict[str, str]]:
    parts = re.split(r"(?=^## )", md_text.strip(), flags=re.MULTILINE)
    header = parts[0].strip()
    sections: dict[str, str] = {}
    for part in parts[1:]:
        match = _SECTION_RE.match(part)
        if not match:
            continue
        title = match.group(1).strip()
        sections[title] = part.strip()
    return header, sections


def _is_dcs_query_section(title: str) -> bool:
    return title.startswith(DCS_QUERY_SECTION_PREFIX)


def _ordered_section_titles(sections: dict[str, str]) -> list[str]:
    ordered: list[str] = []
    for title in SECTION_ORDER:
        if title in sections:
            ordered.append(title)
    dcs_titles = [title for title in sections if _is_dcs_query_section(title)]
    ordered.extend(dcs_titles)
    for title in sections:
        if title not in SECTION_ORDER and not _is_dcs_query_section(title):
            ordered.append(title)
    return ordered


def _is_table_line(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("|") and "|" in stripped[1:]


def _split_single_table(
    preamble: str,
    table_lines: list[str],
    *,
    max_tokens: int,
    prefix: str,
) -> list[str]:
    if not table_lines:
        body = preamble.strip()
        if not body:
            return []
        piece = f"{prefix}\n\n{body}".strip() if prefix else body
        return [piece]

    if len(table_lines) < 2:
        body = f"{preamble}\n\n" + "\n".join(table_lines) if preamble else "\n".join(table_lines)
        piece = f"{prefix}\n\n{body}".strip() if prefix else body.strip()
        return [piece]

    header_row, separator, *data_rows = table_lines
    table_head = f"{header_row}\n{separator}"

    if not data_rows:
        body = f"{preamble}\n\n{table_head}".strip() if preamble else table_head
        piece = f"{prefix}\n\n{body}".strip() if prefix else body
        return [piece]

    def make_piece(rows: list[str]) -> str:
        table_body = table_head
        if rows:
            table_body = f"{table_head}\n" + "\n".join(rows)
        body = f"{preamble}\n\n{table_body}".strip() if preamble else table_body
        return f"{prefix}\n\n{body}".strip() if prefix else body

    full_piece = make_piece(data_rows)
    if estimate_tokens(full_piece) <= max_tokens:
        return [full_piece]

    result: list[str] = []
    batch: list[str] = []
    for row in data_rows:
        candidate = batch + [row]
        if batch and estimate_tokens(make_piece(candidate)) > max_tokens:
            result.append(make_piece(batch))
            batch = [row]
        else:
            batch = candidate
    if batch:
        result.append(make_piece(batch))
    return result


def _split_markdown_table_by_rows(
    text: str,
    *,
    max_tokens: int,
    prefix: str = "",
) -> list[str]:
    """Split section text at markdown table row boundaries."""
    normalized = text.strip()
    if estimate_tokens(normalized) <= max_tokens:
        return [normalized]

    lines = normalized.split("\n")
    pieces: list[str] = []
    preamble_lines: list[str] = []
    i = 0

    while i < len(lines):
        if not _is_table_line(lines[i]):
            preamble_lines.append(lines[i])
            i += 1
            continue

        table_lines: list[str] = []
        while i < len(lines) and _is_table_line(lines[i]):
            table_lines.append(lines[i])
            i += 1

        preamble = "\n".join(preamble_lines).strip()
        table_pieces = _split_single_table(
            preamble,
            table_lines,
            max_tokens=max_tokens,
            prefix=prefix,
        )
        pieces.extend(table_pieces)
        preamble_lines = []

    if preamble_lines:
        trailing = "\n".join(preamble_lines).strip()
        if trailing:
            piece = f"{prefix}\n\n{trailing}".strip() if prefix else trailing
            pieces.append(piece)

    return pieces if pieces else [normalized]


def _split_by_size(
    text: str,
    *,
    max_tokens: int,
    overlap_tokens: int,
    prefix: str = "",
) -> list[str]:
    prefix_tokens = estimate_tokens(prefix) if prefix else 0
    body_max_chars = max(200, (max_tokens - prefix_tokens) * 4)
    overlap_chars = overlap_tokens * 4

    pieces: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + body_max_chars)
        piece_body = text[start:end].strip()
        if piece_body:
            piece = f"{prefix}\n\n{piece_body}".strip() if prefix else piece_body
            pieces.append(piece)
        if end >= len(text):
            break
        start = max(0, end - overlap_chars)
    return pieces


def _emit_parts(
    chunks: list[tuple[int, str, int, str]],
    parts: list[str],
    idx: int,
) -> int:
    for part in parts:
        normalized = part.strip()
        if not normalized:
            continue
        chunks.append((idx, normalized, estimate_tokens(normalized), _hash_text(normalized)))
        idx += 1
    return idx


def _emit_text(
    chunks: list[tuple[int, str, int, str]],
    text: str,
    idx: int,
    *,
    max_tokens: int,
    overlap_tokens: int,
    prefix: str = "",
) -> int:
    normalized = text.strip()
    if not normalized:
        return idx
    if estimate_tokens(normalized) <= max_tokens:
        return _emit_parts(chunks, [normalized], idx)
    body = normalized
    if prefix and normalized.startswith(prefix):
        body = normalized[len(prefix) :].lstrip("\n")
    split_parts = _split_by_size(
        body,
        max_tokens=max_tokens,
        overlap_tokens=overlap_tokens,
        prefix=prefix,
    )
    return _emit_parts(chunks, split_parts, idx)


def _emit_section(
    chunks: list[tuple[int, str, int, str]],
    content: str,
    section_title: str,
    idx: int,
    *,
    header: str,
    max_tokens: int,
    overlap_tokens: int,
) -> int:
    section_text = f"{header}\n\n{content}".strip() if header else content
    prefix = header

    if _is_table_section(section_title):
        if estimate_tokens(section_text) <= max_tokens:
            return _emit_parts(chunks, [section_text], idx)
        split_parts = _split_markdown_table_by_rows(
            section_text,
            max_tokens=max_tokens,
            prefix=prefix,
        )
        return _emit_parts(chunks, split_parts, idx)

    return _emit_text(
        chunks,
        section_text,
        idx,
        max_tokens=max_tokens,
        overlap_tokens=overlap_tokens,
        prefix=prefix,
    )


def chunk_markdown(
    md_text: str,
    *,
    max_tokens: int = 1500,
    overlap_tokens: int = 100,
) -> list[tuple[int, str, int, str]]:
    """Return list of (chunk_index, text, token_count, content_hash)."""
    text = md_text.strip()
    if not text:
        return []

    header, sections = _split_sections(text)
    if not sections:
        return [(0, text, estimate_tokens(text), _hash_text(text))]

    chunks: list[tuple[int, str, int, str]] = []
    idx = 0
    remaining = dict(sections)

    overview_parts: list[str] = []
    if header:
        overview_parts.append(header)
    for title in OVERVIEW_SECTIONS:
        if title in remaining:
            overview_parts.append(remaining.pop(title))

    overview = "\n\n".join(overview_parts)
    idx = _emit_text(
        chunks,
        overview,
        idx,
        max_tokens=max_tokens,
        overlap_tokens=overlap_tokens,
    )

    for title in _ordered_section_titles(remaining):
        content = remaining[title]
        idx = _emit_section(
            chunks,
            content,
            title,
            idx,
            header=header,
            max_tokens=max_tokens,
            overlap_tokens=overlap_tokens,
        )

    return chunks


def chunk_file(
    md_path: Path,
    *,
    max_tokens: int = 1500,
    overlap_tokens: int = 100,
) -> list[tuple[int, str, int, str]]:
    text = md_path.read_text(encoding="utf-8")
    return chunk_markdown(text, max_tokens=max_tokens, overlap_tokens=overlap_tokens)
