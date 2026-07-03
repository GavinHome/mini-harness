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
from compact import run_compact_pipeline, reactive_compact, MAX_REACTIVE_RETRIES, compact_history

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


def agent_loop(messages, max_turns=10, on_usage=None):
    reactive_retries = 0
    while max_turns > 0:
        # ── 压缩管道 (L3 -> L1 -> L2 -> L4) ──
        run_compact_pipeline(messages, client, MODEL_ID)

        try:
            response = client.messages.create(
                model=MODEL_ID,
                max_tokens=8192,
                system=SYSTEM_PROMPT,
                messages=messages,
                tools=TOOLS,
                # stream=True
            )
            reactive_retries = 0  # 成功调用后重置重试计数
        except Exception as e:
            error_str = str(e).lower()
            if ("prompt_too_long" in error_str or "too many tokens" in error_str) and reactive_retries < MAX_REACTIVE_RETRIES:
                print(f"{YELLOW}[reactive compact]{RESET}")
                messages[:] = reactive_compact(messages, client, MODEL_ID)
                reactive_retries += 1
                continue
            raise

        messages.append({ "role": "assistant", "content": serialize_content(response.content) })
        max_turns -= 1

        if on_usage:
            on_usage(response.usage)

        if isinstance(response.content, list):
            for item in response.content:
                if item.type == "thinking":
                    print(f"{CYAN}thinking: {item.thinking}{RESET}")
                    print(f"{GRAY}{'='*50}{RESET}")

        if response.stop_reason == "tool_use":
            tool_results = []
            for item in response.content:
                if item.type == "tool_use":
                    # compact 工具：立即触发 compact_history
                    if item.name == "compact":
                        print(f"{YELLOW}[compact] user triggered summary{RESET}")
                        messages[:] = compact_history(messages, client, MODEL_ID)
                        tool_results.append({ "type": "tool_result", "tool_use_id": item.id,
                                             "content": "[Compacted. Conversation history has been summarized.]" })
                        messages.append({ "role": "user", "content": tool_results })
                        break

                    if not check_permission(item):
                        tool_results.append({"type": "tool_result", "tool_use_id": item.id, "content": "权限不足，无法执行工具"})
                        continue

                    result = execute_tool(item)
                    tool_results.append({ "type": "tool_result", "tool_use_id": item.id, "content": result })

            messages.append({ "role": "user", "content": tool_results })
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
