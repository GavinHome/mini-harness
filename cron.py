"""
Cron 定时任务模块

架构：
  cron_scheduler_loop (后台线程) — 每秒检查 cron 表达式，匹配的 job 入队
  cron_autorun_loop   (后台线程) — 从队列取出 job，调用 agent_loop 自动执行
  agent_lock — 防止多个 agent_loop 同时运行

工具：
  schedule_cron / list_crons / cancel_cron
"""

import json
import random
import threading
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path

from config import WORKDIR


# ── 常量 ──

DURABLE_PATH = WORKDIR / ".scheduled_tasks.json"


# ── 数据模型 ──

@dataclass
class CronJob:
    id: str
    cron: str
    prompt: str
    recurring: bool
    durable: bool


# ── 状态（模块级，线程安全 via cron_lock） ──

scheduled_jobs: dict[str, CronJob] = {}
cron_queue: list[CronJob] = []
cron_lock = threading.Lock()
_last_fired: dict[str, str] = {}


# ── Cron 表达式解析 ──

def _cron_field_matches(field: str, value: int) -> bool:
    if field == "*":
        return True
    if field.startswith("*/"):
        step = int(field[2:])
        return step > 0 and value % step == 0
    if "," in field:
        return any(_cron_field_matches(part.strip(), value) for part in field.split(","))
    if "-" in field:
        lo, hi = field.split("-", 1)
        return int(lo) <= value <= int(hi)
    return value == int(field)


def cron_matches(cron_expr: str, dt: datetime) -> bool:
    fields = cron_expr.strip().split()
    if len(fields) != 5:
        return False
    minute, hour, dom, month, dow = fields
    dow_val = (dt.weekday() + 1) % 7
    m = _cron_field_matches(minute, dt.minute)
    h = _cron_field_matches(hour, dt.hour)
    dom_ok = _cron_field_matches(dom, dt.day)
    month_ok = _cron_field_matches(month, dt.month)
    dow_ok = _cron_field_matches(dow, dow_val)
    if not (m and h and month_ok):
        return False
    if dom == "*" and dow == "*":
        return True
    if dom == "*":
        return dow_ok
    if dow == "*":
        return dom_ok
    return dom_ok or dow_ok


def _validate_cron_field(field: str, lo: int, hi: int) -> str | None:
    if field == "*":
        return None
    if field.startswith("*/"):
        step = field[2:]
        if not step.isdigit() or int(step) <= 0:
            return f"Invalid step: {field}"
        return None
    if "," in field:
        for part in field.split(","):
            err = _validate_cron_field(part.strip(), lo, hi)
            if err:
                return err
        return None
    if "-" in field:
        left, right = field.split("-", 1)
        if not left.isdigit() or not right.isdigit():
            return f"Invalid range: {field}"
        a, b = int(left), int(right)
        if a < lo or a > hi or b < lo or b > hi:
            return f"Range {field} out of bounds [{lo}-{hi}]"
        if a > b:
            return f"Range start > end: {field}"
        return None
    if not field.isdigit():
        return f"Invalid field: {field}"
    value = int(field)
    if value < lo or value > hi:
        return f"Value {value} out of bounds [{lo}-{hi}]"
    return None


def validate_cron(cron_expr: str) -> str | None:
    fields = cron_expr.strip().split()
    if len(fields) != 5:
        return f"Expected 5 fields, got {len(fields)}"
    bounds = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 6)]
    names = ["minute", "hour", "day-of-month", "month", "day-of-week"]
    for field, (lo, hi), name in zip(fields, bounds, names):
        err = _validate_cron_field(field, lo, hi)
        if err:
            return f"{name}: {err}"
    return None


# ── 持久化 ──

def save_durable_jobs():
    durable = [asdict(job) for job in scheduled_jobs.values() if job.durable]
    DURABLE_PATH.write_text(json.dumps(durable, indent=2))


def load_durable_jobs():
    if not DURABLE_PATH.exists():
        return
    try:
        for item in json.loads(DURABLE_PATH.read_text()):
            job = CronJob(**item)
            if not validate_cron(job.cron):
                scheduled_jobs[job.id] = job
    except Exception:
        pass


# ── 调度核心 ──

