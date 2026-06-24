"""简单的处理记录缓存（避免重复抓字幕/分析同一个视频）。

存在 data/cache/processed.json，key 形如 "source_id:external_id"。
只记录"成功处理完"的条目；关键词未命中或抓字幕失败的不记，下次会重试。
"""

from __future__ import annotations

import json

from src.utils.config import PROJECT_ROOT
from src.utils.logger import get_logger

log = get_logger(__name__)

_CACHE_FILE = PROJECT_ROOT / "data" / "cache" / "processed.json"


def _load() -> dict:
    if not _CACHE_FILE.exists():
        return {}
    try:
        return json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def already_processed(key: str) -> bool:
    return key in _load()


def mark_processed(key: str, info: dict | None = None) -> None:
    data = _load()
    data[key] = info or {}
    _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _CACHE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
