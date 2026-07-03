import os
from pathlib import Path
from utils.readline_fix import fix_readline
from utils.serialize import serialize_content

fix_readline()

from anthropic import Anthropic
from dotenv import load_dotenv
from utils.colors import CYAN, GREEN, YELLOW, GRAY, MAGENTA, BLUE, RED, RESET
from tools import TOOLS, execute_tool
from permissions import check_permission
from context import get_context_stats, show_context_bar
from compact import run_compact_pipeline, reactive_compact, compact_history
from error_recovery import (
    RecoveryState, with_retry, is_prompt_too_long_error,
    ESCALATED_MAX_TOKENS, CONTINUATION_PROMPT, MAX_RECOVERY_RETRIES,
)

load_dotenv()

BASE_URL = os.getenv("ANTHROPIC_BASE_URL")
API_KEY = os.getenv("ANTHROPIC_API_KEY")
MODEL_ID = os.getenv("MODEL_ID")

print(f"{MAGENTA}BASE_URL={BASE_URL}{RESET}")
print(f"{MAGENTA}MODEL_ID={MODEL_ID}{RESET}")
print(f"{GRAY}{'='*50}{RESET}")
client = Anthropic(base_url=BASE_URL, api_key=API_KEY)

WORKSPACE_DIR = Path.cwd() / ".workspace"
WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)

SYSTEM_PROMPT = f"""
你是mini-harness, 工作目录是{WORKSPACE_DIR}, 使用工具完成任务。直接执行命令，不要解释。
"""
messages = []
total_input_tokens = 0
total_output_tokens = 0


def _validate_messages(messages):
    """Debug: catch empty content before API call."""
    for i, msg in enumerate(messages):
        content = msg.get("content")
        if not content and content != 0:
            print(f"{RED}[BUG] messages[{i}] has empty content: role={msg.get('role')}, content={content!r}{RESET}")


def agent_loop(messages, max_turns=10, on_usage=None):
    state = RecoveryState(current_model=MODEL_ID)
    max_tokens = 8192

    while max_turns > 0:
        # ── 压缩管道 (L3 -> L1 -> L2 -> L4) ──
        run_compact_pipeline(messages, client, MODEL_ID)

        # ── Debug: validate messages before API call ──
        _validate_messages(messages)

        # ── LLM 调用: with_retry 处理 429/529, 外层处理 prompt_too_long ──
        try:
            response = with_retry(
                lambda mt=max_tokens, mdl=state.current_model:
                    client.messages.create(
                        model=mdl,
                        max_tokens=mt,
                        system=SYSTEM_PROMPT,
                        messages=messages,
                        tools=TOOLS,
                    ),
                state,
            )
        except Exception as e:
            # Path 2: prompt_too_long -> reactive compact (一次机会)
            if is_prompt_too_long_error(e) and not state.has_attempted_reactive_compact:
                print(f"{YELLOW}[reactive compact] prompt too long{RESET}")
                messages[:] = reactive_compact(messages, client, MODEL_ID)
                state.has_attempted_reactive_compact = True
                continue
            # 不可恢复
            name = type(e).__name__
            print(f"{RED}[error] {name}: {str(e)[:100]}{RESET}")
            return

        # ── Path 1: max_tokens 截断 -> 升级 或 续写 ──
        if response.stop_reason == "max_tokens":
            if not state.has_escalated:
                max_tokens = ESCALATED_MAX_TOKENS
                state.has_escalated = True
                print(f"{YELLOW}[max_tokens] escalating {8192} -> {ESCALATED_MAX_TOKENS}{RESET}")
                continue  # 不追加截断输出, 同一请求升级后重试
            # 升级后仍截断: 保存输出 + 续写提示
            serialized = serialize_content(response.content)
            if not serialized:
                serialized = serialize_content(response.content, filter_thinking=False)
            messages.append({ "role": "assistant", "content": serialized })
            if state.recovery_count < MAX_RECOVERY_RETRIES:
                messages.append({ "role": "user", "content": CONTINUATION_PROMPT })
                state.recovery_count += 1
                print(f"{YELLOW}[max_tokens] continuation {state.recovery_count}/{MAX_RECOVERY_RETRIES}{RESET}")
                max_turns -= 1
                continue
            print(f"{RED}[max_tokens] recovery limit reached{RESET}")
            max_turns -= 1
            return

        # ── 正常完成: 追加 assistant 消息 ──
        serialized = serialize_content(response.content)
        if not serialized:
            # 过滤后为空（只有 thinking block），保留原始内容避免 content=[]
            serialized = serialize_content(response.content, filter_thinking=False)
        messages.append({ "role": "assistant", "content": serialized })
        max_turns -= 1

        if on_usage:
            on_usage(response.usage)

        # ── thinking 输出 ──
        if isinstance(response.content, list):
            for item in response.content:
                if item.type == "thinking":
                    print(f"{CYAN}thinking: {item.thinking}{RESET}")
                    print(f"{GRAY}{'='*50}{RESET}")

        # ── stop_reason 分发 ──
        if response.stop_reason == "tool_use":
            tool_results = []
            compact_called = False
            for item in response.content:
                if item.type != "tool_use":
                    continue
                # compact 工具: 立即触发 compact_history
                if item.name == "compact":
                    print(f"{YELLOW}[compact] user triggered summary{RESET}")
                    messages[:] = compact_history(messages, client, MODEL_ID)
                    tool_results.append({ "type": "tool_result", "tool_use_id": item.id,
                                         "content": "[Compacted. Conversation history has been summarized.]" })
                    messages.append({ "role": "user", "content": tool_results })
                    compact_called = True
                    break

                if not check_permission(item):
                    tool_results.append({"type": "tool_result", "tool_use_id": item.id, "content": "权限不足，无法执行工具"})
                    continue

                result = execute_tool(item)
                tool_results.append({ "type": "tool_result", "tool_use_id": item.id, "content": result })

            if not compact_called:
                messages.append({ "role": "user", "content": tool_results })
            continue  # tool_use 分支后继续下一轮
        else:
            for item in response.content:
                if item.type == "text":
                    print(f"{GREEN}assistant: {item.text}{RESET}")
                    print(f"{GRAY}{'='*50}{RESET}")
                    return

if __name__ == "__main__":
    print(f"{CYAN}输入问题，回车发送，输入 q 退出: {RESET}")
    while True:
        query = input(f"{CYAN}mini-harness >> {RESET}")

        if query.strip().lower() in ("exit", "quit", "q"):
            break

        messages.append({ "role": "user", "content": query })

        # ── 上下文大小（发送前）──
        show_context_bar(messages, "发送前")

        tokens = { "input": 0, "output": 0 }
        def on_usage(usage):
            tokens["input"] += usage.input_tokens
            tokens["output"] += usage.output_tokens

        agent_loop(messages, on_usage=on_usage)
        round_input_tokens, round_output_tokens = tokens["input"], tokens["output"]

        # ── 上下文大小（执行完工具结果已回写后）──
        show_context_bar(messages, "回写后")

        print(f"{YELLOW}\n--- Token 统计 ---{RESET}")
        print(f"{YELLOW}本轮: 总共={round_input_tokens + round_output_tokens} 输入={round_input_tokens} 输出={round_output_tokens}{RESET}")

        total_input_tokens += round_input_tokens
        total_output_tokens += round_output_tokens
        print(f"{YELLOW}总计: 总共={total_input_tokens + total_output_tokens} 输入={total_input_tokens} 输出={total_output_tokens}{RESET}")
