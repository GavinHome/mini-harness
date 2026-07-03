"""
上下文管理模块
职责：估算 token 数量、显示上下文进度条
"""

import json

# 可根据实际使用的模型调整
MODEL_MAX_TOKENS = 200_000

# 基于实测：json.dumps 长度 / 3.5 ≈ 实际 token 数（含中英混排+JSON 结构）
_CHARS_PER_TOKEN_RATIO = 3.5


def get_context_stats(msgs) -> dict:
    """获取上下文统计信息（零 API 请求）。
    返回：{ char_len, estimated_tokens, pct }"""
    char_len = len(json.dumps(msgs, ensure_ascii=False))
    estimated_tokens = int(char_len / _CHARS_PER_TOKEN_RATIO)
    pct = estimated_tokens / MODEL_MAX_TOKENS * 100
    return {"char_len": char_len, "estimated_tokens": estimated_tokens, "pct": pct}


def show_context_bar(msgs, label: str = ""):
    """显示上下文进度条（基于估算值）"""
    from utils.colors import GRAY, RESET

    stats = get_context_stats(msgs)
    bar_len = 20
    filled = min(bar_len, int(bar_len * stats["estimated_tokens"] / MODEL_MAX_TOKENS))
    bar = "█" * filled + "░" * (bar_len - filled)
    prefix = f"{label} " if label else ""
    print(f"{GRAY}{prefix}上下文 [{bar}] ~{stats['estimated_tokens']:,} tok ({stats['pct']:.1f}%)  [{stats['char_len']:,} chars]{RESET}")
