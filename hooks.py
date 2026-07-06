"""
Hook 系统
在工具调用前后埋点，用户通过注册回调扩展行为，主循环无需修改。

事件:
  UserPromptSubmit — 用户输入后、发送给 LLM 前
  PreToolUse      — 工具执行前，返回非 None 可阻断执行
  PostToolUse     — 工具执行后
  Stop            — 循环即将退出时
"""

from typing import Any, Callable

from pathlib import Path
from permissions import check_permission
from utils.colors import CYAN, GREEN, GRAY, MAGENTA, YELLOW, RED, RESET
from config import WORKSPACE_DIR

HOOKS: dict[str, list[Callable]] = {
    "UserPromptSubmit": [],
    "PreToolUse": [],
    "PostToolUse": [],
    "Stop": [],
}


def register_hook(event: str, callback: Callable) -> None:
    """注册一个回调到指定事件。"""
    if event not in HOOKS:
        raise ValueError(f"Unknown hook event: {event}. Available: {list(HOOKS.keys())}")
    HOOKS[event].append(callback)


def trigger_hooks(event: str, *args) -> Any:
    """触发指定事件的所有回调，返回第一个非 None 的结果（阻断信号），否则返回 None。"""
    for callback in HOOKS.get(event, []):
        result = callback(*args)
        if result is not None:
            return result
    return None


def clear_hooks(event: str = None) -> None:
    """清空回调。不传 event 则清空全部。"""
    if event:
        HOOKS[event].clear()
    else:
        for lst in HOOKS.values():
            lst.clear()


# ═══════════════════════════════════════════════════════════
#  Default Hook Callbacks
# ═══════════════════════════════════════════════════════════

def _permission_hook(tool):
    """PreToolUse: delegate to check_permission. Return deny message to block, None to allow."""
    if not check_permission(tool):
        return f"⛔ 权限不足，无法执行 {tool.name}"
    return None


def _log_pre_tool(tool):
    """PreToolUse: log every tool call."""
    args_preview = ""
    if tool.input:
        args_preview = str(list(tool.input.values())[:2])[:60]
    print(f"{GRAY}[hook] PreToolUse: {tool.name}({args_preview}){RESET}")
    return None


def _log_post_tool(tool, result):
    """PostToolUse: log result + warn on large output."""
    print(f"{GRAY}[hook] PostToolUse: {tool.name} → {str(result)[:80]}{RESET}")
    if len(str(result)) > 100_000:
        print(f"{YELLOW}[hook] ⚠ Large output from {tool.name}: {len(str(result))} chars{RESET}")
    return None


def _user_prompt_hook(query: str):
    """UserPromptSubmit: log user input before it reaches the LLM."""
    print(f"{GRAY}[hook] UserPromptSubmit: {WORKSPACE_DIR}{RESET}")
    return None


def _log_stop(messages):
    """Stop: print assistant text + tool count summary."""
    for msg in reversed(messages):
        if msg.get("role") == "assistant":
            content = msg.get("content", [])
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        print(f"{GREEN}assistant: {item['text']}{RESET}")
                        print(f"{GRAY}{'='*50}{RESET}")
                        break
            break

    tool_count = 0
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, list):
            tool_count += sum(1 for item in content
                              if isinstance(item, dict)
                              and item.get("type") == "tool_result")
    print(f"{GRAY}[hook] Stop: {tool_count} tool result(s){RESET}")
    return None


# ═══════════════════════════════════════════════════════════
#  Auto-register default hooks
# ═══════════════════════════════════════════════════════════

register_hook("PreToolUse", _permission_hook)
register_hook("PreToolUse", _log_pre_tool)
register_hook("PostToolUse", _log_post_tool)
register_hook("UserPromptSubmit", _user_prompt_hook)
register_hook("Stop", _log_stop)
