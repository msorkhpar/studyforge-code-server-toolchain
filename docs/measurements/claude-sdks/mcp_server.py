"""A one-tool MCP server over stdio, for the profile's offline proof."""

from mcp.server.mcpserver import MCPServer

server = MCPServer("proof")


@server.tool()
def add(a: int, b: int) -> int:
    """Add two integers."""
    return a + b


if __name__ == "__main__":
    server.run("stdio")
