"""
Skills 机制 — 文件驱动的 skill 发现与加载。

设计：
  skills/ 目录下每个子目录是一个 skill，包含 SKILL.md（YAML frontmatter + 内容）
  scan_skills() 扫描并填充 SKILL_REGISTRY
  list_skills() 返回目录摘要，注入 system prompt
  load_skill(name) 按需加载完整内容

注意：scan_skills() 不自动调用，由 main 入口显式调用以保证初始化顺序清晰。
"""

import yaml
from pathlib import Path

from config import WORKDIR

SKILLS_DIR = WORKDIR / "skills"
SKILLS_DIR.mkdir(parents=True, exist_ok=True)

SKILL_REGISTRY: dict[str, dict] = {}


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """解析 SKILL.md 的 YAML frontmatter。返回 (meta, body)。"""
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    try:
        meta = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        meta = {}
    return meta, parts[2].strip()


def scan_skills():
    """扫描 skills/ 目录，将 SKILL.md 解析后填入 SKILL_REGISTRY。"""
    SKILL_REGISTRY.clear()
    if not SKILLS_DIR.exists():
        return
    for directory in sorted(SKILLS_DIR.iterdir()):
        if not directory.is_dir():
            continue
        manifest = directory / "SKILL.md"
        if not manifest.exists():
            continue
        raw = manifest.read_text()
        meta, _ = _parse_frontmatter(raw)
        name = meta.get("name", directory.name)
        desc = meta.get("description", raw.split("\n")[0].lstrip("#").strip())
        SKILL_REGISTRY[name] = {
            "name": name,
            "description": desc,
            "content": raw,
        }


def list_skills() -> str:
    """返回格式化后的 skill 目录，供 system prompt 注入。"""
    if not SKILL_REGISTRY:
        return "(no skills found)"
    return "\n".join(
        f"- {skill['name']}: {skill['description']}"
        for skill in SKILL_REGISTRY.values()
    )


def load_skill(name: str) -> str:
    """按名称加载 skill 的完整内容。"""
    skill = SKILL_REGISTRY.get(name)
    if not skill:
        available = ", ".join(SKILL_REGISTRY.keys()) or "(none)"
        return f"Skill not found: {name}. Available: {available}"
    return skill["content"]
