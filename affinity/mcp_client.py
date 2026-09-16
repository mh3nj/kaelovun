"""
mcp_client.py

Minimal stdlib-only client for Affinity's local MCP scripting server.

Transport: tries Streamable HTTP (POST {base}/mcp) first, then falls
back to legacy SSE (GET {base}/sse + POST the session endpoint).
No third-party dependencies — urllib + threads only, so the
PyInstaller bundle stays unchanged.

All tool calls are schema-driven: tools/list is inspected first, so
execute_script / render calls adapt to whatever parameter names the
running Affinity build uses instead of hardcoding them.
"""

import base64
import json
import queue
import socket
import threading
import time
import urllib.request
import urllib.error


PROTOCOL_VERSION = "2025-11-25"


class MCPError(RuntimeError):
    """Raised for any MCP transport or tool failure."""


class MCPClient:

    def __init__(self, base_url, logger=None, timeout=120):
        self.base_url = base_url.rstrip("/")
        self.logger = logger
        self.timeout = timeout
        self._request_id = 0
        self._id_lock = threading.Lock()
        self._tools_cache = None
        # Loopback must never go through a system/VPN proxy.
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        # One persistent SSE session: the server binds initialize to the
        # connection, so every call must reuse it (fresh connection per
        # call answers "Session not initialized").
        # RLock: _ensure_session calls _read_preamble while holding it,
        # which re-enters via call_tool. A plain Lock would deadlock.
        self._session_lock = threading.RLock()
        self._session_endpoint = None
        self._session_responses = None
        self._session_stop = None
        self._session_reader = None

    # ── logging ──

    def _log(self, message):
        if self.logger:
            self.logger.info(f"[mcp] {message}")

    # ── reachability ──

    def is_reachable(self, timeout=2) -> bool:
        """TCP probe — True when Affinity's MCP port accepts connections."""
        try:
            host, port = self._split_base()
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            return False

    def _split_base(self):
        without_scheme = self.base_url.split("://", 1)[-1].rstrip("/")
        if without_scheme.startswith("["):
            host, _, port = without_scheme[1:].partition("]:")
            return host, int(port) if port else 80
        if ":" in without_scheme:
            host, port = without_scheme.rsplit(":", 1)
            return host, int(port)
        return without_scheme, 80

    def _next_id(self) -> int:
        with self._id_lock:
            self._request_id += 1
            return self._request_id

    # ── low-level HTTP ──

    def _post_json(self, url, payload, accept):
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url, data=data,
            headers={"Content-Type": "application/json", "Accept": accept},
            method="POST",
        )
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                body = response.read()
                return response.headers.get_content_type(), body
        except urllib.error.HTTPError as error:
            raise MCPError(f"HTTP {error.code} from {url}: {error.read()[:300]!r}")

    # ── persistent SSE session ──

    def _reset_session(self):
        stop, reader = self._session_stop, self._session_reader
        self._session_endpoint = None
        self._session_responses = None
        self._session_stop = None
        self._session_reader = None
        if stop:
            stop.set()

    def _ensure_session(self):
        """Open one SSE connection and initialize it (idempotent)."""
        with self._session_lock:
            if (self._session_endpoint and self._session_reader
                    and self._session_reader.is_alive()):
                return
            self._reset_session()
            responses = queue.Queue()
            stop = threading.Event()
            reader = threading.Thread(
                target=self._sse_reader, args=(responses, stop), daemon=True
            )
            reader.start()
            self._session_responses = responses
            self._session_stop = stop
            self._session_reader = reader
            try:
                endpoint = self._wait_for_endpoint(responses)
                self._session_endpoint = endpoint
                init = self._post_session("initialize", {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "Kaelovun", "version": "1.3.1"},
                })
                try:
                    self._post_json(endpoint, {
                        "jsonrpc": "2.0", "method": "notifications/initialized",
                        "params": {},
                    }, "application/json, text/event-stream")
                except Exception:
                    pass
                self._log(f"MCP session ready: {init.get('serverInfo')}")
                self._read_preamble()
            except Exception:
                self._reset_session()
                raise

    def _post_session(self, method, params=None):
        payload = {"jsonrpc": "2.0", "id": self._next_id(),
                   "method": method, "params": params or {}}
        self._post_json(self._session_endpoint, payload,
                        "application/json, text/event-stream")
        return self._unwrap(self._wait_for_id(self._session_responses, payload["id"]),
                            payload["id"])

    def _read_preamble(self):
        """The server requires the 'preamble' doc before execute_script."""
        try:
            tools = self._post_session("tools/list", {}).get("tools", [])
            self._tools_cache = tools
            by_name = {t.get("name", ""): t for t in tools}
            # Exact read tool first — a loose "documentation" match would
            # grab the *list* tool and the preamble would never be read.
            read_tool = by_name.get("read_sdk_documentation_topic") or next(
                (t for t in tools
                 if "read" in t.get("name", "").lower()
                 and "document" in t.get("name", "").lower()),
                None,
            )
            if not read_tool:
                return
            filename = "preamble"
            list_tool = by_name.get("list_sdk_documentation")
            if list_tool:
                try:
                    parts = [i.get("text", "") for i in
                             self.call_tool(list_tool["name"], {})
                             if isinstance(i, dict)]
                    names = [n.strip() for n in " ".join(parts).replace(",", " ").split()]
                    hit = next((n for n in names if n.lower() == "preamble"), None)
                    if hit:
                        filename = hit
                except Exception:
                    pass
            args = self._fill_arguments(read_tool, {"filename": filename})
            self.call_tool(read_tool["name"], args)
            self._log("MCP preamble read.")
        except Exception as error:
            self._log(f"Preamble read skipped: {error}")

    def _rpc(self, method, params=None):
        self._ensure_session()
        try:
            return self._post_session(method, params)
        except MCPError as error:
            if "initialized" in str(error).lower() or "EOF" in str(error):
                self._log(f"Session dropped ({error}); re-establishing once.")
                with self._session_lock:
                    self._reset_session()
                self._ensure_session()
                return self._post_session(method, params)
            raise

    def _sse_reader(self, responses, stop):
        try:
            request = urllib.request.Request(
                self.base_url + "/sse",
                headers={"Accept": "text/event-stream"},
                method="GET",
            )
            with self._opener.open(request, timeout=self.timeout) as stream:
                event, data_lines = None, []
                while not stop.is_set():
                    line = stream.readline().decode("utf-8", "replace")
                    if not line:
                        break
                    line = line.rstrip("\r\n")
                    if line == "":
                        if event or data_lines:
                            responses.put((event, "\n".join(data_lines)))
                        event, data_lines = None, []
                    elif line.startswith("event:"):
                        event = line[6:].strip()
                    elif line.startswith("data:"):
                        data_lines.append(line[5:].strip())
        except Exception as error:
            responses.put(("error", str(error)))

    def _wait_for_endpoint(self, responses):
        deadline = time.time() + 15
        while time.time() < deadline:
            try:
                event, data = responses.get(timeout=1)
            except queue.Empty:
                continue
            if event == "endpoint":
                path = data.strip()
                if path.startswith("http"):
                    return path
                return self.base_url + path
            if event == "error":
                raise MCPError(f"SSE stream failed: {data}")
        raise MCPError("Timed out waiting for the MCP session endpoint.")

    def _wait_for_id(self, responses, request_id):
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            try:
                event, data = responses.get(timeout=1)
            except queue.Empty:
                continue
            if event == "error":
                raise MCPError(f"SSE stream failed: {data}")
            try:
                message = json.loads(data)
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(message, dict) and message.get("id") == request_id:
                return message
        raise MCPError(f"No MCP response for request {request_id}.")

    # ── shared ──

    @staticmethod
    def _unwrap(message, request_id):
        if not isinstance(message, dict):
            raise MCPError(f"Unexpected MCP response: {message!r}")
        if message.get("error"):
            raise MCPError(f"MCP error: {message['error']}")
        return message.get("result", {})

    # ── session ──

    def initialize(self):
        """Open (or reuse) the session. Returns the initialize result."""
        self._ensure_session()
        return {"session": self._session_endpoint}

    # ── tools ──

    def list_tools(self, refresh=False) -> list:
        if self._tools_cache is None or refresh:
            result = self._rpc("tools/list", {})
            self._tools_cache = result.get("tools", [])
        return self._tools_cache

    def _find_tool(self, *name_hints):
        tools = self.list_tools()
        lowered = {t.get("name", "").lower(): t for t in tools}
        for hint in name_hints:
            if hint.lower() in lowered:
                return lowered[hint.lower()]
        for name, tool in lowered.items():
            if any(h in name for h in name_hints):
                return tool
        available = ", ".join(lowered) or "(none)"
        raise MCPError(f"No tool matching {name_hints}. Available: {available}")

    @staticmethod
    def _fill_arguments(tool, payload):
        """Map payload values onto the tool's schema string properties."""
        schema = tool.get("inputSchema", {}) or {}
        props = schema.get("properties", {}) or {}
        required = set(schema.get("required", []) or [])
        args = {}
        remaining = dict(payload)
        for prop, spec in props.items():
            if prop in remaining:
                args[prop] = remaining.pop(prop)
        if remaining:
            string_props = [p for p, s in props.items()
                            if isinstance(s, dict) and s.get("type") == "string"
                            and p not in args]
            for value in remaining.values():
                if not string_props:
                    break
                args[string_props.pop(0)] = value
        for prop in required:
            if prop not in args:
                spec = props.get(prop, {})
                default = spec.get("default")
                if default is not None:
                    args[prop] = default
                elif spec.get("type") == "boolean":
                    args[prop] = False
                elif spec.get("type") in ("number", "integer"):
                    args[prop] = 0
                elif spec.get("type") == "array":
                    args[prop] = []
                elif spec.get("type") == "object":
                    args[prop] = {}
                else:
                    args[prop] = ""
        return args

    def call_tool(self, name, arguments=None) -> list:
        result = self._rpc("tools/call", {"name": name, "arguments": arguments or {}})
        return result.get("content", [])

    # ── high-level scripting primitives ──

    def execute_script(self, js_source) -> str:
        """Run SDK JavaScript in Affinity. Returns concatenated text output."""
        tool = self._find_tool("execute_script", "execute-script", "run_script", "eval")
        args = self._fill_arguments(tool, {"script": js_source})
        parts = []
        for item in self.call_tool(tool["name"], args):
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text":
                parts.append(item.get("text", ""))
            elif item.get("type") == "resource":
                resource = item.get("resource", {})
                text = resource.get("text", "")
                if text:
                    parts.append(text)
        output = "\n".join(parts)
        if "NOT_ALLOWED" in output:
            raise MCPError(
                "Affinity refused the script (NOT_ALLOWED). Enable the "
                "FileSystem permission in Affinity → Settings → MCP Server."
            )
        return output

    def render_spread(self, document_session_uuid, spread_index=0) -> tuple:
        """Render a spread to JPEG. Returns (mime, bytes).

        Affinity caps renders at 1024px on the long edge — plenty for
        naming previews and AVIFs, documented in docs/affinity-setup.md.
        """
        for item in self.call_tool("render_spread", {
            "document_session_uuid": document_session_uuid,
            "spread_index": spread_index,
        }):
            if not isinstance(item, dict):
                continue
            if item.get("type") == "image":
                return (item.get("mimeType", "image/jpeg"),
                        base64.b64decode(item.get("data", "")))
            if item.get("type") == "resource":
                resource = item.get("resource", {})
                blob = resource.get("blob")
                if blob:
                    return (resource.get("mimeType", "image/jpeg"),
                            base64.b64decode(blob))
        raise MCPError("Render tool returned no image data.")
