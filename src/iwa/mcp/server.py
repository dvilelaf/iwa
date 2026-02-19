"""MCP server entry point."""

import sys

from fastmcp import FastMCP

from iwa.mcp.tools import register_tools


def create_mcp_server() -> FastMCP:
    """Create and configure the MCP server with all tools."""
    mcp = FastMCP(
        "iwa",
        instructions=(
            "iwa is a blockchain wallet and interaction platform. "
            "Use the tools to query balances, send transactions, "
            "swap tokens, and manage wallet accounts on EVM chains. "
            "Amounts are in ether (human-readable), not wei. "
            "Default chain is 'gnosis'. Use account tags (e.g. 'master') "
            "or hex addresses."
        ),
    )
    register_tools(mcp)
    _register_plugin_tools(mcp)
    return mcp


def _register_plugin_tools(mcp: FastMCP) -> None:
    """Discover plugins and register their MCP tools."""
    from iwa.core.services.plugin import PluginService

    plugin_service = PluginService()
    for _name, plugin in plugin_service.get_all_plugins().items():
        plugin.register_mcp_tools(mcp)


def run_server(
    transport: str = "stdio",
    host: str = "127.0.0.1",
    port: int = 8000,
) -> None:
    """Run the MCP server with the specified transport."""
    mcp = create_mcp_server()
    mcp.run(transport=transport, host=host, port=port)


def main() -> None:
    """CLI entry point for iwa-mcp console script."""
    transport = "stdio"
    host = "127.0.0.1"
    port = 8000

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] in ("--transport", "-t") and i + 1 < len(args):
            transport = args[i + 1]
            i += 2
        elif args[i] in ("--host",) and i + 1 < len(args):
            host = args[i + 1]
            i += 2
        elif args[i] in ("--port", "-p") and i + 1 < len(args):
            port = int(args[i + 1])
            i += 2
        else:
            i += 1

    run_server(transport=transport, host=host, port=port)


if __name__ == "__main__":
    main()
