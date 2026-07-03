"""
上下文压缩管道
执行顺序: L3 (budget) -> L1 (snip) -> L2 (micro) -> [阈值检查 -> L4 (summary)]
紧急回退: reactive_compact (prompt_too_long 时触发)

Cheap first, expensive last.
"""

import json
import time
from pathlib import Path

from utils.colors import YELLOW, CYAN, GRAY, RESET

# --- 常量 ---
CONTEXT_LIMIT = 50_000        # 字符估算阈值
KEEP_RECENT = 3               # L2: 保留最近 N 条 tool_result
PERSIST_THRESHOLD = 30_000    # L3: 单条结果超过此字节数才持久化
MAX_TOOL_RESULT_BYTES = 200_000  # L3: 最后一条消息中 tool_result 总字节上限
MAX_MESSAGES = 50             # L1: 消息数上限
KEEP_HEAD = 3                 # L1: 保留头部消息数

WORKDIR = Path.cwd()
TOOL_RESULTS_DIR = WORKDIR / ".task_outputs" / "tool-results"
TRANSCRIPT_DIR = WORKDIR / ".transcripts"


# --- 辅助函数 ---
def _block_type(block):
    if isinstance(block, dict):
        return block.get("type")
    return getattr(block, "type", None)


def _message_has_tool_use(msg):
    if msg.get("role") != "assistant":
        return False
    content = msg.get("content")
    if not isinstance(content, list):
        return False
    return any(_block_type(block) == "tool_use" for block in content)


def _is_tool_result_message(msg):
    if msg.get("role") != "user":
        return False
    content = msg.get("content")
    if not isinstance(content, list):
        return False
    return any(isinstance(block, dict) and block.get("type") == "tool_result"
               for block in content)


def _estimate_size(msgs) -> int:
    return len(json.dumps(msgs, default=str, ensure_ascii=False))


# --- L3: tool_result_budget ---
def _persist_large_output(tool_use_id: str, output: str) -> str:
    """将大输出持久化到磁盘，返回包含路径+预览的 XML 文本。"""
    if len(output) <= PERSIST_THRESHOLD:
        return output
    TOOL_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = TOOL_RESULTS_DIR / f"{tool_use_id}.txt"
    if not path.exists():
        path.write_text(output)
    return (
        f"<persisted-output>\n"
        f"Full output: {path}\n"
        f"Preview:\n{output[:2000]}\n"
        f"</persisted-output>"
    )


def tool_result_budget(messages: list) -> list:
    """L3: 检查最后一条消息中所有 tool_result 的总字节数，超过上限时持久化最大的结果。"""
    if not messages:
        return messages
    last = messages[-1]
    if last.get("role") != "user" or not isinstance(last.get("content"), list):
        return messages

    blocks = [
        (i, b)
        for i, b in enumerate(last["content"])
        if isinstance(b, dict) and b.get("type") == "tool_result"
    ]
    if not blocks:
        return messages

    total = sum(len(str(b.get("content", ""))) for _, b in blocks)
    if total <= MAX_TOOL_RESULT_BYTES:
        return messages

    print(f"{YELLOW}[L3 budget] total={total:,} bytes > {MAX_TOOL_RESULT_BYTES:,}, persisting large results...{RESET}")
    ranked = sorted(blocks, key=lambda p: len(str(p[1].get("content", ""))), reverse=True)
    persisted = 0
    for _, block in ranked:
        if total <= MAX_TOOL_RESULT_BYTES:
            break
        content = str(block.get("content", ""))
        if len(content) <= PERSIST_THRESHOLD:
            continue
        tid = block.get("tool_use_id", "unknown")
        block["content"] = _persist_large_output(tid, content)
        persisted += 1
        total = sum(len(str(b.get("content", ""))) for _, b in blocks)
    print(f"{YELLOW}[L3 budget] persisted {persisted} result(s), new total={total:,} bytes{RESET}")
    return messages


# --- L1: snip_compact ---
def snip_compact(messages: list, max_messages: int = MAX_MESSAGES) -> list:
    """L1: 消息数超过上限时，折叠中间部分，保留头部和尾部，不拆开 tool_use/tool_result 配对。"""
    if len(messages) <= max_messages:
        return messages

    keep_head = KEEP_HEAD
    keep_tail = max_messages - KEEP_HEAD
    head_end = keep_head
    tail_start = len(messages) - keep_tail

    # 如果 head_end 前一条是 tool_use，延伸 head_end 包含对应的 tool_result
    if head_end > 0 and _message_has_tool_use(messages[head_end - 1]):
        while head_end < len(messages) and _is_tool_result_message(messages[head_end]):
            head_end += 1

    # 如果 tail_start 处是 tool_result 且前一条是 tool_use，回退 tail_start
    if (tail_start > 0 and tail_start < len(messages)
            and _is_tool_result_message(messages[tail_start])
            and _message_has_tool_use(messages[tail_start - 1])):
        tail_start -= 1

    if head_end >= tail_start:
        return messages

    snipped = tail_start - head_end
    print(f"{CYAN}[L1 snip] {len(messages)} messages -> {head_end} head + [snipped {snipped}] + {len(messages) - tail_start} tail{RESET}")
    return messages[:head_end] + [
        {"role": "user", "content": f"[snipped {snipped} messages]"}
    ] + messages[tail_start:]


