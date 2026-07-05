"""
Task System — 文件持久化的任务图。

每个任务是一个 .json 文件，支持依赖关系（blockedBy）、
执行者（owner）和状态流转。
"""

import json
import time
import random
from dataclasses import dataclass, asdict
from pathlib import Path

from config import WORKSPACE_DIR

TASKS_DIR = WORKSPACE_DIR / ".tasks"
TASKS_DIR.mkdir(exist_ok=True)


# ============================================
# 数据模型
# ============================================

@dataclass
class Task:
    id: str
    subject: str
    description: str
    status: str                  # pending | in_progress | completed
    owner: str | None
    blockedBy: list[str]


# ============================================
# 内部辅助
# ============================================

def _task_path(task_id: str) -> Path:
    return TASKS_DIR / f"{task_id}.json"


# ============================================
# 核心 CRUD
# ============================================

def create_task(subject: str, description: str = "",
                blockedBy: list[str] | None = None) -> Task:
    """创建新任务，写入文件。返回 Task 对象。"""
    task = Task(
        id=f"task_{int(time.time())}_{random.randint(0, 9999):04d}",
        subject=subject,
        description=description,
        status="pending",
        owner=None,
        blockedBy=blockedBy or [],
    )
    save_task(task)
    return task


def save_task(task: Task):
    """序列化任务写入 JSON 文件。"""
    _task_path(task.id).write_text(json.dumps(asdict(task), indent=2))


def load_task(task_id: str) -> Task:
    """从 JSON 文件反序列化为 Task 对象。"""
    return Task(**json.loads(_task_path(task_id).read_text()))


def list_tasks() -> list[Task]:
    """列出所有任务。"""
    return [
        Task(**json.loads(p.read_text()))
        for p in sorted(TASKS_DIR.glob("task_*.json"))
    ]


def get_task(task_id: str) -> str:
    """返回单个任务的 JSON 详情。"""
    task = load_task(task_id)
    return json.dumps(asdict(task), indent=2)


# ============================================
# 依赖与状态流转
# ============================================

def can_start(task_id: str) -> bool:
    """检查任务的 blockedBy 依赖是否全部完成。

    缺失的依赖文件视为被阻塞。
    """
    task = load_task(task_id)
    for dep_id in task.blockedBy:
        if not _task_path(dep_id).exists():
            return False
        if load_task(dep_id).status != "completed":
            return False
    return True


def claim_task(task_id: str, owner: str = "agent") -> str:
    """领取任务：pending → in_progress，设置 owner。

    执行前检查 can_start，被阻塞则返回原因。
    """
    task = load_task(task_id)
    if task.status != "pending":
        return f"Task {task_id} is {task.status}, cannot claim"
    if not can_start(task_id):
        deps = [
            d for d in task.blockedBy
            if not _task_path(d).exists() or load_task(d).status != "completed"
        ]
        return f"Blocked by: {deps}"
    task.owner = owner
    task.status = "in_progress"
    save_task(task)
    return f"Claimed {task.id} ({task.subject})"


def complete_task(task_id: str) -> str:
    """完成任务：in_progress → completed，返回被解锁的下游任务。"""
    task = load_task(task_id)
    if task.status != "in_progress":
        return f"Task {task_id} is {task.status}, cannot complete"
    task.status = "completed"
    save_task(task)
    unblocked = [
        t.subject for t in list_tasks()
        if t.status == "pending" and t.blockedBy and can_start(t.id)
    ]
    msg = f"Completed {task.id} ({task.subject})"
    if unblocked:
        msg += f"\nUnblocked: {', '.join(unblocked)}"
    return msg
