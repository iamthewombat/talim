"""Optional MCP stdio server registering Talim's tool wrappers (WP-27).

The actual MCP SDK is loaded lazily so the package stays importable on
machines that don't have it installed. The wrappers themselves live in
`talim.app.tools.wrappers` and are testable independently.
"""

from __future__ import annotations

import logging

from talim.app.tools import TOOLS, ToolContext

logger = logging.getLogger("talim.app.tools.server")


def list_tool_names() -> list[str]:
    """Return the registered tool names — used by tests and introspection."""
    return [name for name, _fn, _desc in TOOLS]


def run_stdio_server(ctx: ToolContext) -> None:  # pragma: no cover - network
    """Start an MCP stdio server. Requires the `mcp` python SDK."""
    try:
        from mcp.server import Server  # type: ignore
        from mcp.server.stdio import stdio_server  # type: ignore
    except ImportError as e:
        raise ImportError(
            "MCP server requires the `mcp` package. "
            "Install with: pip install mcp"
        ) from e

    server = Server("talim")
    for name, fn, description in TOOLS:
        def _handler(arguments: dict, _fn=fn) -> dict:
            return _fn(ctx, **(arguments or {}))

        server.add_tool(name=name, description=description, handler=_handler)

    import asyncio

    async def _main() -> None:
        async with stdio_server() as (read, write):
            await server.run(read, write)

    asyncio.run(_main())
