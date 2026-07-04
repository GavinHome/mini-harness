"""
集中式配置 — 所有配置只在此读取一次，后续从缓存获取。

来源：
  - .env 文件（通过 load_dotenv）
  - 运行时路径（WORKSPACE_DIR / WORKDIR）
  - API 客户端（Anthropic）
"""

import os
from pathlib import Path
from dotenv import load_dotenv
from anthropic import Anthropic

# ── .env 只加载一次 ──
load_dotenv()

# ── 环境变量 ──
BASE_URL = os.getenv("ANTHROPIC_BASE_URL")
API_KEY = os.getenv("ANTHROPIC_API_KEY")
MODEL_ID = os.getenv("MODEL_ID")
FALLBACK_MODEL_ID = os.getenv("FALLBACK_MODEL_ID")

# ── 路径 ──
WORKDIR = Path.cwd()
WORKSPACE_DIR = WORKDIR / ".workspace"
WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)

# ── API 客户端 ──
client = Anthropic(base_url=BASE_URL, api_key=API_KEY)
