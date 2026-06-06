"""Search result ranking helpers."""

from __future__ import annotations

# Prefer primary metadata types when query matches object name exactly.
OBJECT_TYPE_PRIORITY: dict[str, int] = {
    "Document": 0,
    "Catalog": 1,
    "Report": 2,
    "DataProcessor": 3,
    "InformationRegister": 4,
    "AccumulationRegister": 5,
    "CommonModule": 6,
}


def query_match_strength(query: str, name: str, synonym: str | None) -> float:
    """Return boost for exact name/synonym match (0 = no match)."""
    q = query.strip().casefold()
    if not q:
        return 0.0
    name_cf = name.casefold()
    syn_cf = (synonym or "").casefold()
    if q in (name_cf, syn_cf):
        return 0.25
    return 0.0


def object_type_rank(object_type: str) -> int:
    return OBJECT_TYPE_PRIORITY.get(object_type, 50)


def hit_score(hit: dict[str, object], default: float = 0.0) -> float:
    value = hit.get("score", default)
    if isinstance(value, int | float):
        return float(value)
    return default


def apply_name_match_boost(
    hits: list[dict[str, object]],
    query: str,
    extra_hits: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Merge lexical name matches and boost scores for exact matches."""
    if not extra_hits:
        return hits

    merged = list(hits)
    by_key = {(h.get("object_type"), h.get("name")): h for h in merged}
    max_score = max((hit_score(h) for h in merged), default=0.0)

    for hit in extra_hits:
        key = (hit.get("object_type"), hit.get("name"))
        strength = hit.get("_match_strength", 0)
        strength_f = float(strength) if isinstance(strength, int | float) else 0.0
        if strength_f <= 0:
            continue
        boosted = max(hit_score(hit), max_score + 0.05) + strength_f
        hit = {**hit, "score": boosted}
        hit.pop("_match_strength", None)

        existing = by_key.get(key)
        if existing is None:
            merged.append(hit)
            by_key[key] = hit
        else:
            existing["score"] = max(hit_score(existing), boosted)
            if hit.get("chunk_index") == 0 and existing.get("chunk_index") != 0:
                existing.update(hit)

    return merged
