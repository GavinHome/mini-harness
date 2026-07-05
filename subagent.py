"""
Subagent — 子代理系统。

父 Agent 通过 task tool 委托子任务，子代理独立执行，返回摘要。

设计：
  - spawn_subagent 创建 fresh messages[]，上下文隔离
  - SUB_TOOLS 不含 task，防止递归
  - max 30 turns 安全上限
  - 返回摘要而非完整历史，避免父代理上下文膨胀
"""

import subprocess
from pathlib import Path

from config import WORKSPACE_DIR
from base_tools import run_bash, read_file, write_file, edit_file, glob_file

# ============================================
# 子代理工具集（不含 task，防止递归）
# ============================================

SUB_TOOLS = [
    {"name": "bash", "description": "Run a shell command.",
     "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
    {"name": "read_file", "description": "Read file contents.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"name": "write_file", "description": "Write content to a file.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
    {"name": "edit_file", "description": "Replace exact text in a file once.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "old_string": {"type": "string"}, "new_string": {"type": "string"}}, "required": ["path", "old_string", "new_string"]}},
    {"name": "glob_file", "description": "Find files matching a glob pattern.",
     "input_schema": {"type": "object", "properties": {"pattern": {"type": "string"}}, "required": ["pattern"]}},
]

SUB_HANDLERS = {
    "bash": run_bash,
    "read_file": read_file,
    "write_file": write_file,
    "edit_file": edit_file,
    "glob_file": glob_file,
}

SUB_SYSTEM = (
    f"You are a coding agent at {WORKSPACE_DIR}. "
    "Complete the task you were given, then return a concise summary. "
    "Do not delegate further."
)

# ============================================
# 文本提取工具
# ============================================

def extract_text(content) -> str:
    """从 response.content（Block 列表）提取所有文本拼接。"""
    if not isinstance(content, list):
        return str(content)
    return "".join(getattr(b, "text", "") for b in content if getattr(b, "type", None) == "text")

# ============================================
# 子代理运行时
# ============================================

def spawn_subagent(description: str) -> str:
    """创建子代理，独立执行任务，返回摘要。"""
    from config import client, MODEL_ID

    print(f"\n\033[35m[Subagent spawned] {description[:60]}{'...' if len(description) > 60 else ''}\033[0m")
    messages = [{"role": "user", "content": description}]

    for _ in range(30):
        response = client.messages.create(
            model=MODEL_ID,
            system=SUB_SYSTEM,
            messages=messages,
            tools=SUB_TOOLS,
            max_tokens=8000,
        )
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            break

        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            handler = SUB_HANDLERS.get(block.name)
            if not handler:
                output = f"Unknown tool: {block.name}"
            else:
                output = handler(**block.input)
            results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": output,
            })
        messages.append({"role": "user", "content": results})

    result = extract_text(messages[-1]["content"])
    if not result:
        for msg in reversed(messages):
            if msg["role"] == "assistant":
                result = extract_text(msg["content"])
                if result:
                    break
        if not result:
            result = "Subagent stopped after 30 turns without final answer."

    print(f"\033[35m[Subagent done]\033[0m")
    return result
