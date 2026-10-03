"""Starts mcp_server.py over stdio, lists its tool and calls it. Prints `mcp ok: 5` on success."""

import asyncio
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main() -> None:
    params = StdioServerParameters(command=sys.executable, args=[str(Path(__file__).with_name("mcp_server.py"))])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            assert [t.name for t in tools.tools] == ["add"], tools
            result = await session.call_tool("add", {"a": 2, "b": 3})
            text = result.content[0].text
            assert text == "5", text
            print("mcp ok:", text)


asyncio.run(main())
