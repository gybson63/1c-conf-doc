"""Progress bar helpers for long-running indexing tasks."""

from __future__ import annotations

import sys
from collections.abc import Iterable, Iterator
from typing import TypeVar

T = TypeVar("T")


def use_progress(show_progress: bool | None) -> bool:
    if show_progress is None:
        return sys.stderr.isatty()
    return show_progress


def iter_progress(
    iterable: Iterable[T],
    *,
    total: int | None = None,
    desc: str = "",
    unit: str = "it",
    disable: bool = False,
) -> Iterator[T]:
    if disable:
        yield from iterable
        return
    from tqdm import tqdm

    yield from tqdm(iterable, total=total, desc=desc, unit=unit, file=sys.stderr)
