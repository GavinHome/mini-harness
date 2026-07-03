"""
消息序列化工具
将 Anthropic SDK Block 对象转为纯 dict，统一由 history.py 提供具体策略。
本模块只做底层转换，不做过滤判断。
"""


def block_to_dict(item) -> dict | None:
    """把单个 Anthropic SDK Block 对象转为纯 dict。
    返回 None 表示无法识别的类型。"""
    if isinstance(item, dict):
        return item
    if not hasattr(item, "type"):
        return None
    t = item.type
    if t == "thinking":
        return {"type": "thinking", "thinking": getattr(item, "thinking", ""),
                "signature": getattr(item, "signature", "")}
    if t == "text":
        return {"type": "text", "text": getattr(item, "text", "")}
    if t == "tool_use":
        return {"type": "tool_use", "name": getattr(item, "name", ""),
                "input": getattr(item, "input", {}), "id": getattr(item, "id", "")}
    if t == "tool_result":
        return {"type": "tool_result", "tool_use_id": getattr(item, "tool_use_id", ""),
                "content": getattr(item, "content", "")}
    return {"type": t, "raw": str(item)}


def serialize_content(content, filter_thinking: bool = True) -> list:
    """把 Anthropic SDK 返回的 response.content 转为纯 list[dict]。

    参数：
        content: SDK 返回的 response.content（可能含 Block 对象）
        filter_thinking: True=过滤掉 thinking block（发给 API 用）
                        False=保留 thinking block（持久化用）

    SDK 对象（ThinkingBlock, ToolUseBlock, TextBlock 等）不能直接 json.dumps，
    存 messages 前统一转成 dict，确保后续序列化和下一次 API 调用都不会报错。
    """
    if not isinstance(content, list):
        return content
    result = []
    for item in content:
        if isinstance(item, dict):
            result.append(item)
            continue
        d = block_to_dict(item)
        if d is None:
            continue
        if filter_thinking and d["type"] == "thinking":
            continue
        result.append(d)
    return result
