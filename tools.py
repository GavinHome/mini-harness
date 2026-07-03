"""
工具定义与执行模块
所有工具在此统一注册和管理
"""

from typing import Any, Dict
from utils.colors import RED, RESET


# ============================================
# 工具定义 (Tool Definitions)
# ============================================

TOOLS = [
    {
        "name": "write_file",
        "description": "将内容写入文件",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "文件路径"
                },
                "content": {
                    "type": "string",
                    "description": "文件内容"
                }
            },
            "required": ["path", "content"]
        }
    }
]


# ============================================
# 工具实现 (Tool Implementations)
# ============================================

def write_file(path: str, content: str) -> str:
    """将内容写入指定文件"""
    print(f"写入文件: {path}")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return f"文件 {path} 已写入"


# ============================================
# 工具注册表 (Tool Registry)
# ============================================

TOOLS_HANDLER: Dict[str, callable] = {
    "write_file": write_file,
}


# ============================================
# 工具执行器 (Tool Executor)
# ============================================

def execute_tool(item) -> Any:
    """执行工具调用"""
    print(f"{RED}执行工具: {item.name}{RESET}")
    print(f"{RED}工具参数: {item.input}{RESET}")
    handler = TOOLS_HANDLER.get(item.name)
    if not handler:
        raise ValueError(f"未知工具: {item.name}")
    return handler(**item.input)
