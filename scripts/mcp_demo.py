"""Single MCP tool call demo with UTF-8 output."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
CONF_DOC = ROOT / ".venv" / "Scripts" / "conf-doc.exe"


async def main() -> None:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    api_url = "http://127.0.0.1:8000"
    configuration = "ТестоваяКонфигурация"

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

    async with stdio_client(server_params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        result = await session.call_tool(
            "conf_doc_search",
            {"query": "номенклатура", "top_k": 2, "full": True},
        )
        for block in result.content:
            text = getattr(block, "text", None)
            if text:
                print(json.dumps(json.loads(text), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
