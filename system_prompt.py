"""
System Prompt Assembly — runtime prompt construction from context.

Design:
  PROMPT_SECTIONS  → 文本模板库存
  assemble_system_prompt(context)  → 按需拼接
  get_system_prompt(context)       → 缓存壳，避免重复拼装
"""

import json

from config import WORKSPACE_DIR, WORKTREES_DIR

from memory import MEMORY_INDEX
from skills import list_skills

# ============================================
#  Prompt Sections (文本模板库存)
# ============================================

PROMPT_SECTIONS = {
    "identity": "You are a coding agent. Act, don't explain.",
    "tools": "Available tools: {tool_names}.",
    "workspace": f"Working directory: {WORKSPACE_DIR}",
    "memory": "Relevant memories are injected below when available.",
    "planning": (
        "For simple multi-step tasks you handle yourself, use todo_write to plan "
        "your steps. Update status (pending → in_progress → completed) as you progress."
    ),
    "teams": (
        "For complex tasks that span different specialties and can be parallelized, "
        "use spawn_teammate to create specialized teammates. Each teammate works "
        "autonomously in their own thread. You manage them via send_message, "
        "check_inbox, request_shutdown, request_plan, and review_plan. "
        "Assign one focused task per teammate and let them claim and complete it. "
        "Simple multi-step tasks can be handled directly with todo_write."
    ),
    "worktree": (
        "Worktree isolation (S20 pattern):\n"
        "1. Always use the create_worktree tool to create worktrees. "
        "Do NOT run 'git worktree add' via bash — it creates worktrees in the wrong place.\n"
        "2. create_worktree(name, task_id) creates a branch 'wt/{name}' and a directory "
        f"at {WORKTREES_DIR}/{{name}}. This is the ONLY place worktrees should live.\n"
        "3. After creating a worktree, create a task bound to it, then assign that task to a teammate.\n"
        "4. After the teammate completes, merge_worktree(name) to merge the branch, "
        "then remove_worktree(name) or keep_worktree(name).\n"
        "5. When assigning a task with a worktree, tell the teammate the worktree path."
    ),
    "skills": "Skills catalog:\n{skills_catalog}\nUse load_skill(name) when a skill is relevant for your task.",
}

# ============================================
#  Context Update
# ============================================

def update_context(context: dict, messages: list) -> dict:
    """从真实世界收集当前状态，生成 context dict。"""
    from tools import TOOLS
    memories = ""
    if MEMORY_INDEX.exists():
        memories = MEMORY_INDEX.read_text()[:2000]
    return {
        "enabled_tools": [t["name"] for t in TOOLS],
        "workspace": str(WORKSPACE_DIR),
        "memories": memories,
    }

# ============================================
#  Prompt Assembly
# ============================================

def assemble_system_prompt(context: dict) -> str:
    """根据 context 动态拼装 system prompt。"""
    sections = [
        PROMPT_SECTIONS["identity"],
        PROMPT_SECTIONS["tools"].format(
            tool_names=", ".join(context.get("enabled_tools", []))
        ),
        PROMPT_SECTIONS["workspace"],
        PROMPT_SECTIONS["planning"],
        PROMPT_SECTIONS["teams"],
        PROMPT_SECTIONS["worktree"],
        PROMPT_SECTIONS["skills"].format(skills_catalog=list_skills()),
    ]

    if context.get("memories"):
        sections.append(f"Relevant memories:\n{context['memories']}")

    return "\n\n".join(sections)

# ============================================
#  Cached Access
# ============================================

_last_context_key = None
_last_prompt = None


def get_system_prompt(context: dict) -> str:
    """缓存壳：context 没变就返回上次结果，变了才重新组装。"""
    global _last_context_key, _last_prompt
    key = json.dumps(context, sort_keys=True, ensure_ascii=False, default=str)
    if key == _last_context_key and _last_prompt:
        return _last_prompt
    _last_context_key = key
    _last_prompt = assemble_system_prompt(context)
    return _last_prompt
