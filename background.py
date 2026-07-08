"""
Background Tasks — 慢操作后台执行 + 异步通知

架构：
  is_slow_operation()  — 检测工具调用是否属于慢操作
  should_run_background() — 结合显式标志和关键词判断
  start_background_task()  — 启动后台线程，返回占位结果
  collect_background_results() — 收集完成的 task，格式化为通知
  inject_background_notifications() — 注入到 messages
"""

from utils.colors import CYAN, GREEN, YELLOW, RESET
import threading
import time
from typing import Any


# ── 共享状态（模块级，线程安全 via _lock） ──

_bg_counter = 0
background_tasks: dict[str, dict] = {}
background_results: dict[str, str] = {}
_lock = threading.Lock()


# ── 慢操作检测 ──

_SLOW_KEYWORDS = [
    "install", "build", "test", "deploy", "compile",
    "docker build", "pip install", "npm install",
    "cargo build", "pytest", "make",
]


def _is_slow_operation(tool_name: str, tool_input: dict) -> bool:
    """检查工具调用是否属于慢操作。"""
    if tool_name != "run_bash":
        return False
    command = tool_input.get("command", "").lower()
    return any(keyword in command for keyword in _SLOW_KEYWORDS)


def should_run_background(tool_name: str, tool_input: dict) -> bool:
    """判断是否应该在后台运行。"""
    if tool_name != "run_bash":
        return False
    # 显式标志优先
    if tool_input.get("run_in_background"):
        print(f"{CYAN}[bg] explicit flag: run_in_background=true{RESET}")
        return True
    # 关键词检测
    if _is_slow_operation(tool_name, tool_input):
        cmd = tool_input.get("command", "")
        print(f"{CYAN}[bg] slow op detected: {cmd[:60]}{RESET}")
        return True
    return False


# ── 后台任务管理 ──

def start_background_task(tool_name: str, tool_input: dict, handler, tool_use_id: str = None) -> str:
    """启动后台任务，返回 bg_id。可传入 tool_use_id 用于追踪。"""
    global _bg_counter
    with _lock:
        _bg_counter += 1
        bg_id = f"bg_{_bg_counter:04d}"
        command = tool_input.get("command", tool_name)
        background_tasks[bg_id] = {
            "tool_use_id": tool_use_id,
            "command": command,
            "status": "running",
        }

    def worker():
        print(f"{GREEN}[bg] worker started: {bg_id} -> {command[:60]}{RESET}")
        try:
            result = _call_handler(handler, tool_input, tool_name)
        except Exception as e:
            result = f"Error: {e}"
        with _lock:
            background_tasks[bg_id]["status"] = "completed"
            background_results[bg_id] = str(result)
        print(f"{GREEN}[bg] worker done: {bg_id} ({len(str(result))} chars){RESET}")

    threading.Thread(target=worker, daemon=True).start()
    return bg_id


def _call_handler(handler, args: dict, name: str) -> Any:
    """调用工具 handler（与 tools.py 中 execute_tool 逻辑一致）。"""
    if not handler:
        return f"Unknown: {name}"
    try:
        return handler(**(args or {}))
    except TypeError as e:
        return f"Error: {e}"


# ── 通知收集 ──
def collect_background_results() -> list[str]:
    """收集已完成的 background task，返回通知列表。"""
    with _lock:
        ready = [bg_id for bg_id, task in background_tasks.items()
                 if task["status"] == "completed"]

    notifications = []
    for bg_id in ready:
        with _lock:
            task = background_tasks.pop(bg_id)
            output = background_results.pop(bg_id, "")
        summary = output[:200] if len(output) > 200 else output
        notifications.append(
            f"<task_notification>\n"
            f"  <task_id>{bg_id}</task_id>\n"
            f"  <status>completed</status>\n"
            f"  <command>{task['command']}</command>\n"
            f"  <summary>{summary}</summary>\n"
            f"</task_notification>")
    return notifications


def inject_background_notifications(messages: list):
    """将已完成的 background task 通知注入 messages。"""
    notes = collect_background_results()
    if notes:
        print(f"{YELLOW}[bg] injecting {len(notes)} notification(s){RESET}")
        for note in notes:
            messages.append({"role": "user", "content": [
                {"type": "text", "text": note}]})
