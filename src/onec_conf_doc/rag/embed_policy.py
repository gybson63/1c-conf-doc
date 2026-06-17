"""Which metadata object types are excluded from vector embedding."""

from __future__ import annotations

EMBED_EXCLUDED_OBJECT_TYPES: frozenset[str] = frozenset({"Role"})
