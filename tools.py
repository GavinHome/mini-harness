"""
工具定义与执行模块
所有工具在此统一注册和管理
"""

import subprocess
from pathlib import Path
from typing import Any, Dict
from utils.colors import RED, RESET
WORKSPACE_DIR = Path.cwd() / ".workspace"

# ============================================
# 工具定义 (Tool Definitions)
# ============================================

TOOLS = [
    {
        "name": "run_bash",
        "description": "在工作目录中执行bash命令",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "要执行的bash命令"
                }
            },
            "required": ["command"]
        }
    },
    {
        "name": "read_file",
        "description": "读取工作目录中的文件内容",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "文件路径"
                }
            },
            "required": ["path"]
        }
    },
    {
        "name": "write_file",
        "description": "将内容写入工作目录中的文件",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "文件路径"
                },
                "content": {
                    "type": "string",
                    "description": "文件内容"
                }
            },
            "required": ["path", "content"]
        }
    },
    {
        "name": "edit_file",
        "description": "编辑工作目录中的文件，替换指定内容",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "文件路径"
                },
                "old_string": {
                    "type": "string",
                    "description": "要被替换的旧内容"
                },
                "new_string": {
                    "type": "string",
                    "description": "新内容"
                }
            },
            "required": ["path", "old_string", "new_string"]
        }
    },
    {
        "name": "glob_file",
        "description": "在工作目录中查找匹配模式的文件",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "glob匹配模式，如 *.py, **/*.txt"
                }
            },
            "required": ["pattern"]
        }
    }
]


# ============================================
# 工具实现 (Tool Implementations)
# ============================================

def run_bash(command: str) -> str:
    print(f"执行命令: {command}")
    result = subprocess.run(
        command,
        shell=True,
        cwd=WORKSPACE_DIR,
        capture_output=True,
        text=True,
        timeout=60
    )
    if result.returncode != 0:
        return f"命令执行失败 (exit code {result.returncode}):\nstdout: {result.stdout}\nstderr: {result.stderr}"
    return f"命令执行成功:\nstdout: {result.stdout}"

def safe_path(path: str) -> Path:
    p = Path(path)
    if p.is_absolute():
        resolved = p.resolve()
    else:
        resolved = (WORKSPACE_DIR / p).resolve()
    if not resolved.is_relative_to(WORKSPACE_DIR):
        raise ValueError(f"路径 {path} 不在安全工作目录 {WORKSPACE_DIR} 内")
    return resolved

def read_file(path: str) -> str:
    safe = safe_path(path)
    print(f"读取文件: {safe}")
    if not safe.exists():
        return f"文件不存在: {path}"
    if not safe.is_file():
        return f"{path} 不是文件"
    with open(safe, "r", encoding="utf-8") as f:
        return f.read()

def write_file(path: str, content: str) -> str:
    safe = safe_path(path)
    print(f"写入文件: {safe}")
    safe.parent.mkdir(parents=True, exist_ok=True)
    with open(safe, "w", encoding="utf-8") as f:
        f.write(content)
    return f"文件 {path} 已写入"

def edit_file(path: str, old_string: str, new_string: str) -> str:
    safe = safe_path(path)
    print(f"编辑文件: {safe}")
    if not safe.exists():
        return f"文件不存在: {path}"
    if not safe.is_file():
        return f"{path} 不是文件"
    with open(safe, "r", encoding="utf-8") as f:
        content = f.read()
    if old_string not in content:
        return f"未找到要替换的内容: {old_string[:50]}..."
    new_content = content.replace(old_string, new_string)
    with open(safe, "w", encoding="utf-8") as f:
        f.write(new_content)
    return f"文件 {path} 已编辑"

def glob_file(pattern: str) -> str:
    print(f"查找文件: {pattern}")
    matches = list(WORKSPACE_DIR.glob(pattern))
    if not matches:
        return f"未找到匹配 {pattern} 的文件"
    return "\n".join(str(p) for p in matches)


# ============================================
# 工具注册表 (Tool Registry)
# ============================================
TOOLS_HANDLER: Dict[str, callable] = {
    "run_bash": run_bash,
    "read_file": read_file,
    "write_file": write_file,
    "edit_file": edit_file,
    "glob_file": glob_file,
}


# ============================================
# 工具执行器 (Tool Executor)
# ============================================

def execute_tool(item) -> Any:
    """执行工具调用"""
    print(f"{RED}执行工具: {item.name}{RESET}")
    print(f"{RED}工具参数: {item.input}{RESET}")
    handler = TOOLS_HANDLER.get(item.name)
    if not handler:
        raise ValueError(f"未知工具: {item.name}")
    return handler(**item.input)
