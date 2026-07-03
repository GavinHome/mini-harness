"""
错误恢复模块 (Error Recovery)
三种恢复模式：
  1. max_tokens 截断 -> 升级 8K->64K, 或续写提示 (最多 3 次)
  2. prompt_too_long -> reactive compact -> 重试 (一次)
  3. 429/529      -> 指数退避 + 抖动, 连续 529 切换备用模型

Cheap first, expensive last: with_retry 处理瞬态错误，外层 try/except 处理业务错误。
"""

import os
import time
import random

from utils.colors import YELLOW, RED, GRAY, RESET
from dotenv import load_dotenv

load_dotenv()

# ── 常量 ──
ESCALATED_MAX_TOKENS = 64_000
DEFAULT_MAX_TOKENS = 8_192
MAX_RECOVERY_RETRIES = 3
MAX_RETRIES = 10
BASE_DELAY_MS = 500
MAX_CONSECUTIVE_529 = 3
CONTINUATION_PROMPT = (
    "Output token limit hit. Resume directly — "
    "no apology, no recap. Pick up mid-thought."
)

FALLBACK_MODEL = os.getenv("FALLBACK_MODEL_ID")
PRIMARY_MODEL = os.getenv("MODEL_ID")


class RecoveryState:
    """跨循环追踪恢复状态"""

    def __init__(self, current_model: str = None):
        self.has_escalated = False
        self.recovery_count = 0
        self.consecutive_529 = 0
        self.has_attempted_reactive_compact = False
        self.has_switched_to_fallback = False
        self.current_model = current_model or PRIMARY_MODEL


def retry_delay(attempt: int, retry_after: float = None) -> float:
    """指数退避 + 抖动。Retry-After header 优先。"""
    if retry_after is not None:
        return retry_after
    base = min(BASE_DELAY_MS * (2 ** attempt), 32_000) / 1000
    jitter = random.uniform(0, base * 0.25)
    return base + jitter


def with_retry(fn, state: RecoveryState):
    """包裹 LLM 调用，处理瞬态错误 (429/529)。非瞬态错误抛出给外层。"""
    for attempt in range(MAX_RETRIES):
        try:
            result = fn()
            state.consecutive_529 = 0  # 成功则重置
            return result
        except Exception as e:
            name = type(e).__name__
            msg = str(e).lower()

            # 429 rate limit
            if "ratelimit" in name.lower() or "429" in msg:
                delay = retry_delay(attempt)
                print(f"  {YELLOW}[429 rate limit] retry {attempt + 1}/{MAX_RETRIES},"
                      f" wait {delay:.1f}s{RESET}")
                time.sleep(delay)
                continue

            # 529 overloaded
            if "overloaded" in name.lower() or "529" in msg:
                state.consecutive_529 += 1
                if state.consecutive_529 >= MAX_CONSECUTIVE_529 and FALLBACK_MODEL:
                    if not state.has_switched_to_fallback:
                        # 第一次切换: 切到备用模型, 重置计数
                        state.current_model = FALLBACK_MODEL
                        state.has_switched_to_fallback = True
                        state.consecutive_529 = 0
                        print(f"  {RED}[529 x{MAX_CONSECUTIVE_529}]"
                              f" switching to {FALLBACK_MODEL}{RESET}")
                    else:
                        # 备用模型也连续 529, 不再切换, 继续退避重试直到耗尽
                        print(f"  {RED}[529 x{MAX_CONSECUTIVE_529}]"
                              f" fallback also failing, retrying{RESET}")
                delay = retry_delay(attempt)
                print(f"  {YELLOW}[529 overloaded] retry {attempt + 1}/{MAX_RETRIES},"
                      f" wait {delay:.1f}s{RESET}")
                time.sleep(delay)
                continue

            # 非瞬态错误 -> 交给外层处理
            raise

    raise RuntimeError(f"Max retries ({MAX_RETRIES}) exceeded")


def is_prompt_too_long_error(e: Exception) -> bool:
    """判断是否为上下文超限错误。"""
    msg = str(e).lower()
    return (
        "prompt" in msg and "long" in msg
        or "prompt_is_too_long" in msg
        or "context_length_exceeded" in msg
        or "max_context_window" in msg
    )
