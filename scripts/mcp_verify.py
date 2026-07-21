"""MCP Server Verification Script.

Connects to a running ODL MCP server via SSE, lists available tools,
calls search_documents with various parameters, and reports pass/fail
for each test.

Usage:
    # Terminal 1 — start server:
    uv run python -m core.main

    # Terminal 2 — run verification:
    uv run python scripts/mcp_verify.py

    # With custom URL:
    uv run python scripts/mcp_verify.py --url http://localhost:8000/mcp
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import urllib.error
import urllib.request
from typing import Any

from mcp import types
from mcp.client.sse import sse_client

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PASS = "✅ PASS"
FAIL = "❌ FAIL"

_tests_run = 0
_tests_passed = 0
_tests_failed = 0


def _test(name: str, passed: bool, detail: str = "") -> None:
    global _tests_run, _tests_passed, _tests_failed
    _tests_run += 1
    if passed:
        _tests_passed += 1
        print(f"  {PASS}  {name}")
    else:
        _tests_failed += 1
        print(f"  {FAIL}  {name}")
    if detail:
        for line in detail.strip().split("\n"):
            print(f"         {line}")


def _check_server_alive(url: str) -> bool:
    """Check if the HTTP server is reachable (quick connectivity test)."""
    base_url = url.replace("/mcp", "").replace("/sse", "")
    health_url = f"{base_url}/health"
    try:
        resp = urllib.request.urlopen(health_url, timeout=3)
        return resp.status == 200  # type: ignore[no-any-return]
    except (urllib.error.URLError, urllib.error.HTTPError, OSError):
        # Maybe /health is not available externally, try the base URL
        try:
            resp = urllib.request.urlopen(base_url, timeout=3)
            return resp.status in (200, 404)
        except (urllib.error.URLError, OSError):
            return False


async def _read_response(read: Any, timeout: float = 10.0) -> dict[str, Any]:
    """Read a single JSON-RPC response from the SSE stream with timeout."""

    raw: Any = await asyncio.wait_for(read.receive(), timeout=timeout)
    if hasattr(raw, "message"):
        return raw.message.model_dump(mode="json")  # type: ignore[no-any-return]
    return raw  # type: ignore[no-any-return]


async def _send_request(write: Any, request: dict[str, Any]) -> None:
    """Send a JSON-RPC request."""
    await write.send(request)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def _run_tests(url: str) -> None:
    """Run all verification tests against the MCP SSE endpoint."""
    async with sse_client(url=url) as (read, write):
        # Test 1: Connect and initialize
        print("  [1/5] Connect & Initialize ...")
        init_params = types.InitializeRequestParams(
            protocolVersion=types.LATEST_PROTOCOL_VERSION,
            capabilities=types.ClientCapabilities(),
            clientInfo=types.Implementation(
                name="mcp-verify",
                version="1.0.0",
            ),
        ).model_dump(mode="json")
        init_request = types.JSONRPCRequest(
            jsonrpc="2.0",
            id="1",
            method="initialize",
            params=init_params,
        )
        await _send_request(write, init_request.model_dump(by_alias=True, mode="json"))
        resp = await _read_response(read)
        ok = resp.get("result", {}).get("protocolVersion") is not None
        _test("Connect & Initialize", ok)

        if not ok:
            print("\n  ❌ Cannot initialize MCP session.")
            return

        # Send initialized notification
        initialized = types.JSONRPCNotification(
            jsonrpc="2.0",
            method="notifications/initialized",
        )
        await _send_request(write, initialized.model_dump(by_alias=True, mode="json"))

        # Test 2: List tools
        print("\n  [2/4] List tools ...")
        list_request = types.JSONRPCRequest(
            jsonrpc="2.0",
            id="2",
            method="tools/list",
            params=types.PaginatedRequestParams().model_dump(mode="json"),
        )
        await _send_request(write, list_request.model_dump(by_alias=True, mode="json"))
        resp = await _read_response(read)
        tools = resp.get("result", {}).get("tools", [])
        tool_names = {t["name"] for t in tools}
        expected = {"search_documents", "get_document_detail"}
        missing = expected - tool_names
        ok = not missing
        detail = f"Found {len(tools)} tool(s): {list(tool_names)}"
        if missing:
            detail += f"\nMissing: {missing}"
        _test("List tools (search_documents + get_document_detail)", ok, detail)

        # Test 3: Minimal search
        print("\n  [3/4] Search (minimal params) ...")
        search_request = types.JSONRPCRequest(
            jsonrpc="2.0",
            id="3",
            method="tools/call",
            params=types.CallToolRequestParams(
                name="search_documents",
                arguments={"query": "государственные пособия"},
            ).model_dump(mode="json"),
        )
        await _send_request(write, search_request.model_dump(by_alias=True, mode="json"))
        resp = await _read_response(read)
        result = resp.get("result", {})
        content = result.get("content", [])
        is_error = result.get("isError", False)
        if is_error:
            error_text = content[0].get("text", "") if content else "unknown error"
            _test("Search with query only", False, f"Error: {error_text}")
        else:
            _test("Search with query only", True)

        # Test 4: Search with all valid params
        print("\n  [4/4] Search (all valid params) ...")
        search_request = types.JSONRPCRequest(
            jsonrpc="2.0",
            id="4",
            method="tools/call",
            params=types.CallToolRequestParams(
                name="search_documents",
                arguments={
                    "query": "пособия",
                    "offset": 0,
                    "max_results": 5,
                    "region": "Московская область",
                    "organization": ["Минтруд"],
                    "max_age_days": 365,
                },
            ).model_dump(mode="json"),
        )
        await _send_request(write, search_request.model_dump(by_alias=True, mode="json"))
        resp = await _read_response(read)
        result = resp.get("result", {})
        content = result.get("content", [])
        is_error = result.get("isError", False)
        if is_error:
            error_text = content[0].get("text", "") if content else "unknown error"
            _test("Search with region, org, max_age_days", False, f"Error: {error_text}")
        else:
            _test("Search with region, org, max_age_days", True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> None:
    parser = argparse.ArgumentParser(description="Verify MCP server functionality")
    parser.add_argument(
        "--url",
        default="http://localhost:8000/mcp/sse",
        help="MCP SSE URL (default: http://localhost:8000/mcp/sse)",
    )
    args = parser.parse_args()

    print(f"\n{'=' * 60}")
    print("  MCP Server Verification")
    print(f"  Target: {args.url}")
    print(f"{'=' * 60}\n")

    # First check if server is running (quick HTTP test)
    print("  [0/5] Checking server availability ...")
    if not _check_server_alive(args.url):
        print(f"  {FAIL}  Server not reachable at {args.url}")
        print("\n  ❌ Make sure the server is running:")
        print(f"     cd {__import__('os').getcwd()}")
        print("     uv run python -m core.main")
        print()
        sys.exit(1)
    print(f"  {PASS}  Server is reachable\n")

    # Run tests
    try:
        await _run_tests(args.url)
    except Exception as e:
        print(f"\n  {FAIL}  Fatal error during MCP session: {e}")
        print("         The server may have disconnected or encountered an error.")
        print("         Check the server logs for details.")

    # Summary
    print(f"\n{'=' * 60}")
    print(f"  Results: {_tests_passed}/{_tests_run} passed, {_tests_failed} failed")
    print(f"{'=' * 60}\n")

    if _tests_failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
