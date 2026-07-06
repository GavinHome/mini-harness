from utils.readline_fix import fix_readline
from utils.serialize import serialize_content

fix_readline()

from utils.colors import CYAN, GREEN, YELLOW, GRAY, MAGENTA, BLUE, RED, RESET
from config import BASE_URL, API_KEY, MODEL_ID, WORKSPACE_DIR, client
from tools import TOOLS, execute_tool
from hooks import trigger_hooks
from system_prompt import get_system_prompt, update_context
from context import get_context_stats, show_context_bar
from compact import run_compact_pipeline, reactive_compact, compact_history
from error_recovery import (
    RecoveryState, with_retry, is_prompt_too_long_error,
    ESCALATED_MAX_TOKENS, CONTINUATION_PROMPT, MAX_RECOVERY_RETRIES,
)
from memory import extract_memories, inject_memories, load_memories, consolidate_memories
from teams import consume_lead_inbox

print(f"{MAGENTA}BASE_URL={BASE_URL}{RESET}")
print(f"{MAGENTA}MODEL_ID={MODEL_ID}{RESET}")
print(f"{GRAY}{'='*50}{RESET}")

messages = []
total_input_tokens = 0
total_output_tokens = 0
rounds_since_todo = 0


def agent_loop(messages, max_turns=10, context=None):
    state = RecoveryState(current_model=MODEL_ID)
    max_tokens = 8192
    usage = {"input": 0, "output": 0}

    context = update_context(context or {}, messages)

    while max_turns > 0:
        # ── Nag reminder: 3 轮未更新 todo → 强制回顾 ──
        global rounds_since_todo
        if rounds_since_todo >= 3 and messages:
            messages.append({"role": "user",
                             "content": "<reminder>Update your todos.</reminder>"})
            rounds_since_todo = 0

        # ── 压缩前快照（记忆提取用，保留原始对话完整度）──
        pre_compress = [
            m if isinstance(m, dict) else {"role": m.get("role", ""), "content": str(m.get("content", ""))}
            for m in messages
        ]

        # ── 压缩管道 (L3 -> L1 -> L2 -> L4) ──
        run_compact_pipeline(messages, client, MODEL_ID)

        # 消息变化后刷新 context
        context = update_context(context, messages)

        # ── 记忆注入（每轮只做一次 side-query）──
        request_messages = inject_memories(messages)

        # ── LLM 调用: with_retry 处理 429/529, 外层处理 prompt_too_long ──
        try:
            response = with_retry(
                lambda mt=max_tokens, mdl=state.current_model:
                    client.messages.create(
                        model=mdl,
                        max_tokens=mt,
                        system=get_system_prompt(context),
                        messages=request_messages,
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
            return usage, context

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
            return usage, context

        # ── 正常完成: 追加 assistant 消息 ──
        serialized = serialize_content(response.content)
        if not serialized:
            # 过滤后为空（只有 thinking block），保留原始内容避免 content=[]
            serialized = serialize_content(response.content, filter_thinking=False)
        messages.append({ "role": "assistant", "content": serialized })
        max_turns -= 1

        usage["input"] += response.usage.input_tokens
        usage["output"] += response.usage.output_tokens

        # ── thinking 输出 ──
        if isinstance(response.content, list):
            for item in response.content:
                if item.type == "thinking":
                    print(f"{CYAN}thinking: {item.thinking}{RESET}")
                    print(f"{GRAY}{'='*50}{RESET}")

        # ── stop_reason 分发 ──
        if response.stop_reason == "tool_use":
            rounds_since_todo += 1
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

                blocked = trigger_hooks("PreToolUse", item)
                if blocked:
                    tool_results.append({"type": "tool_result", "tool_use_id": item.id,
                                         "content": blocked})
                    continue

                result = execute_tool(item)
                trigger_hooks("PostToolUse", item, result)
                tool_results.append({ "type": "tool_result", "tool_use_id": item.id,
                                     "content": result })

                # todo_write 调用后归零计数器
                if item.name == "todo_write":
                    rounds_since_todo = 0

            if not compact_called:
                messages.append({ "role": "user", "content": tool_results })
            continue  # tool_use 分支后继续下一轮
        else:
            trigger_hooks("Stop", messages)
            extract_memories(pre_compress)
            consolidate_memories()
            return usage, context

if __name__ == "__main__":
    print(f"{CYAN}输入问题，回车发送，输入 q 退出: {RESET}")
    context = {}
    while True:
        query = input(f"{CYAN}mini-harness >> {RESET}")

        if query.strip().lower() in ("exit", "quit", "q"):
            break

        blocked = trigger_hooks("UserPromptSubmit", query)
        if blocked:
            continue

        messages.append({ "role": "user", "content": query })

        # ── 队友收件箱（在 agent_loop 前注入，Lead 本轮可见）──
        inbox = consume_lead_inbox(route_protocol=True)
        if inbox:
            inbox_text = "\n".join(
                f"From {m['from']} [{m['type']}]: {m['content'][:200]}"
                for m in inbox)
            messages.append({"role": "user",
                "content": f"[Inbox]\n{inbox_text}"})

        # ── 上下文大小（发送前）──
        show_context_bar(messages, "发送前")

        usage, context = agent_loop(messages, context=context)
        round_input_tokens = usage["input"]
        round_output_tokens = usage["output"]

        # ── 上下文大小（执行完工具结果已回写后）──
        show_context_bar(messages, "回写后")

        print(f"{YELLOW}\n--- Token 统计 ---{RESET}")
        print(f"{YELLOW}本轮: 总共={round_input_tokens + round_output_tokens} 输入={round_input_tokens} 输出={round_output_tokens}{RESET}")

        total_input_tokens += round_input_tokens
        total_output_tokens += round_output_tokens
        print(f"{YELLOW}总计: 总共={total_input_tokens + total_output_tokens} 输入={total_input_tokens} 输出={total_output_tokens}{RESET}")
