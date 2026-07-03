"""
Token 使用统计模块
统计和显示 API 调用的 token 使用情况
"""

from typing import Optional
from utils.colors import YELLOW, RESET


def print_token_usage(
    input_tokens: int,
    output_tokens: int,
    label: str = "Token 使用统计"
) -> None:
    """
    打印 token 使用统计信息
    
    Args:
        input_tokens: 输入 token 数
        output_tokens: 输出 token 数
        label: 统计标题
    """
    total = input_tokens + output_tokens
    print(f"\n{YELLOW}--- {label} ---{RESET}")
    print(f"{YELLOW}输入 token: {input_tokens}{RESET}")
    print(f"{YELLOW}输出 token: {output_tokens}{RESET}")
    print(f"{YELLOW}总 token: {total}{RESET}")


def format_token_usage(
    input_tokens: int,
    output_tokens: int
) -> dict:
    """
    格式化 token 使用数据
    
    Returns:
        dict: 包含 token 统计的字典
    """
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens
    }
