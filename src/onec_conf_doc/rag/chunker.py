"""Split markdown documents into RAG chunks."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

OVERVIEW_SECTIONS = (
    "Справка",
    "Формы",
    "Значения перечисления",
)

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

    for content in remaining.values():
        section_text = f"{header}\n\n{content}".strip() if header else content
        idx = _emit_text(
            chunks,
            section_text,
            idx,
            max_tokens=max_tokens,
            overlap_tokens=overlap_tokens,
            prefix=header,
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
