"""List MCP tools — connects to the running server and shows all available tools.

Uses the MCP client library to connect via SSE.

Usage:
    # Terminal 1 — start server:
    uv run python -m core.main

    # Terminal 2 — list tools:
    uv run python scripts/mcp_list_tools.py
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from mcp import types
from mcp.client.sse import sse_client


async def main() -> None:
    parser = argparse.ArgumentParser(description="List MCP server tools")
    parser.add_argument(
        "--url",
        default="http://localhost:8000/mcp/sse",
        help="MCP SSE URL (default: http://localhost:8000/mcp/sse)",
    )
    parser.add_argument(
        "--format",
        choices=["human", "raw"],
        default="raw",
        help="Output format: human, raw (full JSON schema, default)",
    )
    args = parser.parse_args()

    print(f"Connecting to {args.url}...", file=sys.stderr)

    try:
        async with sse_client(url=args.url) as (read, write):
            # Initialize
            init_params = types.InitializeRequestParams(
                protocolVersion=types.LATEST_PROTOCOL_VERSION,
                capabilities=types.ClientCapabilities(),
                clientInfo=types.Implementation(
                    name="mcp-list-tools",
                    version="1.0.0",
                ),
            ).model_dump(mode="json")
            init_request = types.JSONRPCRequest(
                jsonrpc="2.0",
                id="1",
                method="initialize",
                params=init_params,
            )
            await write.send(init_request.model_dump(by_alias=True, mode="json"))
            await read.receive()  # init response
            print("Connected.", file=sys.stderr)

            # Send initialized notification
            initialized = types.JSONRPCNotification(
                jsonrpc="2.0",
                method="notifications/initialized",
            )
            await write.send(initialized.model_dump(by_alias=True, mode="json"))

            # List tools
            list_request = types.JSONRPCRequest(
                jsonrpc="2.0",
                id="2",
                method="tools/list",
                params=types.PaginatedRequestParams().model_dump(mode="json"),
            )
            await write.send(list_request.model_dump(by_alias=True, mode="json"))
            raw_msg = await read.receive()
            # SessionMessage.message is a JSONRPCMessage with .root or .model_dump()
            if hasattr(raw_msg, "message"):
                list_response = raw_msg.message.model_dump(mode="json")
            else:
                list_response = raw_msg

            if args.format == "raw":
                print(json.dumps(list_response, indent=2, ensure_ascii=False))
                return

            tools_data = list_response.get("result", {}).get("tools", [])
            if not tools_data:
                print("No tools found.")
                return

            print(f"\n{'=' * 60}")
            print(f"  MCP Server Tools ({len(tools_data)} total)")
            print(f"{'=' * 60}\n")

            for i, tool in enumerate(tools_data, 1):
                name = tool.get("name", "unknown")
                description = tool.get("description", "")
                input_schema = tool.get("inputSchema", {})
                properties = input_schema.get("properties", {})
                required = input_schema.get("required", [])

                print(f"  [{i}] {name}")
                print(f"      Description: {description}")

                if properties:
                    print("      Parameters:")
                    for param_name, param_info in properties.items():
                        param_type = param_info.get("type", "any")
                        param_desc = param_info.get("description", "")
                        required_mark = " *required" if param_name in required else ""
                        print(f"        - {param_name}: {param_type}{required_mark}")
                        if param_desc:
                            print(f"          {param_desc}")
                print()

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        print(
            "Make sure the server is running: uv run python -m core.main",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
