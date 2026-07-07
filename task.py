"""
Task System — 文件持久化的任务图。

每个任务是一个 .json 文件，支持依赖关系（blockedBy）、
执行者（owner）、状态流转和 worktree 绑定。
"""

import json
import time
import random
import re
import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path

from config import WORKSPACE_DIR, WORKTREES_DIR, WORKDIR

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
    worktree: str | None         # worktree 名称，None 表示未分配


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
        worktree=None,
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
    worktree 不在此创建，由 LLM 通过 create_worktree 工具单独管理。
    """
    task = load_task(task_id)
    if task.status != "pending":
        return f"Task {task_id} is {task.status}, cannot claim"
    if task.owner:
        return f"Task {task_id} already owned by {task.owner}"
    if not can_start(task_id):
        deps = [d for d in task.blockedBy
                if _task_path(d).exists() and load_task(d).status != "completed"]
        missing = [d for d in task.blockedBy if not _task_path(d).exists()]
        parts = []
        if deps: parts.append(f"blocked by: {deps}")
        if missing: parts.append(f"missing deps: {missing}")
        return "Cannot start — " + ", ".join(parts)
    task.owner = owner
    task.status = "in_progress"
    save_task(task)
    print(f"  [claim] {task.subject} → in_progress")
    return f"Claimed {task.id} ({task.subject})"


def complete_task(task_id: str) -> str:
    """完成任务：in_progress → completed，返回被解锁的下游任务。

    worktree 的合并和清理由 LLM 通过 merge_worktree/remove_worktree 工具处理。
    """
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


# ============================================
# Worktree 隔离
# ============================================

_VALID_WT_NAME = re.compile(r'^[a-zA-Z0-9._-]{1,64}$')


def validate_worktree_name(name: str) -> str | None:
    """校验 worktree 名称合法性。返回错误信息或 None。"""
    if not name:
        return "Worktree name cannot be empty"
    if name in (".", ".."):
        return f"'{name}' is not a valid worktree name"
    if not _VALID_WT_NAME.match(name):
        return (f"Invalid worktree name '{name}': "
                "only letters, digits, dots, underscores, dashes (1-64 chars)")
    return None


def run_git(args: list[str], cwd: Path | None = None) -> tuple[bool, str]:
    """统一 git 调用，返回 (success, output)。"""
    target = cwd or WORKDIR
    try:
        r = subprocess.run(["git"] + args, cwd=target,
                           capture_output=True, text=True, timeout=30)
        out = (r.stdout + r.stderr).strip()
        return r.returncode == 0, out[:5000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return False, "Error: git timeout"


def log_event(event_type: str, worktree_name: str, task_id: str = ""):
    """记录 worktree 事件到 events.jsonl。"""
    event = {"type": event_type, "worktree": worktree_name,
             "task_id": task_id, "ts": time.time()}
    events_file = WORKTREES_DIR / "events.jsonl"
    with open(events_file, "a") as f:
        f.write(json.dumps(event) + "\n")


def create_worktree(name: str, task_id: str = "") -> str:
    """创建一个隔离的 git worktree。

    name: 自定义名称（如 'backend-dev'）
    task_id: 可选，绑定到指定任务
    """
    err = validate_worktree_name(name)
    if err:
        return f"Error: {err}"
    if task_id:
        try:
            load_task(task_id)
        except FileNotFoundError:
            return f"Error: task {task_id} not found"
    path = WORKTREES_DIR / name
    if path.exists():
        return f"Worktree '{name}' already exists at {path}"
    ok, result = run_git(["worktree", "add", str(path), "-b", f"wt/{name}", "HEAD"])
    if not ok:
        return f"Git error: {result}"
    if task_id:
        bind_task_to_worktree(task_id, name)
    log_event("create", name, task_id)
    print(f"  [worktree] created: {name} at {path}")
    return f"Worktree '{name}' created at {path}"


def bind_task_to_worktree(task_id: str, worktree_name: str):
    """将任务绑定到已有 worktree。"""
    task = load_task(task_id)
    task.worktree = worktree_name
    save_task(task)


def _count_worktree_changes(path: Path) -> tuple[int, int]:
    """统计 worktree 中未提交的文件数和 commit 数。"""
    try:
        r1 = subprocess.run(["git", "status", "--porcelain"],
                            cwd=path, capture_output=True, text=True, timeout=10)
        files = len([l for l in r1.stdout.strip().splitlines() if l.strip()])
        r2 = subprocess.run(["git", "log", "@{push}..HEAD", "--oneline"],
                            cwd=path, capture_output=True, text=True, timeout=10)
        commits = len([l for l in r2.stdout.strip().splitlines() if l.strip()])
        return files, commits
    except Exception:
        return -1, -1


def remove_worktree(name: str, discard_changes: bool = False) -> str:
    """删除 worktree 和关联分支。

    有未提交改动时会拒绝，需显式传入 discard_changes=True。
    """
    err = validate_worktree_name(name)
    if err:
        return err
    path = WORKTREES_DIR / name
    if not path.exists():
        return f"Worktree '{name}' not found"
    if not discard_changes:
        files, commits = _count_worktree_changes(path)
        if files < 0:
            return "Cannot verify status. Use discard_changes=true to force."
        if files > 0 or commits > 0:
            return (f"Worktree '{name}' has {files} file(s), {commits} commit(s). "
                    "Use discard_changes=true or keep_worktree.")
    ok1, _ = run_git(["worktree", "remove", str(path), "--force"])
    if not ok1:
        return f"Failed to remove worktree '{name}'"
    run_git(["branch", "-D", f"wt/{name}"])
    log_event("remove", name)
    print(f"  [worktree] removed: {name}")
    return f"Worktree '{name}' removed"


def keep_worktree(name: str) -> str:
    """保留 worktree 供人工审查，不自动删除。"""
    err = validate_worktree_name(name)
    if err:
        return err
    log_event("keep", name)
    return f"Worktree '{name}' kept for review (branch: wt/{name})"


def merge_worktree(name: str) -> str:
    """将 worktree 的 branch 合并到 main。"""
    err = validate_worktree_name(name)
    if err:
        return err
    branch = f"wt/{name}"
    ok, result = run_git(["merge", branch, "--no-ff", "-m", f"Merge {branch}"])
    if not ok:
        return f"Merge conflict:\n{result[:500]}"
    return result or f"Merged {branch}"


def list_worktrees() -> str:
    """列出当前所有 worktree。"""
    ok, result = run_git(["worktree", "list"])
    if not ok:
        return f"No git worktrees: {result}"
    return result
