"""
基础工具层 (Base Tools)

纯函数实现，零循环依赖。
tools.py 和 subagent.py 都从此模块导入基础工具函数。
"""

import subprocess
from pathlib import Path

from config import WORKSPACE_DIR


# ============================================
# 基础工具函数
# ============================================

def run_bash(command: str, cwd: str | None = None) -> str:
    print(f"执行命令: {command}")
    workdir = Path(cwd) if cwd else WORKSPACE_DIR
    result = subprocess.run(
        command,
        shell=True,
        cwd=workdir,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        return f"命令执行失败 (exit code {result.returncode}):\nstdout: {result.stdout}\nstderr: {result.stderr}"
    return f"命令执行成功:\nstdout: {result.stdout}"


def safe_path(path: str, cwd: str | None = None) -> Path:
    p = Path(path)
    base = Path(cwd) if cwd else WORKSPACE_DIR
    if p.is_absolute():
        resolved = p.resolve()
    else:
        resolved = (base / p).resolve()
    if not resolved.is_relative_to(WORKSPACE_DIR):
        raise ValueError(f"路径 {path} 不在安全工作目录 {WORKSPACE_DIR} 内")
    return resolved


def read_file(path: str, cwd: str | None = None) -> str:
    safe = safe_path(path, cwd)
    print(f"读取文件: {safe}")
    if not safe.exists():
        return f"文件不存在: {path}"
    if not safe.is_file():
        return f"{path} 不是文件"
    with open(safe, "r", encoding="utf-8") as f:
        return f.read()


def write_file(path: str, content: str, cwd: str | None = None) -> str:
    safe = safe_path(path, cwd)
    print(f"写入文件: {safe}")
    safe.parent.mkdir(parents=True, exist_ok=True)
    with open(safe, "w", encoding="utf-8") as f:
        f.write(content)
    return f"文件 {path} 已写入"


def edit_file(path: str, old_string: str, new_string: str) -> str:
    safe = safe_path(path)
    print(f"编辑文件: {safe}")
    if not safe.exists():
        return f"文件不存在: {path}"
    if not safe.is_file():
        return f"{path} 不是文件"
    with open(safe, "r", encoding="utf-8") as f:
        content = f.read()
    if old_string not in content:
        return f"未找到要替换的内容: {old_string[:50]}..."
    new_content = content.replace(old_string, new_string)
    with open(safe, "w", encoding="utf-8") as f:
        f.write(new_content)
    return f"文件 {path} 已编辑"


def glob_file(pattern: str) -> str:
    print(f"查找文件: {pattern}")
    matches = list(WORKSPACE_DIR.glob(pattern))
    if not matches:
        return f"未找到匹配 {pattern} 的文件"
    return "\n".join(str(p) for p in matches)
