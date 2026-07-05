"""
工具定义与执行模块
所有工具在此统一注册和管理
"""

from typing import Any, Dict

from utils.colors import RED, RESET
from config import WORKSPACE_DIR
from base_tools import run_bash, read_file, write_file, edit_file, glob_file
from todo import run_todo_write
from subagent import spawn_subagent

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
        "name": "compact",
        "description": "Summarize earlier conversation to free context space. Optionally specify a focus area.",
        "input_schema": {
            "type": "object",
            "properties": {
                "focus": {
                    "type": "string",
                    "description": "Optional: specific area to focus the summary on"
                }
            }
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
    },
    {
        "name": "todo_write",
        "description": "Create and manage a task list for your current coding session.",
        "input_schema": {
            "type": "object",
            "properties": {
                "todos": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "content": {"type": "string"},
                            "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]}
                        },
                        "required": ["content", "status"]
                    }
                }
            },
            "required": ["todos"]
        }
    },
    {
        "name": "task",
        "description": "Launch a subagent to handle a complex subtask. Returns only the final summary.",
        "input_schema": {
            "type": "object",
            "properties": {
                "description": {
                    "type": "string",
                    "description": "The subtask to delegate to the subagent"
                }
            },
            "required": ["description"]
        }
    }
]


# ============================================
# 工具注册表 (Tool Registry)
# ============================================
TOOLS_HANDLER: Dict[str, callable] = {
    "run_bash": run_bash,
    "read_file": read_file,
    "write_file": write_file,
    "edit_file": edit_file,
    "glob_file": glob_file,
    "todo_write": run_todo_write,
    "task": spawn_subagent,
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
