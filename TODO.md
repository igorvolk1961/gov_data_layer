# TODO

## Health endpoint issues

### 1. Redis shows "unavailable" despite being up in Docker

**Root cause:** [`CacheClient`](core/cache/__init__.py) uses lazy connection — `_available` is initialized to `False` and only set to `True` after the first successful `ping()` in `_connect()`. Since no cache operation (get/set) has been performed by the time `/health` is called, `cache.available` remains `False`.

**Fix needed:** In the `/health` endpoint ([`core/api/rest_server.py:154`](core/api/rest_server.py:154)), actively attempt to connect to Redis (call `cache._connect()` or a new `cache.ping()` method) instead of relying on the passive `available` flag.

### 2. LangFuse shows "unavailable" despite being up in Docker

**Root cause:** Either:
- The tracer was initialized as [`FileFallbackTracer`](core/observability/tracer.py:363) (LangFuse API keys not set or invalid), so `check_health()` always returns `False`
- OR [`LangFuseTracer.check_health()`](core/observability/tracer.py:298) calls `_verify_connection()` → `auth_check()`, but the `langfuse_host` in config points to a URL not reachable from the container network

**Fix needed:** Verify LangFuse configuration (`langfuse_host`, `public_key`, `secret_key`) and ensure the host URL is accessible from the application container.

### 3. Tracing middleware crashes on requests with query parameters

**Root cause:** In [`_TracingASGIMiddleware`](core/api/rest_server.py:76), `dict(scope.get("query_string", b"").decode())` fails when the query string contains parameters (e.g., `?parent_id=t1`), because `dict()` expects an iterable of key-value pairs, not a raw string.

**Fix needed:** Replace `dict(...)` with `dict(parse_qsl(scope.get("query_string", b"").decode()))` using `urllib.parse.parse_qsl`.

## MCP client script can't find MCP service

### 4. [`scripts/mcp_list_tools.py`](scripts/mcp_list_tools.py) fails to connect to the MCP SSE endpoint

**Symptoms:**
Running `uv run python scripts/mcp_list_tools.py` throws a connection error — the script cannot reach the MCP service at `http://localhost:8000/mcp`.

**Possible root causes:**
- The MCP server is created in [`create_mcp_server()`](core/api/mcp_server.py:31) and mounted as an SSE app under `/mcp` in [`core/main.py:183-184`](core/main.py:183-184). If the server isn't running (or started on a different host/port), the SSE client in [`mcp_list_tools.py`](scripts/mcp_list_tools.py:42) cannot connect.
- The [`mcp_server.sse_app(mount_path="/mcp")`](core/main.py:183) call generates an internal Starlette ASGI app, but the relationship between the `mount_path` parameter and the FastAPI `app.mount("/mcp", ...)` on the next line may conflict — the SSE endpoint might be served at a different path than expected.
- The `_TracingASGIMiddleware` in [`rest_server.py:54`](core/api/rest_server.py:54) skips tracing for `/mcp` paths, so a crash inside the SSE app would not be visible in traces.
- CORS or networking issues when connecting from the client process.

**Fix needed:**
Verify the actual URL path the SSE app listens on. Test with `curl -N http://localhost:8000/mcp` or a direct SSE client. Ensure the server is started before running the client script. If the `mount_path` in `sse_app()` and the `app.mount()` path disagree, align them.
