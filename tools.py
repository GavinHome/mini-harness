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
from task import (
    create_task,
    list_tasks,
    get_task,
    claim_task,
    complete_task,
    create_worktree,
    remove_worktree,
    keep_worktree,
    merge_worktree,
    list_worktrees,
)
from skills import load_skill
from cron import run_schedule_cron, run_list_crons, run_cancel_cron
from teams import TEAMS_TOOLS, TEAMS_HANDLERS

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
    },
    {
        "name": "create_task",
        "description": "Create a new persistent task. Optionally specify dependencies via blockedBy.",
        "input_schema": {
            "type": "object",
            "properties": {
                "subject": {"type": "string", "description": "Brief task title"},
                "description": {"type": "string", "description": "Detailed description"},
                "blockedBy": {"type": "array", "items": {"type": "string"}, "description": "Task IDs that must complete before this one can start"}
            },
            "required": ["subject"]
        }
    },
    {
        "name": "list_tasks",
        "description": "List all tasks with their status, owner, and dependencies.",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "name": "get_task",
        "description": "Get full details of a specific task by ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "The task ID to retrieve"}
            },
            "required": ["task_id"]
        }
    },
    {
        "name": "claim_task",
        "description": "Claim a task to start executing it. Status changes from pending to in_progress.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "The task ID to claim"}
            },
            "required": ["task_id"]
        }
    },
    {
        "name": "complete_task",
        "description": "Mark a task as completed. Automatically unblocks downstream tasks.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "The task ID to complete"}
            },
            "required": ["task_id"]
        }
    },
    {
        "name": "create_worktree",
        "description": "Create an isolated git worktree with a custom name. Optionally bind to a task.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Worktree name (e.g. 'backend-dev')"},
                "task_id": {"type": "string", "description": "Optional: bind this worktree to a task"}
            },
            "required": ["name"]
        }
    },
    {
        "name": "remove_worktree",
        "description": "Remove a worktree. Refuses if uncommitted changes exist unless discard_changes=true.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Worktree name to remove"},
                "discard_changes": {"type": "boolean", "description": "Force remove even with uncommitted changes"}
            },
            "required": ["name"]
        }
    },
    {
        "name": "keep_worktree",
        "description": "Keep a worktree for manual review instead of removing it.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Worktree name to keep"}
            },
            "required": ["name"]
        }
    },
    {
        "name": "merge_worktree",
        "description": "Merge a worktree's branch (wt/{name}) into main.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Worktree name to merge"}
            },
            "required": ["name"]
        }
    },
    {
        "name": "list_worktrees",
        "description": "List all active git worktrees.",
        "input_schema": {"type": "object", "properties": {}, "required": []}},
    {
        "name": "load_skill",
        "description": "Load the full content of a skill by name for detailed guidance.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Skill name to load"}
            },
            "required": ["name"]
        }
    },
    {
        "name": "schedule_cron",
        "description": "Schedule a cron job that triggers an agent prompt at specified times. Cron format: 'minute hour day-of-month month day-of-week'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "cron": {"type": "string", "description": "Cron expression (5 fields): e.g. '*/5 * * * *' for every 5 min, '0 9 * * 1-5' for 9am weekdays"},
                "prompt": {"type": "string", "description": "The prompt to execute when the cron fires"},
                "recurring": {"type": "boolean", "description": "If true (default), repeats. If false, one-shot only."},
                "durable": {"type": "boolean", "description": "If true (default), survives restart. If false, session-only."}
            },
            "required": ["cron", "prompt"]
        }
    },
    {
        "name": "list_crons",
        "description": "List all scheduled cron jobs with their schedule, prompt, and status.",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "name": "cancel_cron",
        "description": "Cancel a scheduled cron job by its ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "The cron job ID to cancel"}
            },
            "required": ["job_id"]
        }
    },
]

TOOLS.extend(TEAMS_TOOLS)


# ============================================


# ============================================
# Task 工具包装函数（返回字符串，避免 JSON 序列化问题）
# ============================================

def run_create_task(subject: str, description: str = "", blockedBy: list[str] | None = None) -> str:
    task = create_task(subject, description, blockedBy)
    deps = f" (blockedBy: {', '.join(blockedBy)})" if blockedBy else ""
    return f"Created {task.id}: {task.subject}{deps}"


def run_list_tasks() -> str:
    tasks = list_tasks()
    if not tasks:
        return "No tasks. Use create_task to add some."
    lines = []
    for t in tasks:
        icon = {"pending": "○", "in_progress": "●", "completed": "✓"}.get(t.status, "?")
        deps = f" (blockedBy: {', '.join(t.blockedBy)})" if t.blockedBy else ""
        owner = f" [{t.owner}]" if t.owner else ""
        lines.append(f"  {icon} {t.id}: {t.subject} [{t.status}]{owner}{deps}")
    return "\n".join(lines)


def run_get_task(task_id: str) -> str:
    try:
        return get_task(task_id)
    except FileNotFoundError:
        return f"Error: Task {task_id} not found"


def run_claim_task(task_id: str) -> str:
    return claim_task(task_id, owner="agent")


def run_complete_task(task_id: str) -> str:
    return complete_task(task_id)


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
    "create_task": run_create_task,
    "list_tasks": run_list_tasks,
    "get_task": run_get_task,
    "claim_task": run_claim_task,
    "complete_task": run_complete_task,
    "create_worktree": create_worktree,
    "remove_worktree": remove_worktree,
    "keep_worktree": keep_worktree,
    "merge_worktree": merge_worktree,
    "list_worktrees": list_worktrees,
    "load_skill": load_skill,
    "schedule_cron": run_schedule_cron,
    "list_crons": run_list_crons,
    "cancel_cron": run_cancel_cron,
}

TOOLS_HANDLER.update(TEAMS_HANDLERS)


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
    return handler(**(item.input or {}))
