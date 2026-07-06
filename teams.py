"""
Teams — 多 Agent 协作（S15/S16/S17）

组件:
  - MessageBus: 基于 JSONL 文件的邮箱，用于 Agent 间通信
  - ProtocolState: 请求-响应 FSM，用于结构化协议
  - spawn_teammate: 创建自主队友线程
  - Lead 协议工具: request_shutdown, request_plan, review_plan
"""

import json
import time
import random
import threading
from dataclasses import dataclass, field
from pathlib import Path

from config import WORKDIR, client, MODEL_ID
from base_tools import run_bash, read_file, write_file

# ============================================
# MessageBus — 基于文件的邮箱
# ============================================

MAILBOX_DIR = WORKDIR / ".mailboxes"
MAILBOX_DIR.mkdir(exist_ok=True)


class MessageBus:
    def send(self, from_agent: str, to_agent: str, content: str,
             msg_type: str = "message", metadata: dict = None):
        msg = {
            "from": from_agent, "to": to_agent,
            "content": content, "type": msg_type,
            "ts": time.time(), "metadata": metadata or {},
        }
        inbox = MAILBOX_DIR / f"{to_agent}.jsonl"
        with open(inbox, "a") as f:
            f.write(json.dumps(msg) + "\n")
        print(f"  \033[33m[bus] {from_agent} → {to_agent}: "
              f"({msg_type}) {content[:50]}\033[0m")

    def read_inbox(self, agent: str) -> list[dict]:
        inbox = MAILBOX_DIR / f"{agent}.jsonl"
        if not inbox.exists():
            return []
        msgs = [json.loads(line) for line in inbox.read_text().splitlines()
                if line.strip()]
        inbox.unlink()
        return msgs


BUS = MessageBus()
active_teammates: dict[str, bool] = {}


# ============================================
# ProtocolState — 请求-响应状态机
# ============================================

@dataclass
class ProtocolState:
    request_id: str
    type: str
    sender: str
    target: str
    status: str
    payload: str
    created_at: float = field(default_factory=time.time)


pending_requests: dict[str, ProtocolState] = {}


def _new_request_id() -> str:
    return f"req_{random.randint(0, 999999):06d}"


def _match_response(response_type: str, request_id: str, approve: bool):
    state = pending_requests.get(request_id)
    if not state:
        return
    if state.type == "shutdown" and response_type != "shutdown_response":
        return
    if state.type == "plan_approval" and response_type != "plan_approval_response":
        return
    state.status = "approved" if approve else "rejected"


def consume_lead_inbox(route_protocol=True) -> list[dict]:
    msgs = BUS.read_inbox("lead")
    if route_protocol:
        for msg in msgs:
            meta = msg.get("metadata", {})
            req_id = meta.get("request_id", "")
            msg_type = msg.get("type", "")
            if req_id and msg_type.endswith("_response"):
                _match_response(msg_type, req_id, meta.get("approve", False))
    return msgs


# ============================================
# 自主 Agent — 空闲轮询
# ============================================

IDLE_POLL_INTERVAL = 5
IDLE_TIMEOUT = 60


def _scan_unclaimed_tasks() -> list[dict]:
    from task import TASKS_DIR, can_start
    unclaimed = []
    for f in sorted(TASKS_DIR.glob("task_*.json")):
        task = json.loads(f.read_text())
        if (task.get("status") == "pending"
                and not task.get("owner")
                and can_start(task["id"])):
            unclaimed.append(task)
    return unclaimed