def schedule_job(cron: str, prompt: str,
                 recurring: bool = True, durable: bool = True) -> CronJob | str:
    err = validate_cron(cron)
    if err:
        return err
    job = CronJob(
        id=f"cron_{random.randint(0, 999999):06d}",
        cron=cron, prompt=prompt,
        recurring=recurring, durable=durable)
    with cron_lock:
        scheduled_jobs[job.id] = job
    if durable:
        save_durable_jobs()
    return job


def cancel_job(job_id: str) -> str:
    with cron_lock:
        job = scheduled_jobs.pop(job_id, None)
    if not job:
        return f"Job {job_id} not found"
    if job.durable:
        save_durable_jobs()
    return f"Cancelled {job_id}"


def cron_scheduler_loop():
    """后台线程：每秒检查是否有 cron job 到达触发时间。"""
    while True:
        time.sleep(1)
        now = datetime.now()
        marker = now.strftime("%Y-%m-%d %H:%M")
        with cron_lock:
            for job in list(scheduled_jobs.values()):
                try:
                    if cron_matches(job.cron, now) and _last_fired.get(job.id) != marker:
                        cron_queue.append(job)
                        _last_fired[job.id] = marker
                        if not job.recurring:
                            scheduled_jobs.pop(job.id, None)
                            if job.durable:
                                save_durable_jobs()
                except Exception as e:
                    print(f"\033[31m[cron error] {job.id}: {e}\033[0m")


def consume_cron_queue() -> list[CronJob]:
    with cron_lock:
        fired = list(cron_queue)
        cron_queue.clear()
    return fired


# ── 自动执行循环 ──

# 这些由 mini-harness.py 在启动时注入（避免循环导入）
_agent_loop_fn = None       # agent_loop(messages, context) -> (usage, context)
_shared_history = None      # list — 共享对话历史
_shared_context = None      # dict — 共享上下文
_agent_lock_ref = None      # threading.Lock() — 防止并发


def cron_autorun_loop():
    """后台线程：监控 cron 队列，触发时自动调用 agent_loop。"""
    while True:
        time.sleep(1)
        fired = consume_cron_queue()
        if not fired:
            continue
        for job in fired:
            print(f"\033[35m[cron auto] {job.prompt[:60]}\033[0m")
            if _agent_loop_fn and _shared_history is not None and _shared_context is not None:
                _shared_history.append({
                    "role": "user",
                    "content": f"[Scheduled] {job.prompt}"
                })
                try:
                    _agent_lock_ref.acquire()
                    _, new_context = _agent_loop_fn(_shared_history, context=_shared_context)
                    _shared_context.clear()
                    _shared_context.update(new_context)
                except Exception as e:
                    print(f"\033[31m[cron auto error] {e}\033[0m")
                finally:
                    if _agent_lock_ref.locked():
                        _agent_lock_ref.release()


# ── 工具包装函数 ──

def run_schedule_cron(cron: str, prompt: str,
                      recurring: bool = True, durable: bool = True) -> str:
    result = schedule_job(cron, prompt, recurring, durable)
    if isinstance(result, str):
        return f"Error: {result}"
    return f"Scheduled {result.id}: '{cron}' -> {prompt[:40]}"


def run_list_crons() -> str:
    with cron_lock:
        jobs = list(scheduled_jobs.values())
    if not jobs:
        return "No cron jobs."
    return "\n".join(
        f"  {job.id}: '{job.cron}' -> {job.prompt[:40]} "
        f"[{'recurring' if job.recurring else 'one-shot'}, "
        f"{'durable' if job.durable else 'session'}]"
        for job in jobs)


def run_cancel_cron(job_id: str) -> str:
    return cancel_job(job_id)


# ── 启动 ──

def start_cron_threads(agent_loop_fn, history, context, agent_lock):
    """由 mini-harness.py 调用，注入依赖并启动线程。"""
    global _agent_loop_fn, _shared_history, _shared_context, _agent_lock_ref
    _agent_loop_fn = agent_loop_fn
    _shared_history = history
    _shared_context = context
    _agent_lock_ref = agent_lock

    load_durable_jobs()
    threading.Thread(target=cron_scheduler_loop, daemon=True).start()
    threading.Thread(target=cron_autorun_loop, daemon=True).start()
