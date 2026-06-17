"""Quick smoke test for role rights search."""

from __future__ import annotations

import json
import urllib.request

BASE = "http://127.0.0.1:8000"


def search(query: str, object_type: str | None = None, top_k: int = 5) -> list[dict]:
    body: dict = {"query": query, "top_k": top_k}
    if object_type:
        body["object_type"] = object_type
    req = urllib.request.Request(
        f"{BASE}/search",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read())


def main() -> None:
    queries = [
        ("права на справочник Сотрудники", "Role"),
        ("Catalog.Сотрудники Read View", "Role"),
        ("ExchangeATS WebService Use", "Role"),
    ]
    for query, obj_type in queries:
        print(f"\n=== {query!r} (type={obj_type}) ===")
        hits = search(query, obj_type, top_k=3)
        for hit in hits:
            text = hit.get("text", "").replace("\n", " ")[:150]
            print(f"  {hit.get('score', 0):.3f} | {hit.get('name')} | {text}")


if __name__ == "__main__":
    main()
