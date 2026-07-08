"""
MCP (Model Context Protocol) Client — stdio transport

通过子进程与外部 MCP server 通信，动态发现和调用工具。
协议: JSON-RPC 2.0 over stdio

职责边界：
  mcp.py — 启动进程、协议通信、发现工具（纯数据返回，不碰 TOOLS）
  tools.py — 调用 get_mcp_tool_pool()，统一 extend TOOLS / update TOOLS_HANDLER
"""

import json
import subprocess
import threading
from typing import Any

from utils.colors import CYAN, GREEN, YELLOW, RED, RESET
from config import MCP_SERVERS


# ── 错误类 ──

class MCPError(Exception):
    """MCP 协议错误。"""


# ── 客户端 ──

class MCPClient:
    """通过 stdio 与单个 MCP server 进程通信。"""

    def __init__(self, name: str, command: str, args: list[str]):
        self.name = name
        self.command = command
        self.args = args
        self.process: subprocess.Popen | None = None
        self.tools: list[dict] = []
        self.server_info: dict = {}
        self._counter = 0
        self._lock = threading.Lock()

    def start(self) -> dict:
        """启动子进程，完成 MCP 握手（initialize + initialized）。"""
        self.process = subprocess.Popen(
            [self.command] + self.args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        threading.Thread(target=self._drain_stderr, daemon=True).start()

        result = self._request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "mini-harness", "version": "1.0"},
        })
        self.server_info = result.get("serverInfo", {})
        self._notify("notifications/initialized")
        return result

    def list_tools(self) -> list[dict]:
        """获取 server 提供的工具列表。"""
        result = self._request("tools/list", {})
        return result.get("tools", [])

    def call_tool(self, name: str, args: dict) -> str:
        """调用 server 上的工具，返回文本结果。"""
        result = self._request("tools/call", {
            "name": name,
            "arguments": args,
        })
        if result.get("isError"):
            content = result.get("content", [])
            texts = [c.get("text", "") for c in content if c.get("type") == "text"]
            return f"[MCP error] {self.name}/{name}: " + "\n".join(texts)
        content = result.get("content", [])
        texts = [c.get("text", "") for c in content if c.get("type") == "text"]
        return "\n".join(texts)

    def close(self):
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()

    # ── 底层 JSON-RPC 通信 ──

    def _request(self, method: str, params: dict) -> dict:
        with self._lock:
            self._counter += 1
            req_id = self._counter
            msg = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}
            line = json.dumps(msg, separators=(',', ':')) + "\n"
            self.process.stdin.write(line.encode())
            self.process.stdin.flush()

            while True:
                raw = self.process.stdout.readline()
                if not raw:
                    raise ConnectionError(f"MCP server '{self.name}' disconnected")
                try:
                    resp = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if "id" not in resp:
                    continue
                if resp.get("id") == req_id:
                    if "error" in resp:
                        raise MCPError(resp["error"].get("message", str(resp["error"])))
                    return resp.get("result", {})

    def _notify(self, method: str, params: dict | None = None):
        msg = {"jsonrpc": "2.0", "method": method}
        if params:
            msg["params"] = params
        line = json.dumps(msg, separators=(',', ':')) + "\n"
        self.process.stdin.write(line.encode())
        self.process.stdin.flush()

    def _drain_stderr(self):
        if not self.process:
            return
        for line in self.process.stderr:
            line = line.decode().rstrip()
            if line:
                print(f"\033[90m[mcp:{self.name}] {line}\033[0m")


# ── 全局状态 ──

mcp_clients: dict[str, MCPClient] = {}
_DISALLOWED_CHARS = __import__('re').compile(r'[^a-zA-Z0-9_-]')


def _normalize(name: str) -> str:
    return _DISALLOWED_CHARS.sub('_', name)


def _build_tools_for_client(server_name: str, client: MCPClient) -> tuple[list[dict], dict]:
    """为单个 MCP client 构建工具定义和 handler。"""
    tool_defs = []
    handlers = {}
    safe_server = _normalize(server_name)
    for tool_def in client.tools:
        safe_tool = _normalize(tool_def["name"])
        prefixed = f"mcp__{safe_server}__{safe_tool}"
        tool_defs.append({
            "name": prefixed,
            "description": tool_def.get("description", ""),
            "input_schema": tool_def.get("inputSchema", {}),
        })
        handlers[prefixed] = (
            lambda *, c=client, t=tool_def["name"], **kw: c.call_tool(t, kw)
        )
    return tool_defs, handlers


def get_mcp_tool_pool() -> tuple[list[dict], dict[str, Any]]:
    """收集所有已连接 MCP server 的工具定义和 handler，供调用方注册。

    Returns:
        (tool_defs, handlers) — 纯数据，不修改 TOOLS/TOOLS_HANDLER
    """
    tool_defs = []
    handlers = {}
    for server_name, client in mcp_clients.items():
        td, h = _build_tools_for_client(server_name, client)
        tool_defs.extend(td)
        handlers.update(h)
        for t in td:
            print(f"{GREEN}[mcp] discovered: {t['name']}{RESET}")
    return tool_defs, handlers


# ── 启动 / 连接 ──

def _do_connect(name: str, cfg: dict) -> bool:
    """执行实际连接（启动子进程、握手、获取工具）。"""
    command = cfg.get("command") if isinstance(cfg, dict) else None
    args = cfg.get("args", []) if isinstance(cfg, dict) else []
    if not command:
        return False
    print(f"{CYAN}[mcp] connecting: {name} ({command} {' '.join(args)}){RESET}")
    try:
        client = MCPClient(name, command, args)
        client.start()
        client.tools = client.list_tools()
        mcp_clients[name] = client
        print(f"{GREEN}[mcp] {name}: {len(client.tools)} tools discovered{RESET}")
        return True
    except Exception as e:
        print(f"{RED}[mcp] failed to connect {name}: {e}{RESET}")
        return False


def load_servers():
    """从 MCP_SERVERS 配置并行启动所有 MCP servers（仅连接，不注册工具）。"""
    if not MCP_SERVERS:
        return
    threads = []
    for cfg in MCP_SERVERS:
        name = cfg.get("name")
        if not name:
            continue
        t = threading.Thread(target=_do_connect, args=(name, cfg), daemon=True)
        t.start()
        threads.append(t)
    for t in threads:
        t.join()


def connect_mcp(name: str, command: str, args: str = "") -> str:
    """工具: 运行时连接 MCP server（仅连接，返回结果供调用方注册工具）。"""
    if name in mcp_clients:
        return f"MCP server '{name}' already connected"
    cfg = {"command": command, "args": args.split() if args else []}
    if _do_connect(name, cfg):
        tool_names = [t["name"] for t in mcp_clients[name].tools]
        return f"Connected to '{name}'. {len(mcp_clients[name].tools)} tools: {', '.join(tool_names)}"
    return f"Failed to connect '{name}'"
