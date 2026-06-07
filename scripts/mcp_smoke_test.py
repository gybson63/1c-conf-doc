"""Smoke test MCP stdio server against running conf-doc API."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONF_DOC = ROOT / ".venv" / "Scripts" / "conf-doc.exe"


async def main() -> int:
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except ImportError:
        print("FAIL: install mcp — pip install -e '.[mcp]'")
        return 1

    api_url = os.environ.get("CONF_DOC_API_URL", "http://127.0.0.1:8000")
    configuration = os.environ.get("CONF_DOC_CONFIGURATION", "ТестоваяКонфигурация")

    server_params = StdioServerParameters(
        command=str(CONF_DOC),
        args=["mcp"],
        env={
            **os.environ,
            "CONF_DOC_API_URL": api_url,
            "CONF_DOC_CONFIGURATION": configuration,
            "PYTHONIOENCODING": "utf-8",
        },
    )

    print(f"API: {api_url}")
    print(f"Configuration: {configuration}")
    print(f"MCP command: {CONF_DOC} mcp\n")

    async with stdio_client(server_params) as (read, write), ClientSession(read, write) as session:
        init = await session.initialize()
        print(f"Initialized: {init.serverInfo.name if init.serverInfo else '1c-conf-doc'}")

        tools = await session.list_tools()
        tool_names = sorted(t.name for t in tools.tools)
        print(f"Tools ({len(tool_names)}): {', '.join(tool_names)}\n")

        async def call(name: str, arguments: dict | None = None) -> None:
            print(f"=== {name} ===")
            result = await session.call_tool(name, arguments or {})
            for block in result.content:
                text = getattr(block, "text", None)
                if text:
                    try:
                        parsed = json.loads(text)
                        print(json.dumps(parsed, ensure_ascii=False, indent=2)[:2000])
                        if len(text) > 2000:
                            print("... (truncated)")
                    except json.JSONDecodeError:
                        print(text[:2000])
            print()

        await call("conf_doc_health")
        await call("conf_doc_list_configurations")
        await call(
            "conf_doc_search",
            {"query": "номенклатура", "top_k": 3},
        )
        await call(
            "conf_doc_get_object",
            {"object_type": "Catalog", "name": "Номенклатура"},
        )
        await call(
            "conf_doc_get_object_chunk",
            {
                "object_type": "Catalog",
                "name": "Номенклатура",
                "chunk_index": 0,
            },
        )
        await call(
            "conf_doc_query",
            {"question": "Что такое номенклатура?"},
        )

    print("MCP smoke test completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