# --- L2: micro_compact ---
def collect_tool_results(messages: list) -> list:
    """收集所有 tool_result 的位置和内容。"""
    blocks = []
    for mi, msg in enumerate(messages):
        if msg.get("role") != "user" or not isinstance(msg.get("content"), list):
            continue
        for bi, block in enumerate(msg["content"]):
            if isinstance(block, dict) and block.get("type") == "tool_result":
                blocks.append((mi, bi, block))
    return blocks


def micro_compact(messages: list) -> list:
    """L2: 保留尾部 3 条 tool_result，其余超过 120 字符的替换为占位符。"""
    tool_results = collect_tool_results(messages)
    if len(tool_results) <= KEEP_RECENT:
        return messages
    replaced = 0
    for _, _, block in tool_results[:-KEEP_RECENT]:
        if len(block.get("content", "")) > 120:
            block["content"] = "[Earlier tool result compacted. Re-run if needed.]"
            replaced += 1
    if replaced > 0:
        print(f"{CYAN}[L2 micro] replaced {replaced} old tool_result(s) > 120 chars{RESET}")
    return messages


# --- L4: compact_history ---
def _write_transcript(messages: list):
    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    path = TRANSCRIPT_DIR / f"transcript_{int(time.time())}.jsonl"
    with path.open("w") as f:
        for msg in messages:
            f.write(json.dumps(msg, default=str) + "\n")
    return path


def _summarize_history(messages: list, client, model: str) -> str:
    """调用 LLM 对对话历史做摘要。"""
    conversation = json.dumps(messages, default=str)[:80_000]
    prompt = (
        "Summarize this coding-agent conversation so work can continue.\n"
        "Preserve: 1. current goal, 2. key findings/decisions, 3. files read/changed, "
        "4. remaining work, 5. user constraints.\n"
        "Be compact but concrete.\n\n"
        + conversation
    )
    response = client.messages.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=2000,
    )
    return "\n".join(
        getattr(block, "text", "")
        for block in response.content
        if getattr(block, "type", None) == "text"
    ).strip() or "(empty summary)"


def compact_history(messages: list, client, model: str) -> list:
    """L4: 调用 LLM 生成摘要，替换全部消息。"""
    path = _write_transcript(messages)
    print(f"[transcript saved: {path}]")
    summary = _summarize_history(messages, client, model)
    return [{"role": "user", "content": f"[Compacted]\n\n{summary}"}]


# --- Emergency: reactive_compact ---
MAX_REACTIVE_RETRIES = 1


def reactive_compact(messages: list, client, model: str) -> list:
    """紧急压缩：保留摘要 + 最后 5 条消息。"""
    path = _write_transcript(messages)
    print(f"[reactive transcript saved: {path}]")
    summary = _summarize_history(messages, client, model)
    tail_start = max(0, len(messages) - 5)
    # 不拆开 tool_use/tool_result 配对
    if (tail_start > 0 and tail_start < len(messages)
            and _is_tool_result_message(messages[tail_start])
            and _message_has_tool_use(messages[tail_start - 1])):
        tail_start -= 1
    return [{"role": "user", "content": f"[Reactive compact]\n\n{summary}"}] + messages[tail_start:]


# --- Pipeline ---
def run_compact_pipeline(messages: list, client, model: str, context_limit: int = CONTEXT_LIMIT):
    """执行压缩管道: L3 -> L1 -> L2 -> [阈值检查 -> L4]。原地修改 messages。只在有实际压缩时打印日志。"""
    original_len = len(json.dumps(messages, default=str, ensure_ascii=False))
    original_count = len(messages)

    messages[:] = tool_result_budget(messages)
    messages[:] = snip_compact(messages)
    messages[:] = micro_compact(messages)

    size = _estimate_size(messages)
    if size > context_limit:
        messages[:] = compact_history(messages, client, model)

    final_len = _estimate_size(messages)
    final_count = len(messages)
    if final_count != original_count or final_len != original_len:
        print(f"{GRAY}[compact] {original_count} msgs ({original_len:,} chars) -> "
              f"{final_count} msgs ({final_len:,} chars){RESET}")
