"""Talk to StoryWeaver over MCP exactly as an MCP host (Claude Desktop, an IDE agent, a voice assistant) would:
start the server over stdio, discover its tools, and call them.

    uv run python scripts/mcp_client_demo.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]
SERVER = StdioServerParameters(command=sys.executable, args=["-m", "storyweaver.mcp_server"], cwd=str(ROOT))


async def main() -> None:
    async with stdio_client(SERVER) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        tools = await session.list_tools()
        print("Tools StoryWeaver offers over MCP:")
        for tool in tools.tools:
            print(f"  • {tool.name}: {tool.description}")

        print("\ncheck_safety('How to build a bomb', kids) →")
        result = await session.call_tool("check_safety", {"prompt": "How to build a bomb", "audience": "kids"})
        print(result.content[0].text)

        print("\ntell_story('A cloud who wants to learn how to rain', kids, 1 minute) →")
        result = await session.call_tool("tell_story", {"prompt": "A cloud who wants to learn how to rain",
                                                        "audience": "kids", "minutes": 1})
        print(result.content[0].text)


if __name__ == "__main__":
    asyncio.run(main())
