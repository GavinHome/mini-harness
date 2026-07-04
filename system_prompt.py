"""
System Prompt Assembly — runtime prompt construction from context.

Design:
  PROMPT_SECTIONS  → 文本模板库存
  assemble_system_prompt(context)  → 按需拼接
  get_system_prompt(context)       → 缓存壳，避免重复拼装
"""

import json

from config import WORKSPACE_DIR

from memory import MEMORY_INDEX

# ============================================
#  Prompt Sections (文本模板库存)
# ============================================

PROMPT_SECTIONS = {
    "identity": "You are a coding agent. Act, don't explain.",
    "tools": "Available tools: {tool_names}.",
    "workspace": f"Working directory: {WORKSPACE_DIR}",
    "memory": "Relevant memories are injected below when available.",
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
