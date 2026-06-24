"""读取配置：.env 里的密钥/模型名，以及 config/ 下的 YAML 文件。

设计原则：所有“路径/读取文件”的逻辑都集中在这里，其他模块只管调用，
不用关心文件在哪、怎么读。
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

# 项目根目录 = 这个文件往上数三层（src/utils/config.py -> 项目根）
PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "config"
PROMPTS_DIR = PROJECT_ROOT / "src" / "prompts"

# 加载 .env（如果存在）。override=False：已有的环境变量优先。
load_dotenv(PROJECT_ROOT / ".env", override=False)


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"找不到配置文件：{path}")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_sources() -> dict:
    """返回 config/sources.yaml 的内容（含 window_days 和 sources 列表）。"""
    return _load_yaml(CONFIG_DIR / "sources.yaml")


def get_filters() -> dict:
    """返回 config/filters.yaml 的内容（筛选标准 + 分析框架）。"""
    return _load_yaml(CONFIG_DIR / "filters.yaml")


def load_prompt(filename: str) -> str:
    """读取 src/prompts/ 下的 Prompt 模板文件。"""
    path = PROMPTS_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"找不到 Prompt 模板：{path}")
    return path.read_text(encoding="utf-8")


def get_env(name: str, default: str | None = None) -> str | None:
    return os.getenv(name, default)