def _idle_poll(agent_name: str, messages: list,
              name: str, role: str,
              worktree_context: dict | None = None) -> str:
    for _ in range(IDLE_TIMEOUT // IDLE_POLL_INTERVAL):
        time.sleep(IDLE_POLL_INTERVAL)
        inbox = BUS.read_inbox(agent_name)
        if inbox:
            for msg in inbox:
                if msg.get("type") == "shutdown_request":
                    req_id = msg.get("metadata", {}).get("request_id", "")
                    BUS.send(name, "lead", "Shutting down.",
                             "shutdown_response",
                             {"request_id": req_id, "approve": True})
                    return "shutdown"
            messages.append({"role": "user",
                "content": "<inbox>" + json.dumps(inbox) + "</inbox>"})
            return "work"
        unclaimed = _scan_unclaimed_tasks()
        if unclaimed:
            task_data = unclaimed[0]
            from task import claim_task, load_task
            result = claim_task(task_data["id"], agent_name)
            if "Claimed" in result:
                task = load_task(task_data["id"])
                if task.worktree:
                    wt_path = WORKDIR / ".worktrees" / task.worktree
                    if worktree_context is not None:
                        worktree_context["path"] = str(wt_path)
                messages.append({"role": "user",
                    "content": f"<auto-claimed>Task {task_data['id']}: "
                               f"{task_data['subject']}</auto-claimed>"})
                return "work"
    return "timeout"


# ============================================
# 队友线程
# ============================================

def spawn_teammate_thread(name: str, role: str, prompt: str) -> str:
    if name in active_teammates:
        return f"Teammate '{name}' already exists"

    protocol_ctx = {"waiting_plan": None}

    def handle_inbox_message(name: str, msg: dict, messages: list):
        msg_type = msg.get("type", "message")
        meta = msg.get("metadata", {})
        req_id = meta.get("request_id", "")
        if msg_type == "shutdown_request":
            BUS.send(name, "lead", "Shutting down.",
                     "shutdown_response",
                     {"request_id": req_id, "approve": True})
            return True
        if msg_type == "plan_approval_response":
            approve = meta.get("approve", False)
            if req_id == protocol_ctx["waiting_plan"]:
                protocol_ctx["waiting_plan"] = None
            messages.append({"role": "user",
                "content": "[Plan approved]" if approve
                           else f"[Plan rejected] {msg['content']}"})
        return False

    def run():
        wt_ctx = {"path": None}

        def _wt_cwd():
            p = wt_ctx["path"]
            return Path(p) if p else None

        def _run_bash(command: str) -> str:
            return run_bash(command, cwd=_wt_cwd())

        def _run_read(path: str) -> str:
            return read_file(path, cwd=_wt_cwd())

        def _run_write(path: str, content: str) -> str:
            return write_file(path, content, cwd=_wt_cwd())

        def _run_list_tasks():
            from task import list_tasks
            tasks = list_tasks()
            if not tasks:
                return "No tasks."
            return "\n".join(
                f"  {t.id}: {t.subject} [{t.status}]"
                + (f" (wt:{t.worktree})" if t.worktree else "")
                for t in tasks)

        def _run_claim_task(task_id: str):
            from task import claim_task, load_task
            result = claim_task(task_id, owner=name)
            if "Claimed" in result:
                task = load_task(task_id)
                if task.worktree:
                    wt_ctx["path"] = str(WORKDIR / ".worktrees" / task.worktree)
            return result

        def _run_complete_task(task_id: str):
            from task import complete_task
            result = complete_task(task_id)
            wt_ctx["path"] = None
            return result

        messages = [{"role": "user", "content": prompt}]
        sub_tools = [
            {"name": "bash", "description": "Run a shell command.",
             "input_schema": {"type": "object",
                              "properties": {"command": {"type": "string"}},
                              "required": ["command"]}},
            {"name": "read_file", "description": "Read file.",
             "input_schema": {"type": "object",
                              "properties": {"path": {"type": "string"}},
                              "required": ["path"]}},
            {"name": "write_file", "description": "Write file.",
             "input_schema": {"type": "object",
                              "properties": {"path": {"type": "string"},
                                             "content": {"type": "string"}},
                              "required": ["path", "content"]}},
            {"name": "send_message",
             "description": "Send message to another agent.",
             "input_schema": {"type": "object",
                              "properties": {"to": {"type": "string"},
                                             "content": {"type": "string"}},
                              "required": ["to", "content"]}},
            {"name": "submit_plan",
             "description": "Submit a plan for Lead approval.",
             "input_schema": {"type": "object",
                              "properties": {"plan": {"type": "string"}},
                              "required": ["plan"]}},
            {"name": "list_tasks",
             "description": "List all tasks.",
             "input_schema": {"type": "object", "properties": {},
                              "required": []}},
            {"name": "claim_task",
             "description": "Claim a pending task.",
             "input_schema": {"type": "object",
                              "properties": {"task_id": {"type": "string"}},
                              "required": ["task_id"]}},
            {"name": "complete_task",
             "description": "Mark an in-progress task as completed.",
             "input_schema": {"type": "object",
                              "properties": {"task_id": {"type": "string"}},
                              "required": ["task_id"]}},
        ]

        sub_handlers = {
            "bash": _run_bash, "read_file": _run_read,
            "write_file": _run_write,
            "send_message": lambda to, content: BUS.send(name, to, content) or "Sent",
            "list_tasks": _run_list_tasks,
            "claim_task": _run_claim_task,
            "complete_task": _run_complete_task,
        }

        while True:
            if len(messages) <= 3:
                messages.insert(0, {"role": "user",
                    "content": f"<identity>You are '{name}', role: {role}. "
                               f"Continue your work.</identity>"})
            should_shutdown = False
            for _ in range(10):
                inbox = BUS.read_inbox(name)
                for msg in inbox:
                    stopped = handle_inbox_message(name, msg, messages)
                    if stopped:
                        should_shutdown = True
                        break
                if should_shutdown:
                    break
                if protocol_ctx["waiting_plan"]:
                    time.sleep(IDLE_POLL_INTERVAL)
                    continue
                if inbox and not should_shutdown:
                    non_protocol = [m for m in inbox
                                    if m.get("type") == "message"]
                    if non_protocol:
                        messages.append({"role": "user",
                            "content": "<inbox>" + json.dumps(non_protocol) + "</inbox>"})
                try:
                    response = client.messages.create(
                        model=MODEL_ID,
                        system=f"You are '{name}', a {role}. Use tools to complete tasks.",
                        messages=messages[-20:],
                        tools=sub_tools,
                        max_tokens=8000,
                    )
                except Exception:
                    break
                messages.append({"role": "assistant", "content": response.content})
                if not any(getattr(b, "type", None) == "tool_use" for b in (response.content or [])):
                    break
                results = []
                for block in response.content:
                    if block.type != "tool_use":
                        continue
                    if block.name == "submit_plan":
                        output = _teammate_submit_plan(
                            name, block.input.get("plan", ""))
                        import re as _re
                        match = _re.search(r"\((req_\d+)\)", output)
                        protocol_ctx["waiting_plan"] = (
                            match.group(1) if match else output)
                    else:
                        handler = sub_handlers.get(block.name)
                        output = handler(**block.input) if handler else f"Unknown tool: {block.name}"
                    results.append({"type": "tool_result",
                                    "tool_use_id": block.id,
                                    "content": str(output)})
                    if protocol_ctx["waiting_plan"]:
                        break
                messages.append({"role": "user", "content": results})
                if protocol_ctx["waiting_plan"]:
                    break
            if should_shutdown:
                break
            if protocol_ctx["waiting_plan"]:
                continue
            idle_result = _idle_poll(name, messages, name, role, wt_ctx)
            if idle_result in ("shutdown", "timeout"):
                break

        summary = "Done."
        for msg in reversed(messages):
            if msg["role"] == "assistant":
                content = msg["content"]
                if isinstance(content, list):
                    for b in content:
                        if getattr(b, "type", None) == "text":
                            summary = b.text
                            break
                    else:
                        continue
                    break
                elif isinstance(content, str):
                    summary = content
                    break
        BUS.send(name, "lead", summary, "result")
        active_teammates.pop(name, None)

    active_teammates[name] = True
    threading.Thread(target=run, daemon=True).start()
    return f"Teammate '{name}' spawned as {role}"


def _teammate_submit_plan(from_name: str, plan: str) -> str:
    req_id = _new_request_id()
    pending_requests[req_id] = ProtocolState(
        request_id=req_id, type="plan_approval",
        sender=from_name, target="lead",
        status="pending", payload=plan)
    BUS.send(from_name, "lead", plan,
             "plan_approval_request",
             {"request_id": req_id})
    return f"Plan submitted ({req_id})"


# ============================================
# Lead 协议工具
# ============================================

def run_request_shutdown(teammate: str) -> str:
    req_id = _new_request_id()
    pending_requests[req_id] = ProtocolState(
        request_id=req_id, type="shutdown",
        sender="lead", target=teammate,
        status="pending", payload="")
    BUS.send("lead", teammate, "Shut down.", "shutdown_request",
             {"request_id": req_id})
    return f"Shutdown request sent to {teammate}"


def run_review_plan(request_id: str, approve: bool,
                    feedback: str = "") -> str:
    state = pending_requests.get(request_id)
    if not state:
        return f"Request {request_id} not found"
    state.status = "approved" if approve else "rejected"
    BUS.send("lead", state.sender,
             feedback or ("Approved" if approve else "Rejected"),
             "plan_approval_response",
             {"request_id": request_id, "approve": approve})
    return f"Plan {'approved' if approve else 'rejected'}"


# ============================================
# Lead 通信工具
# ============================================

def run_request_plan(teammate: str, task: str) -> str:
    BUS.send("lead", teammate, f"Submit plan for: {task}", "message")
    return f"Asked {teammate} to submit a plan"


def run_send_message(to: str, content: str) -> str:
    BUS.send("lead", to, content)
    return f"Sent to {to}"


def run_check_inbox() -> str:
    msgs = consume_lead_inbox(route_protocol=True)
    if not msgs:
        return "(inbox empty)"
    lines = []
    for m in msgs:
        meta = m.get("metadata", {})
        req_id = meta.get("request_id", "")
        tag = f" [{m['type']} req:{req_id}]" if req_id else f" [{m['type']}]"
        lines.append(f"  [{m['from']}]{tag} {m['content'][:200]}")
    return "\n".join(lines)


# ============================================
# 工具定义（供合并到主 TOOLS）
# ============================================
TEAMS_TOOLS = [
    {"name": "spawn_teammate",
     "description": "Spawn an autonomous teammate with a name, role, and initial prompt.",
     "input_schema": {"type": "object",
                      "properties": {
                          "name": {"type": "string", "description": "Unique name for this teammate"},
                          "role": {"type": "string", "description": "Role description (e.g. 'backend developer')"},
                          "prompt": {"type": "string", "description": "Initial task/prompt for the teammate"},
                      },
                      "required": ["name", "role", "prompt"]}},
    {"name": "send_message",
     "description": "Send a message to a teammate.",
     "input_schema": {"type": "object",
                      "properties": {
                          "to": {"type": "string", "description": "Teammate name"},
                          "content": {"type": "string", "description": "Message content"},
                      },
                      "required": ["to", "content"]}},
    {"name": "check_inbox",
     "description": "Check lead inbox for messages and protocol responses.",
     "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "request_shutdown",
     "description": "Request a teammate to shut down (with confirmation protocol).",
     "input_schema": {"type": "object",
                      "properties": {
                          "teammate": {"type": "string", "description": "Teammate name to shutdown"},
                      },
                      "required": ["teammate"]}},
    {"name": "request_plan",
     "description": "Ask a teammate to submit a plan for a task.",
     "input_schema": {"type": "object",
                      "properties": {
                          "teammate": {"type": "string", "description": "Teammate name"},
                          "task": {"type": "string", "description": "Task description"},
                      },
                      "required": ["teammate", "task"]}},
    {"name": "review_plan",
     "description": "Approve or reject a plan submitted by a teammate.",
     "input_schema": {"type": "object",
                      "properties": {
                          "request_id": {"type": "string", "description": "The request_id from submit_plan"},
                          "approve": {"type": "boolean", "description": "True to approve, False to reject"},
                          "feedback": {"type": "string", "description": "Optional feedback for the teammate"},
                      },
                      "required": ["request_id", "approve"]}},
]

# ============================================
# Teams 工具注册表 (Teams Tool Registry)
# ============================================
TEAMS_HANDLERS = {
    "spawn_teammate": spawn_teammate_thread,
    "send_message": run_send_message,
    "check_inbox": run_check_inbox,
    "request_shutdown": run_request_shutdown,
    "request_plan": run_request_plan,
    "review_plan": run_review_plan,
}
